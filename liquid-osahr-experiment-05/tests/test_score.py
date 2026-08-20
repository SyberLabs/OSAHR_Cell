from __future__ import annotations

import pandas as pd

from liquid_osahr05.score import annotate_foils, score_table, summarize_claims

MODELS = {
    "oracle": 1.0,
    "mechanistic_calibrated": 0.0,
    "residual_quarter": 0.25,
    "residual_idcal": 0.5,
    "residual_predictive": 1.0,
}


def _row(regime, scenario, model, trust, policy, goal, events=0):
    return {
        "regime": regime,
        "scenario": scenario,
        "replicate": 0,
        "model": model,
        "trust": trust,
        "policy": policy,
        "goal_utility_ratio": goal,
        "critical_success_rate": goal,
        "mean_latency": goal,
        "events": events,
        "outages": 0,
        "handovers": 0,
        "reroutes": 0,
    }


def _arm_pair(regime, scenario, model, trust, throughput, semantic, events_delta=0):
    return [
        _row(regime, scenario, model, trust, "throughput", throughput, events=0),
        _row(regime, scenario, model, trust, "semantic", semantic, events=events_delta),
    ]


def test_score_table_covers_all_statuses():
    rows = []
    # unknown: oracle Δ=0
    for model, trust in MODELS.items():
        rows += _arm_pair("id", 1, model, trust, 0.2, 0.2)
    # admit: all positive
    for model, trust in MODELS.items():
        rows += _arm_pair("id", 2, model, trust, 0.2, 0.4, events_delta=2)
    # hold: α=0.5 negative
    for model, trust in MODELS.items():
        semantic = 0.1 if model == "residual_idcal" else 0.4
        rows += _arm_pair("high_stress", 3, model, trust, 0.2, semantic, events_delta=1)
    # reject: all residual negative, oracle positive
    for model, trust in MODELS.items():
        semantic = 0.4 if model == "oracle" else 0.1
        rows += _arm_pair("high_mobility", 4, model, trust, 0.2, semantic, events_delta=1)
    df = pd.DataFrame(rows)
    claims = score_table(df, estimand="goal_utility_ratio", horizon=3.0, eps=0.0)
    by_scen = {c.scenario: c.status for c in claims}
    assert by_scen[1] == "outcome_unknown"
    assert by_scen[2] == "admit"
    assert by_scen[3] == "hold_unresolved"
    assert by_scen[4] == "reject"
    frame = annotate_foils(claims)
    hold = frame[frame.scenario == 3].iloc[0]
    assert bool(hold["T04_strict_illegal_promotion"]) is True  # T04 high_stress α=0.25 matches oracle
    summary = summarize_claims(frame, seed=11)
    assert summary["n"] == 4
    assert summary["status_counts"]["admit"] == 1
    assert summary["status_counts"]["hold_unresolved"] == 1
    assert summary["status_counts"]["reject"] == 1
    assert summary["status_counts"]["outcome_unknown"] == 1
