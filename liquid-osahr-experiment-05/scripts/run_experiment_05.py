#!/usr/bin/env python3
"""Experiment 05 stages: freeze, instrument, confirm, analyze.

Confirmatory execution is refused until artifacts/FROZEN.json matches the
claim grammar. Formulation does not run the 22 s confirmatory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from liquid_osahr05.protocol import (
    ART,
    CLAIM_GRAMMAR_VERSION,
    CONF_CSV,
    CONFIRMATORY_SEED,
    EPS_SENSITIVITY,
    EPS_ZERO,
    ESTIMANDS,
    EXP02B,
    FROZEN_PATH,
    GRAMMAR_FILES,
    GRID,
    HORIZON,
    INSTRUMENT_04_CSV,
    N_SCENARIOS,
    PRIMARY_ESTIMAND,
    REGIMES,
    REPLICATES,
)
from liquid_osahr05.score import annotate_foils, claims_frame, load_table, score_table, summarize_claims


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grammar_checksum() -> str:
    h = hashlib.sha256()
    for path in GRAMMAR_FILES:
        h.update(path.read_bytes())
    return h.hexdigest()


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if hasattr(obj, "item"):
        return obj.item()
    return obj


def _fmt_ci(block: dict) -> str:
    return f"{block['mean']:.5f}  [{block['lo']:.5f}, {block['hi']:.5f}]"


def require_freeze() -> dict:
    if not FROZEN_PATH.exists():
        raise SystemExit("refusing confirmatory: artifacts/FROZEN.json missing")
    freeze = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
    if freeze["grammar_sha256"] != grammar_checksum():
        raise SystemExit("claim grammar changed after freeze")
    if freeze["confirmatory_seed_declared"] != CONFIRMATORY_SEED:
        raise SystemExit("confirmatory seed drifted from freeze")
    if freeze["horizon"] != HORIZON:
        raise SystemExit("horizon drifted from freeze")
    return freeze


def evaluate_table(df, *, horizon: float, label: str, seed: int) -> dict:
    payload = {"label": label, "horizon": horizon, "n_rows": int(len(df)), "estimands": {}}
    ART.mkdir(parents=True, exist_ok=True)
    for i, estimand in enumerate(ESTIMANDS):
        by_eps = {}
        for j, eps in enumerate((EPS_ZERO, EPS_SENSITIVITY)):
            claims = score_table(df, estimand=estimand, horizon=horizon, eps=eps)
            frame = annotate_foils(claims)
            stem = f"{label}_{estimand}_eps{eps:.2f}"
            frame.to_csv(ART / f"claims_{stem}.csv", index=False)
            by_eps[f"{eps:.2f}"] = summarize_claims(frame, seed=seed + 1000 * i + 10 * j)
        payload["estimands"][estimand] = by_eps
    return payload


def stage_freeze() -> None:
    if CONF_CSV.exists():
        raise SystemExit("confirmatory CSV already exists; freeze must precede confirmatory")
    ART.mkdir(parents=True, exist_ok=True)
    freeze = {
        "protocol_status": "FROZEN before confirmatory root seed 110518 was executed",
        "claim_grammar_version": CLAIM_GRAMMAR_VERSION,
        "confirmatory_seed_declared": CONFIRMATORY_SEED,
        "horizon": HORIZON,
        "grid": list(GRID),
        "eps_zero": EPS_ZERO,
        "eps_sensitivity": EPS_SENSITIVITY,
        "regimes": list(REGIMES),
        "n_scenarios": N_SCENARIOS,
        "replicates": REPLICATES,
        "residual_checkpoint": str(EXP02B / "artifacts" / "residual_cfc.pt"),
        "grammar_files": [str(p) for p in GRAMMAR_FILES],
        "grammar_sha256": grammar_checksum(),
        "answering_object": "claim_status",
        "selects_alpha": False,
    }
    tmp = FROZEN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(freeze, indent=2), encoding="utf-8")
    tmp.replace(FROZEN_PATH)
    print("FROZE", FROZEN_PATH)


def stage_instrument() -> dict:
    if not INSTRUMENT_04_CSV.exists():
        raise SystemExit(f"04 confirmatory CSV missing: {INSTRUMENT_04_CSV}")
    df = load_table(INSTRUMENT_04_CSV)
    payload = evaluate_table(df, horizon=3.0, label="instrument_h3", seed=50_518)
    payload["source_csv"] = str(INSTRUMENT_04_CSV)
    payload["source_sha256"] = _sha256(INSTRUMENT_04_CSV)
    payload["labeled"] = "NOT a 05 confirmation; 04 holdout at h=3 s"
    (ART / "instrument_h3.json").write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")
    write_report(ROOT / "EXPERIMENT_REPORT.md", instrument=payload, confirmatory=None)
    print("WROTE", ART / "instrument_h3.json")
    return payload


def stage_confirm() -> None:
    freeze = require_freeze()
    from liquid_osahr05.simulate import run_confirmatory

    run_confirmatory(combined_csv=CONF_CSV, horizon=HORIZON, root_seed=freeze["confirmatory_seed_declared"])


def stage_analyze() -> None:
    freeze = require_freeze()
    if not CONF_CSV.exists():
        raise SystemExit("confirmatory CSV missing")
    df = load_table(CONF_CSV)
    payload = evaluate_table(df, horizon=HORIZON, label="confirmatory_h22", seed=110_518)
    payload["source_csv"] = str(CONF_CSV)
    payload["source_sha256"] = _sha256(CONF_CSV)
    payload["freeze"] = freeze
    instrument = None
    inst_path = ART / "instrument_h3.json"
    if inst_path.exists():
        instrument = json.loads(inst_path.read_text(encoding="utf-8"))
    (ART / "confirmatory_evaluation.json").write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")
    write_report(ROOT / "EXPERIMENT_REPORT.md", instrument=instrument, confirmatory=payload)
    manifest = {
        "experiment": "liquid-osahr-experiment-05",
        "confirmatory_seed": CONFIRMATORY_SEED,
        "horizon": HORIZON,
        "grammar_sha256": freeze["grammar_sha256"],
        "confirmatory_sha256": _sha256(CONF_CSV),
        "frozen": True,
        "selects_alpha": False,
    }
    (ROOT / "RUN_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def _status_row(summary: dict, status: str) -> str:
    block = summary["rates"][status]["macro"]
    count = summary["status_counts"][status]
    return f"| {status} | {count} | {_fmt_ci(block)} |"


def write_report(path: Path, *, instrument: dict | None, confirmatory: dict | None) -> None:
    lines = [
        "# Experiment 05 Report: Residual-Hypothesis Claim Status",
        "",
        "**Answering object:** claim status, not a point T to alpha*.",
        f"**Confirmatory seed (declared):** `{CONFIRMATORY_SEED}`. **Horizon:** {HORIZON} s.",
        "",
    ]
    if confirmatory is None:
        lines += [
            "**Confirmatory status:** not executed. This report is formulation plus the labeled h=3 s instrument check.",
            "",
        ]
    if instrument is not None:
        prim = instrument["estimands"][PRIMARY_ESTIMAND]["0.00"]
        lines += [
            "## Instrument check (04 holdout, h=3 s), not confirmatory",
            "",
            f"Source SHA-256 `{instrument['source_sha256'][:16]}…`. Independent units: {prim['n']}. Expressed: {prim['expressed_n']}.",
            "",
            "Goal-utility status counts at eps=0:",
            "",
            "| Status | Count | Macro rate (95% CI) |",
            "|---|---:|---|",
            _status_row(prim, "outcome_unknown"),
            _status_row(prim, "admit"),
            _status_row(prim, "hold_unresolved"),
            _status_row(prim, "reject"),
            "",
            f"Activation without effect: `{_fmt_ci(prim['activation_without_effect'])}`.",
            f"Illegal promotion of 04 `T_strict` among expressed: `{_fmt_ci(prim['foils']['T04_strict']['among_expressed'])}`.",
            f"Illegal promotion of global alpha=1 among expressed: `{_fmt_ci(prim['foils']['alpha1']['among_expressed'])}`.",
            "",
            "Other estimands (unknown / admit / hold / reject):",
            "",
            "| Estimand | eps | Unknown | Admit | Hold | Reject | Expressed |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for estimand in ESTIMANDS:
            for eps_key in ("0.00", "0.02"):
                block = instrument["estimands"][estimand][eps_key]
                c = block["status_counts"]
                lines.append(
                    f"| {estimand} | {eps_key} | {c['outcome_unknown']} | {c['admit']} | {c['hold_unresolved']} | {c['reject']} | {block['expressed_n']} |"
                )
        lines += [
            "",
            "Latency at eps=0 is saturated (every scenario has a nonzero contrast). Read latency at eps=0.02.",
            "This table tests the instrument. It is not a 05 confirmation.",
            "",
        ]
    if confirmatory is not None:
        prim = confirmatory["estimands"][PRIMARY_ESTIMAND]["0.00"]
        lines += [
            "## Confirmatory (h=22 s, seed 110518)",
            "",
            f"Independent units: {prim['n']}. Expressed: {prim['expressed_n']}.",
            "",
            "| Status | Count | Macro rate (95% CI) |",
            "|---|---:|---|",
            _status_row(prim, "outcome_unknown"),
            _status_row(prim, "admit"),
            _status_row(prim, "hold_unresolved"),
            _status_row(prim, "reject"),
            "",
        ]
        if prim["expressed_n"]:
            lines.append("Among expressed goal-utility claims:")
            lines.append("")
            for status in ("admit", "hold_unresolved", "reject"):
                block = prim["expressed_rates"][status]["macro"]
                lines.append(f"- {status}: `{_fmt_ci(block)}`")
            lines.append("")
        lines += [
            "## Scope",
            "",
            "- KNOWN: 02B residual checkpoint unchanged; grammar frozen before confirmatory.",
            "- MEASURED: claim-status rates at the native twin horizon.",
            "- INFERRED: whether a point T is the wrong object because expressed claims are robust, fragile, or still unknown.",
            "- PROPOSED: real RAN remains a factual-shadow question, not an oracle-do validation.",
            "",
            "Synthetic scenario generator only. Not a real RAN field trial.",
            "",
        ]
    else:
        lines += [
            "## Scope",
            "",
            "- KNOWN: grammar and seeds frozen; 04 3 s table used as a labeled instrument check.",
            "- MEASURED: 3 s claim-status mix under the 05 decision rule.",
            "- INFERRED: not yet. Confirmatory is the 22 s seed `110518`.",
            "",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--stage",
        choices=("freeze", "instrument", "formulate", "confirm", "analyze", "all"),
        default="formulate",
    )
    args = ap.parse_args()
    stages = {
        "freeze": stage_freeze,
        "instrument": stage_instrument,
        "confirm": stage_confirm,
        "analyze": stage_analyze,
    }
    if args.stage == "formulate":
        order = ("freeze", "instrument")
    elif args.stage == "all":
        order = ("freeze", "instrument", "confirm", "analyze")
    else:
        order = (args.stage,)
    for name in order:
        print("STAGE", name, flush=True)
        stages[name]()


if __name__ == "__main__":
    main()
