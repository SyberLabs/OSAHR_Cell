#!/usr/bin/env python3
"""Experiment 06 stages: freeze, instrument, confirm, analyze.

Confirmatory execution is refused until artifacts/FROZEN.json matches vault
files, junction grammar, and AnLF versions. No LLM is imported.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from osahr.boundary import ExternalEvent

from osahr_cell.anlf import LoadLevel, load_handle
from osahr_cell.claims_bridge import (
    ActivationCounts,
    illegal_promotion,
    point_direction,
    score_semantic_contrast,
)
from osahr_cell.freeze import require_freeze, write_freeze
from osahr_cell.protocol import (
    ART,
    CONF_JSON,
    CONFIRMATORY_SEED,
    EPS_SENSITIVITY,
    EPS_ZERO,
    HORIZON,
    HYPOTHESES,
    INSTRUMENT_JSON,
    INSTRUMENT_SEED,
    PRIMARY_ESTIMAND,
    REPLICATES,
    SCENARIOS,
)
from osahr_cell.twin import build_stub_runtime, default_config, run_arm
from osahr_cell.vault import SemanticVault


def _mean(values: list[float]) -> float:
    return float(statistics.fmean(values)) if values else 0.0


def _group(rows: list[dict]) -> dict[tuple, list[dict]]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["regime"], row["scenario"], row["policy"], row.get("residual_alpha", 0.0))
        grouped[key].append(row)
    return grouped


def _metric_mean(rows: list[dict], estimand: str) -> float:
    return _mean([float(row[estimand]) for row in rows])


def stage_freeze() -> None:
    if CONF_JSON.exists():
        raise SystemExit("confirmatory JSON already exists; freeze must precede confirmatory")
    payload = write_freeze()
    print(json.dumps({"freeze": payload["protocol_status"], "seed": payload["confirmatory_seed_declared"]}))


def stage_instrument() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    vault = SemanticVault.load()
    runtime = build_stub_runtime(vault, root_seed=INSTRUMENT_SEED)
    payload = LoadLevel(capacity=4).infer([0.0, 1.0, 2.0])
    load_handle("fast-edge-load").validate_payload(payload)
    runtime.inject(ExternalEvent(0.25, "anlf-load", 1, "inst-load", "fast-edge-load", payload))
    runtime.run_until_time(1.0)
    claim = score_semantic_contrast(
        oracle_effect=0.0,
        effects_by_alpha={a: 0.0 for a in HYPOTHESES},
        activation=ActivationCounts(0, 0, 0, 0),
        scenario=0,
        regime="instrument",
        horizon=1.0,
    )
    record = {
        "seed": INSTRUMENT_SEED,
        "horizon": 1.0,
        "label": "instrument_1s_stub",
        "final_time": runtime.time,
        "state_hash": runtime.state_hash,
        "anlf_load_payload": payload,
        "claim_status": claim.status,
        "note": "Instrument check only. Confirmatory seed 260826 was not used.",
    }
    INSTRUMENT_JSON.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"instrument": "ok", "claim_status": claim.status}))


def _run_grid(root_seed: int) -> list[dict]:
    vault = SemanticVault.load()
    rows: list[dict] = []
    for spec in SCENARIOS:
        cfg = default_config(**spec["overrides"])
        regime = spec["regime"]
        scenario = spec["scenario"]
        for replicate in range(REPLICATES):
            jobs = [
                ("throughput", 0.0, None),
                ("scalar_semantic", 0.0, None),
                ("vault_gated", 0.0, None),
                ("oracle_vault_greedy", 0.0, None),
            ]
            for alpha in HYPOTHESES:
                if alpha == 0.0:
                    continue
                jobs.append(("scalar_semantic", float(alpha), None))
            for policy, alpha, _status in jobs:
                label = "residual_semantic" if alpha else policy
                row = run_arm(
                    policy,
                    replicate,
                    root_seed,
                    cfg,
                    vault if policy in ("vault_gated", "oracle_vault_greedy") else None,
                    residual_alpha=alpha,
                    scenario=scenario,
                )
                row["regime"] = regime
                row["scenario"] = scenario
                row["arm_label"] = label
                rows.append(row)
        # Score claims from this scenario's replicates, then run Brain-at-hold.
        scenario_rows = [row for row in rows if row["scenario"] == scenario]
        claims = _score_scenario(scenario_rows, cfg.horizon)
        status = claims[EPS_ZERO]["status"]
        for replicate in range(REPLICATES):
            row = run_arm(
                "brain_at_hold",
                replicate,
                root_seed,
                cfg,
                vault,
                claim_status=status,
                scenario=scenario,
            )
            row["regime"] = regime
            row["scenario"] = scenario
            row["arm_label"] = "brain_at_hold"
            row["claim_status_used"] = status
            rows.append(row)
            vault.record_claim_note(
                scenario=scenario,
                status=status,
                reason=f"scenario {scenario} {regime}: Brain used {status}",
                extra={"horizon": cfg.horizon},
            )
    return rows


def _score_scenario(rows: list[dict], horizon: float) -> dict[float, dict]:
    grouped = _group(rows)
    # residual alpha 0 is scalar_semantic
    by_eps = {}
    for eps in (EPS_ZERO, EPS_SENSITIVITY):
        # one representative scenario id in this slice
        sample = rows[0]
        regime = sample["regime"]
        scenario = sample["scenario"]
        thru = _metric_mean(
            grouped[(regime, scenario, "throughput", 0.0)], PRIMARY_ESTIMAND
        )
        oracle = _metric_mean(
            grouped[(regime, scenario, "oracle_vault_greedy", 0.0)], PRIMARY_ESTIMAND
        )
        effects = {0.0: _metric_mean(grouped[(regime, scenario, "scalar_semantic", 0.0)], PRIMARY_ESTIMAND) - thru}
        for alpha in HYPOTHESES:
            if alpha == 0.0:
                continue
            effects[alpha] = (
                _metric_mean(grouped[(regime, scenario, "scalar_semantic", alpha)], PRIMARY_ESTIMAND)
                - thru
            )
        activation = ActivationCounts(
            events=_mean([float(r["events"]) for r in rows if r["policy"] == "scalar_semantic"]),
            outages=1.0,
            handovers=_mean([float(r["handovers"]) for r in rows if r["policy"] == "scalar_semantic"]),
            reroutes=_mean([float(r["reroutes"]) for r in rows if r["policy"] == "scalar_semantic"]),
        )
        claim = score_semantic_contrast(
            oracle_effect=oracle - thru,
            effects_by_alpha=effects,
            activation=activation,
            scenario=scenario,
            regime=regime,
            horizon=horizon,
            eps=eps,
        )
        by_eps[eps] = claim.to_json()
    return by_eps


def stage_confirm() -> None:
    freeze = require_freeze()
    ART.mkdir(parents=True, exist_ok=True)
    rows = _run_grid(CONFIRMATORY_SEED)
    CONF_JSON.write_text(
        json.dumps(
            {
                "seed": CONFIRMATORY_SEED,
                "horizon": HORIZON,
                "freeze": freeze["grammar_sha256"],
                "rows": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"confirmatory": "ok", "n_rows": len(rows), "seed": CONFIRMATORY_SEED}))


def _arm_delta(grouped, regime, scenario, policy, alpha=0.0) -> float:
    thru = _metric_mean(grouped[(regime, scenario, "throughput", 0.0)], PRIMARY_ESTIMAND)
    value = _metric_mean(grouped[(regime, scenario, policy, alpha)], PRIMARY_ESTIMAND)
    return value - thru


def stage_analyze() -> dict:
    if not CONF_JSON.exists():
        raise SystemExit("confirmatory JSON missing")
    payload = json.loads(CONF_JSON.read_text(encoding="utf-8"))
    rows = payload["rows"]
    grouped = _group(rows)
    summaries = []
    promotions = []
    for spec in SCENARIOS:
        regime = spec["regime"]
        scenario = spec["scenario"]
        slice_rows = [row for row in rows if row["scenario"] == scenario]
        claims = _score_scenario(slice_rows, HORIZON)
        status = claims[EPS_ZERO]["status"]
        oracle_delta = _arm_delta(grouped, regime, scenario, "oracle_vault_greedy")
        arm_deltas = {
            "scalar_semantic": _arm_delta(grouped, regime, scenario, "scalar_semantic"),
            "vault_gated": _arm_delta(grouped, regime, scenario, "vault_gated"),
            "brain_at_hold": _arm_delta(grouped, regime, scenario, "brain_at_hold"),
        }
        maes = {name: abs(delta - oracle_delta) for name, delta in arm_deltas.items()}
        for name, delta in arm_deltas.items():
            direction = point_direction(oracle_delta, delta, EPS_ZERO)
            promotions.append(
                {
                    "regime": regime,
                    "scenario": scenario,
                    "arm": name,
                    "illegal_promotion": illegal_promotion(status, direction),
                    "direction": direction,
                    "status": status,
                }
            )
        summaries.append(
            {
                "regime": regime,
                "scenario": scenario,
                "status": status,
                "oracle_delta": oracle_delta,
                "arm_deltas": arm_deltas,
                "mae": maes,
                "claim": claims[EPS_ZERO],
            }
        )
    mean_mae = {
        arm: _mean([item["mae"][arm] for item in summaries])
        for arm in ("scalar_semantic", "vault_gated", "brain_at_hold")
    }
    promotion_rate = {
        arm: _mean(
            [
                1.0 if item["illegal_promotion"] else 0.0
                for item in promotions
                if item["arm"] == arm
            ]
        )
        for arm in ("scalar_semantic", "vault_gated", "brain_at_hold")
    }
    result = {
        "seed": payload["seed"],
        "horizon": HORIZON,
        "primary_estimand": PRIMARY_ESTIMAND,
        "mean_mae_vs_oracle": mean_mae,
        "illegal_promotion_rate": promotion_rate,
        "scenarios": summaries,
        "promotions": promotions,
        "llm_in_confirmatory": False,
    }
    (ART / "analysis.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"mae": mean_mae, "illegal_promotion_rate": promotion_rate}))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("freeze", "instrument", "confirm", "analyze", "all"))
    args = parser.parse_args()
    if args.stage in ("freeze", "all"):
        stage_freeze()
    if args.stage in ("instrument", "all"):
        stage_instrument()
    if args.stage in ("confirm", "all"):
        stage_confirm()
    if args.stage in ("analyze", "all"):
        stage_analyze()


if __name__ == "__main__":
    main()
