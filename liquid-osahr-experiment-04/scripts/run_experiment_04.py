#!/usr/bin/env python3
"""Experiment 04 stages: calibrate, freeze, confirm, analyze.

Confirmatory execution is refused until artifacts/FROZEN.json exists.
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

import pandas as pd

from liquid_osahr04.calibrate import fit_from_calibration_table, load_02b_predictive_nmae, loso_cell_alphas
from liquid_osahr04.protocol import (
    ART,
    CAL_CSV,
    CAL_REGIMES,
    CAL_SCENARIOS,
    CALIBRATION_SEED,
    CONF_CSV,
    CONF_REGIMES,
    CONF_SCENARIOS,
    CONFIRMATORY_SEED,
    ESTIMANDS,
    EXP02B,
    EXP03,
    FROZEN_PATH,
    GRID,
    HORIZON,
    LAMBDA,
    calibration_scenario_id,
    calibration_scenario_seed_offset,
    confirmatory_scenario_id,
    confirmatory_scenario_seed_offset,
)

if str(EXP03) not in sys.path:
    sys.path.insert(0, str(EXP03))

from liquid_osahr03.confirmatory import (  # type: ignore
    arm_abs_error,
    compare_fields,
    field_abs_error,
    global_alpha_table,
    load_confirmatory,
    scenario_effects,
    summarize_errors,
)
from liquid_osahr03.trust import QueryContext  # type: ignore


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _fmt_ci(block: dict) -> str:
    return f"{block['mean']:.5f}  [{block['lo']:.5f}, {block['hi']:.5f}]"


def _resolved(block: dict) -> str:
    if block["lo"] > 0:
        return "positive, 95% CI excludes 0"
    if block["hi"] < 0:
        return "negative, 95% CI excludes 0"
    return "unresolved (95% CI includes 0)"


def stage_calibrate() -> None:
    from liquid_osahr04.simulate import run_split

    run_split(
        split="calibration",
        root_seed=CALIBRATION_SEED,
        regimes=CAL_REGIMES,
        n_scenarios=CAL_SCENARIOS,
        scenario_id_fn=calibration_scenario_id,
        seed_offset_fn=calibration_scenario_seed_offset,
        combined_csv=CAL_CSV,
        horizon=HORIZON,
    )


def stage_freeze() -> None:
    if not CAL_CSV.exists():
        raise SystemExit("calibration CSV missing; run --stage calibrate")
    if CONF_CSV.exists():
        raise SystemExit("confirmatory CSV already exists; freeze must precede confirmatory")
    pred_payload = json.loads((EXP02B / "artifacts" / "intervention_calibration_multi.json").read_text(encoding="utf-8"))
    pred = load_02b_predictive_nmae(pred_payload)
    df = pd.read_csv(CAL_CSV)
    fields = {
        "T_strict": fit_from_calibration_table(df, predictive_nmae=pred, protocol="T_strict", lam=LAMBDA),
        "T_primary_share": fit_from_calibration_table(
            df, predictive_nmae=pred, protocol="T_primary_share", lam=LAMBDA, share_primary=True
        ),
        "T_intervention_only": fit_from_calibration_table(
            df, predictive_nmae=pred, protocol="T_intervention_only", lam=0.0
        ),
    }
    ART.mkdir(exist_ok=True)
    for name, field in fields.items():
        (ART / f"trust_field_{name}.json").write_text(json.dumps(field.to_json(), indent=2), encoding="utf-8")
    freeze = {
        "protocol_status": "FROZEN before confirmatory root seed 880419 was executed",
        "calibration_seed": CALIBRATION_SEED,
        "confirmatory_seed_declared": CONFIRMATORY_SEED,
        "horizon": HORIZON,
        "lam": LAMBDA,
        "grid": list(GRID),
        "calibration_csv": str(CAL_CSV),
        "calibration_sha256": _sha256(CAL_CSV),
        "predictive_nmae": {f"{a:.2f}": pred[a] for a in GRID},
        "calibration_loso": loso_cell_alphas(df, predictive_nmae=pred, lam=LAMBDA),
        "cells_T_strict": fields["T_strict"].to_json()["cells"],
    }
    tmp = FROZEN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(freeze, indent=2), encoding="utf-8")
    tmp.replace(FROZEN_PATH)
    print("FROZE", FROZEN_PATH)


def stage_confirm() -> None:
    if not FROZEN_PATH.exists():
        raise SystemExit("refusing confirmatory: artifacts/FROZEN.json missing")
    freeze = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
    if freeze["calibration_sha256"] != _sha256(CAL_CSV):
        raise SystemExit("calibration CSV changed after freeze")
    from liquid_osahr04.simulate import run_split

    run_split(
        split="confirmatory",
        root_seed=CONFIRMATORY_SEED,
        regimes=CONF_REGIMES,
        n_scenarios=CONF_SCENARIOS,
        scenario_id_fn=confirmatory_scenario_id,
        seed_offset_fn=confirmatory_scenario_seed_offset,
        combined_csv=CONF_CSV,
        horizon=HORIZON,
    )


def stage_analyze() -> None:
    if not FROZEN_PATH.exists() or not CONF_CSV.exists():
        raise SystemExit("need freeze and confirmatory CSV")
    freeze = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
    if freeze["calibration_sha256"] != _sha256(CAL_CSV):
        raise SystemExit("calibration CSV changed after freeze")
    from liquid_osahr03.trust import TrustField  # type: ignore

    fields = {
        name: TrustField.from_json(json.loads((ART / f"trust_field_{name}.json").read_text(encoding="utf-8")))
        for name in ("T_strict", "T_primary_share", "T_intervention_only")
    }
    df = load_confirmatory(CONF_CSV)
    confirmatory: dict = {}
    protocol_seed = {"T_strict": 1, "T_primary_share": 2, "T_intervention_only": 3}
    map_rows = []
    for name, field in fields.items():
        for q in ESTIMANDS:
            for r in CONF_REGIMES:
                d = field.select(QueryContext(q, regime=r, horizon=HORIZON))
                map_rows.append(
                    {"protocol": name, "estimand": q, "regime": r, "alpha": d.alpha, "source": d.source, "notes": d.notes}
                )
    pd.DataFrame(map_rows).to_csv(ART / "trust_map.csv", index=False)
    for i, estimand in enumerate(ESTIMANDS):
        effects = scenario_effects(df, estimand)
        block = {"global": global_alpha_table(effects, GRID, seed=70_000 + 1000 * i)}
        for name, field in fields.items():
            err = field_abs_error(effects, field, estimand)
            err.to_csv(ART / f"errors_{name}_{estimand}.csv", index=False)
            pseed = protocol_seed[name]
            block[name] = summarize_errors(err, seed=80_000 + 1000 * i + pseed)
            block[f"paired_{name}_vs_alpha0"] = compare_fields(
                err, arm_abs_error(effects, 0.0), seed=90_000 + 1000 * i + pseed
            )
            block[f"paired_{name}_vs_alpha1"] = compare_fields(
                err, arm_abs_error(effects, 1.0), seed=91_000 + 1000 * i + pseed
            )
        confirmatory[estimand] = block
    confirmatory["goal_utility_ratio"]["paired_vs_alpha0"] = confirmatory["goal_utility_ratio"]["paired_T_strict_vs_alpha0"]
    payload = {
        "freeze": freeze,
        "fields": {k: v.to_json() for k, v in fields.items()},
        "confirmatory": confirmatory,
    }
    (ART / "confirmatory_evaluation.json").write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")
    write_report(ROOT / "EXPERIMENT_REPORT.md", payload=_jsonable(payload))
    manifest = {
        "experiment": "liquid-osahr-experiment-04",
        "calibration_seed": CALIBRATION_SEED,
        "confirmatory_seed": CONFIRMATORY_SEED,
        "horizon": HORIZON,
        "calibration_sha256": freeze["calibration_sha256"],
        "confirmatory_sha256": _sha256(CONF_CSV),
        "frozen": True,
    }
    (ROOT / "RUN_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def write_report(path: Path, *, payload: dict) -> None:
    prim = payload["confirmatory"]["goal_utility_ratio"]
    cells = payload["fields"]["T_strict"]["cells"]
    lines = [
        "# Experiment 04 Report — Same-Horizon Multi-Query Calibration",
        "",
        "**Status:** completed synthetic confirmatory study.",
        "**Calibration seed:** 440318. **Confirmatory seed:** 880419. **Horizon:** 3.0 s.",
        "",
        "## 1. Frozen T_strict cells",
        "",
        "| Estimand | Regime | α | Calibration MAE | Inadequacy |",
        "|---|---|---:|---:|:---|",
    ]
    for cell in cells:
        mae = cell["mae_by_alpha"][f"{cell['alpha']:.2f}"]
        lines.append(
            f"| {cell['estimand']} | {cell['regime']} | {cell['alpha']:.2f} | {mae:.5f} | {cell['inadequacy']} |"
        )
    lines += [
        "",
        "Weak channel is uncalibrated and falls back to α=0.",
        "",
        "## 2. Primary confirmatory endpoint",
        "",
        "Goal-utility semantic-vs-throughput effect MAE versus oracle.",
        "",
        "| Selector | Macro MAE | 95% CI |",
        "|---|---:|---|",
        f"| T_strict | {prim['T_strict']['macro']['mean']:.5f} | [{prim['T_strict']['macro']['lo']:.5f}, {prim['T_strict']['macro']['hi']:.5f}] |",
        f"| global α=0 | {prim['global']['0.00']['macro']['mean']:.5f} | [{prim['global']['0.00']['macro']['lo']:.5f}, {prim['global']['0.00']['macro']['hi']:.5f}] |",
        f"| global α=1 | {prim['global']['1.00']['macro']['mean']:.5f} | [{prim['global']['1.00']['macro']['lo']:.5f}, {prim['global']['1.00']['macro']['hi']:.5f}] |",
        "",
        "Paired T_strict minus global α=0 (negative = T better):",
        "",
        f"- macro: `{_fmt_ci(prim['paired_vs_alpha0']['macro'])}` — {_resolved(prim['paired_vs_alpha0']['macro'])}",
    ]
    for regime, block in prim["paired_vs_alpha0"]["regimes"].items():
        lines.append(f"- {regime}: `{_fmt_ci(block)}` — {_resolved(block)}")
    lines += [
        "",
        "## 3. All estimands",
        "",
        "| Estimand | Protocol | Macro MAE | vs α=0 | Reading |",
        "|---|---|---:|---:|---|",
    ]
    for estimand in ESTIMANDS:
        block = payload["confirmatory"][estimand]
        for proto in ("T_strict", "T_primary_share", "T_intervention_only"):
            paired = block[f"paired_{proto}_vs_alpha0"]["macro"]
            lines.append(
                f"| {estimand} | {proto} | {block[proto]['macro']['mean']:.5f} | {paired['mean']:.5f} [{paired['lo']:.5f}, {paired['hi']:.5f}] | {_resolved(paired)} |"
            )
    lines += [
        "",
        "## 4. Scope",
        "",
        "- KNOWN: 02B residual checkpoint unchanged; confirmatory seed was declared before freeze.",
        "- MEASURED: 3 s multi-query calibration cells; new-seed arm-selection errors.",
        "- INFERRED: whether same-horizon query-conditioning transports.",
        "- PROPOSED: federation with srsRAN/5G-LENA remains the external-validation step.",
        "",
        "Synthetic scenario generator only. Not a real RAN field trial.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("calibrate", "freeze", "confirm", "analyze", "all"), default="all")
    args = ap.parse_args()
    stages = {
        "calibrate": stage_calibrate,
        "freeze": stage_freeze,
        "confirm": stage_confirm,
        "analyze": stage_analyze,
    }
    order = ("calibrate", "freeze", "confirm", "analyze") if args.stage == "all" else (args.stage,)
    for name in order:
        print("STAGE", name, flush=True)
        stages[name]()


if __name__ == "__main__":
    main()
