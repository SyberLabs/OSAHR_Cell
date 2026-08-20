from __future__ import annotations

import pandas as pd
import pytest

from liquid_osahr04.calibrate import errors_by_alpha, fit_from_calibration_table
from liquid_osahr04.protocol import CAL_REGIMES, ESTIMANDS, FROZEN_PATH


def _toy_calibration() -> pd.DataFrame:
    rows = []
    # Distinct best alphas: ID goal-utility prefers 0.5; high_stress prefers 0.25;
    # latency prefers 1.0 on ID. Oracle effects are 0.2 everywhere.
    best = {
        ("goal_utility_ratio", "id"): {0.0: 0.20, 0.25: 0.12, 0.5: 0.02, 1.0: 0.15},
        ("goal_utility_ratio", "high_mobility"): {0.0: 0.01, 0.25: 0.08, 0.5: 0.09, 1.0: 0.10},
        ("goal_utility_ratio", "high_stress"): {0.0: 0.18, 0.25: 0.03, 0.5: 0.11, 1.0: 0.20},
        ("critical_success_rate", "id"): {0.0: 0.04, 0.25: 0.05, 0.5: 0.06, 1.0: 0.07},
        ("critical_success_rate", "high_mobility"): {0.0: 0.04, 0.25: 0.05, 0.5: 0.06, 1.0: 0.07},
        ("critical_success_rate", "high_stress"): {0.0: 0.04, 0.25: 0.05, 0.5: 0.06, 1.0: 0.07},
        ("mean_latency", "id"): {0.0: 0.20, 0.25: 0.15, 0.5: 0.12, 1.0: 0.01},
        ("mean_latency", "high_mobility"): {0.0: 0.02, 0.25: 0.08, 0.5: 0.09, 1.0: 0.10},
        ("mean_latency", "high_stress"): {0.0: 0.02, 0.25: 0.08, 0.5: 0.09, 1.0: 0.10},
    }
    models = {
        0.0: "mechanistic_calibrated",
        0.25: "residual_quarter",
        0.5: "residual_idcal",
        1.0: "residual_predictive",
    }
    for regime in CAL_REGIMES:
        for scenario in (0, 1):
            for alpha, model in models.items():
                for pol, base in (("throughput", 0.10), ("semantic", 0.30)):
                    row = {
                        "regime": regime,
                        "scenario": scenario,
                        "replicate": 0,
                        "model": model,
                        "trust": alpha,
                        "policy": pol,
                    }
                    for estimand in ESTIMANDS:
                        err = best[(estimand, regime)][alpha]
                        # semantic - throughput should be 0.20 - err for residual arms
                        if pol == "throughput":
                            row[estimand] = 0.10
                        else:
                            row[estimand] = 0.10 + (0.20 - err)
                    rows.append(row)
            for pol, val in (("throughput", 0.10), ("semantic", 0.30)):
                row = {
                    "regime": regime,
                    "scenario": scenario,
                    "replicate": 0,
                    "model": "oracle",
                    "trust": 1.0,
                    "policy": pol,
                    "goal_utility_ratio": val,
                    "critical_success_rate": val,
                    "mean_latency": val,
                }
                rows.append(row)
    return pd.DataFrame(rows)


def test_multi_query_fit_is_non_scalar():
    df = _toy_calibration()
    pred = {0.0: 0.05, 0.25: 0.04, 0.5: 0.03, 1.0: 0.02}
    field = fit_from_calibration_table(df, predictive_nmae=pred, protocol="T_strict", lam=0.0)
    from liquid_osahr03.trust import QueryContext

    assert field.select(QueryContext("goal_utility_ratio", regime="id")).alpha == 0.5
    assert field.select(QueryContext("goal_utility_ratio", regime="high_stress")).alpha == 0.25
    assert field.select(QueryContext("mean_latency", regime="id")).alpha == 1.0
    assert field.select(QueryContext("goal_utility_ratio", regime="weak_channel")).alpha == 0.0
    assert field.select(QueryContext("goal_utility_ratio", regime="high_mobility")).alpha == 0.0


def test_errors_by_alpha_uses_scenario_level_mae():
    df = _toy_calibration()
    from liquid_osahr03.confirmatory import scenario_effects

    effects = scenario_effects(df, "goal_utility_ratio")
    err = errors_by_alpha(effects, "id")
    assert set(err) == {0.0, 0.25, 0.5, 1.0}
    assert all(abs(v - 0.02) < 1e-12 for v in err[0.5])


def test_confirm_requires_freeze_constant():
    assert FROZEN_PATH.name == "FROZEN.json"
