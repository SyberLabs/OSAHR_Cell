#!/usr/bin/env python3
"""Fit frozen T from 02B calibration and score the 02B confirmatory holdout.

Fitting reads only intervention_calibration_multi.json.
Scoring reads confirmatory_release.csv by arm selection. No new OSAHR runs.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from liquid_osahr03.calibration import fit_from_02b_multi, load_02b_multi, loso_cell_alphas
from liquid_osahr03.confirmatory import (
    ESTIMANDS,
    REGIMES,
    arm_abs_error,
    compare_fields,
    field_abs_error,
    global_alpha_table,
    load_confirmatory,
    loso_selector_errors,
    oracle_cell_errors,
    scenario_effects,
    summarize_errors,
)
from liquid_osahr03.trust import DEFAULT_GRID, DEFAULT_INTERVENTION, QueryContext

EXP02B = ROOT.parent / "liquid-osahr-experiment-02b" / "liquid-osahr-exp02b-stage-final"
CAL_PATH = EXP02B / "artifacts" / "intervention_calibration_multi.json"
CONF_PATH = EXP02B / "artifacts" / "confirmatory_release.csv"
ART = ROOT / "artifacts"


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _fmt_ci(block: dict) -> str:
    return f"{block['mean']:.5f}  [{block['lo']:.5f}, {block['hi']:.5f}]"


def _resolved(block: dict) -> str:
    if block["lo"] > 0:
        return "positive, 95% CI excludes 0"
    if block["hi"] < 0:
        return "negative, 95% CI excludes 0"
    return "unresolved (95% CI includes 0)"


def trust_map_rows(fields: dict) -> pd.DataFrame:
    rows = []
    for name, field in fields.items():
        table = field.map_table(ESTIMANDS, REGIMES, DEFAULT_INTERVENTION)
        for q, by_r in table.items():
            for r, decision in by_r.items():
                rows.append({
                    "protocol": name,
                    "estimand": q,
                    "regime": r,
                    "alpha": decision.alpha,
                    "source": decision.source,
                    "notes": decision.notes,
                })
    return pd.DataFrame(rows)


def write_report(path: Path, *, payload: dict) -> None:
    t_strict = payload["fields"]["T_strict"]
    prim = payload["confirmatory"]["goal_utility_ratio"]
    lines = [
        "# Experiment 03 Report: Query-Conditioned Trust",
        "",
        "**Status:** completed reanalysis of frozen Liquid-OSAHR 02B artifacts.",
        "**Simulation:** none. Confirmatory scores are arm selections from already-committed trajectories.",
        "",
        "## 1. Frozen field",
        "",
        "Primary protocol `T_strict` applies the 02B objective per calibrated cell",
        "on `goal_utility_ratio` only. Uncalibrated queries and regimes fall back to α=0.",
        "",
        "| Regime | Selected α | Source | Intervention MAE (calibration) | Inadequacy |",
        "|---|---:|---|---:|:---|",
    ]
    for cell in t_strict["cells"]:
        mae = cell["mae_by_alpha"][f"{cell['alpha']:.2f}"]
        lines.append(
            f"| {cell['regime']} | {cell['alpha']:.2f} | calibrated_cell | {mae:.5f} | {cell['inadequacy']} |"
        )
    lines += [
        "| weak_channel | 0.00 | default_mechanistic | - | fallback |",
        "",
        "Calibration LOSO selected alphas (6 folds per calibrated regime):",
        "",
        "```json",
        json.dumps(payload["calibration_loso"], indent=2),
        "```",
        "",
        "## 2. Confirmatory primary endpoint",
        "",
        "Absolute semantic-vs-throughput **goal-utility** effect error versus oracle.",
        "Independent unit: physical scenario. 50,000 scenario bootstraps.",
        "",
        "| Selector | Macro MAE | 95% CI |",
        "|---|---:|---|",
        f"| T_strict | {prim['T_strict']['macro']['mean']:.5f} | [{prim['T_strict']['macro']['lo']:.5f}, {prim['T_strict']['macro']['hi']:.5f}] |",
        f"| global α=0 | {prim['global']['0.00']['macro']['mean']:.5f} | [{prim['global']['0.00']['macro']['lo']:.5f}, {prim['global']['0.00']['macro']['hi']:.5f}] |",
        f"| global α=1 | {prim['global']['1.00']['macro']['mean']:.5f} | [{prim['global']['1.00']['macro']['lo']:.5f}, {prim['global']['1.00']['macro']['hi']:.5f}] |",
        "",
        "Paired difference in absolute error, T_strict minus global α=0 (negative = T better):",
        "",
        f"- macro: `{_fmt_ci(prim['paired_vs_alpha0']['macro'])}`: {_resolved(prim['paired_vs_alpha0']['macro'])}",
    ]
    for regime, block in prim["paired_vs_alpha0"]["regimes"].items():
        lines.append(f"- {regime}: `{_fmt_ci(block)}`: {_resolved(block)}")
    lines += [
        "",
        "Per-regime MAE under T_strict:",
        "",
        "| Regime | Selected α (mean) | MAE | 95% CI |",
        "|---|---:|---:|---|",
    ]
    for regime, block in prim["T_strict"]["regimes"].items():
        lines.append(
            f"| {regime} | {block['mean_selected_alpha']:.2f} | {block['mae']['mean']:.5f} | [{block['mae']['lo']:.5f}, {block['mae']['hi']:.5f}] |"
        )
    lines += [
        "",
        "## 3. Secondary estimands under frozen protocols",
        "",
        "`T_strict` cannot condition on critical success or latency because those",
        "queries are absent from the 02B calibration JSON. `T_primary_share` reuses",
        "the goal-utility cell when the regime was calibrated.",
        "",
        "| Estimand | Protocol | Macro MAE | vs α=0 (paired) | Reading |",
        "|---|---|---:|---:|---|",
    ]
    for estimand in ESTIMANDS:
        block = payload["confirmatory"][estimand]
        for proto in ("T_strict", "T_primary_share"):
            paired = block[f"paired_{proto}_vs_alpha0"]["macro"]
            lines.append(
                f"| {estimand} | {proto} | {block[proto]['macro']['mean']:.5f} | {paired['mean']:.5f} [{paired['lo']:.5f}, {paired['hi']:.5f}] | {_resolved(paired)} |"
            )
    lines += [
        "",
        "## 4. Exploratory value of information (not confirmatory)",
        "",
        "Leave-one-scenario-out selectors fitted **on the confirmatory holdout**",
        "estimate how much query-conditioning could help if calibration had the",
        "same horizon and estimand support. The oracle-per-scenario selector is an",
        "infeasible ceiling.",
        "",
        "| Estimand | Frozen T_strict | Exploratory LOSO | Infeasible oracle-cell |",
        "|---|---:|---:|---:|",
    ]
    for estimand in ESTIMANDS:
        exp = payload["exploratory"][estimand]
        frozen = payload["confirmatory"][estimand]["T_strict"]["macro"]["mean"]
        lines.append(
            f"| {estimand} | {frozen:.5f} | {exp['loso']['macro']['mean']:.5f} | {exp['oracle_cell']['macro']['mean']:.5f} |"
        )
    lines += [
        "",
        "## 5. Interpretation",
        "",
        payload["interpretation"],
        "",
        "## 6. Exactness and scope",
        "",
        "- KNOWN: 02B trajectories, hashes, and calibration JSON are unchanged.",
        "- MEASURED: cell-wise α from the frozen calibration objective; confirmatory arm-selection errors.",
        "- INFERRED: whether query-conditioning improves holdout policy-effect recovery under this protocol.",
        "- ASSUMED: confirmatory `trust` column is the residual coefficient actually used in 02B.",
        "- PROPOSED: a later same-horizon multi-query calibration, and only then a new untouched seed.",
        "",
        "This is a synthetic scenario-generator result. It is not a real RAN field trial.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def interpret(payload: dict) -> str:
    prim = payload["confirmatory"]["goal_utility_ratio"]
    paired = prim["paired_vs_alpha0"]["macro"]
    cells = {c["regime"]: c["alpha"] for c in payload["fields"]["T_strict"]["cells"]}
    bits = [
        f"Calibrated cells: " + ", ".join(f"{r}→α={a:.2f}" for r, a in cells.items()) + ".",
        "Uncalibrated support (other queries, weak_channel) is α=0 by protocol.",
    ]
    if paired["hi"] < 0:
        bits.append(
            "On the primary confirmatory endpoint, T_strict reduced absolute "
            "goal-utility effect error versus global α=0, and the paired 95% CI excludes zero."
        )
    elif paired["lo"] > 0:
        bits.append(
            "On the primary confirmatory endpoint, T_strict increased error versus "
            "global α=0; the paired 95% CI excludes zero. Query-conditioning as fitted "
            "from the 2 s calibration did not transport."
        )
    else:
        bits.append(
            "On the primary confirmatory endpoint, the paired difference versus global "
            f"α=0 is {_fmt_ci(paired)} and is unresolved."
        )
    id_pair = prim["paired_vs_alpha0"]["regimes"].get("id")
    if id_pair and id_pair["hi"] < 0:
        bits.append(
            "The identifiable ID cell (α=0.5 via predictive tie-break on tied "
            "intervention MAE) is the only calibrated departure from α=0, and it "
            "improved ID confirmatory recovery."
        )
    stress = prim["T_strict"]["regimes"].get("high_stress", {})
    bits.append(
        "High-stress remains on the mechanistic fallback because calibration "
        f"penalized residual trust there. Frozen T therefore cannot capture any "
        f"later high-stress residual benefit; that is a transport/design limit, "
        f"not a silent interpolation. Confirmatory high-stress MAE under T_strict "
        f"is {stress.get('mae', {}).get('mean', float('nan')):.5f}."
    )
    bits.append(
        "Exploratory LOSO on the confirmatory holdout is reported separately. "
        "It is not a frozen-protocol confirmation."
    )
    return " ".join(bits)


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    cal = load_02b_multi(CAL_PATH)

    fields = {
        "T_strict": fit_from_02b_multi(cal, protocol="T_strict", share_primary=False),
        "T_primary_share": fit_from_02b_multi(cal, protocol="T_primary_share", share_primary=True),
        "T_intervention_only": fit_from_02b_multi(
            cal, protocol="T_intervention_only", lam=0.0, share_primary=False
        ),
    }
    for name, field in fields.items():
        (ART / f"trust_field_{name}.json").write_text(
            json.dumps(field.to_json(), indent=2), encoding="utf-8"
        )

    df = load_confirmatory(CONF_PATH)
    map_df = trust_map_rows(fields)
    map_df.to_csv(ART / "trust_map.csv", index=False)

    protocol_seed = {"T_strict": 1, "T_primary_share": 2, "T_intervention_only": 3}
    confirmatory: dict = {}
    exploratory: dict = {}
    for i, estimand in enumerate(ESTIMANDS):
        effects = scenario_effects(df, estimand)
        glob = global_alpha_table(effects, DEFAULT_GRID, seed=70_000 + 1000 * i)
        block = {"global": glob}
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
        loso = loso_selector_errors(effects, lam=0.0, grid=DEFAULT_GRID)
        oracle = oracle_cell_errors(effects, grid=DEFAULT_GRID)
        loso.to_csv(ART / f"exploratory_loso_{estimand}.csv", index=False)
        exploratory[estimand] = {
            "label": "exploratory_confirmatory_loso",
            "loso": summarize_errors(loso, seed=92_000 + i),
            "oracle_cell": summarize_errors(oracle, seed=93_000 + i),
            "paired_loso_vs_alpha0": compare_fields(loso, arm_abs_error(effects, 0.0), seed=94_000 + i),
        }

    confirmatory["goal_utility_ratio"]["paired_vs_alpha0"] = confirmatory["goal_utility_ratio"][
        "paired_T_strict_vs_alpha0"
    ]
    confirmatory["goal_utility_ratio"]["paired_vs_alpha1"] = confirmatory["goal_utility_ratio"][
        "paired_T_strict_vs_alpha1"
    ]

    payload = {
        "fields": {k: v.to_json() for k, v in fields.items()},
        "calibration_loso": loso_cell_alphas(cal),
        "confirmatory": confirmatory,
        "exploratory": exploratory,
    }
    payload["interpretation"] = interpret(payload)
    (ART / "confirmatory_evaluation.json").write_text(
        json.dumps(_jsonable(payload), indent=2), encoding="utf-8"
    )

    manifest = {
        "experiment": "liquid-osahr-experiment-03",
        "version": "0.1.0",
        "date": "2026-08-18",
        "simulation": "none",
        "calibration_artifact": str(CAL_PATH),
        "calibration_sha256": _sha256(CAL_PATH),
        "confirmatory_artifact": str(CONF_PATH),
        "confirmatory_sha256": _sha256(CONF_PATH),
        "bootstrap_resamples": 50_000,
        "independent_unit": "physical scenario",
        "protocols": list(fields),
    }
    (ROOT / "RUN_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_report(ROOT / "EXPERIMENT_REPORT.md", payload=_jsonable(payload))
    print(json.dumps(_jsonable(manifest), indent=2))
    print("\n" + payload["interpretation"].replace("α", "alpha").replace("→", "->"))


if __name__ == "__main__":
    main()
