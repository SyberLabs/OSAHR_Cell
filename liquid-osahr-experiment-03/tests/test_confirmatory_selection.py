from __future__ import annotations

import pandas as pd
import pytest

from liquid_osahr03.confirmatory import ARM_BY_ALPHA, field_abs_error, scenario_effects
from liquid_osahr03.trust import TrustField, fit_cell


def _toy_confirmatory() -> pd.DataFrame:
    rows = []
    for regime, scenario in (("id", 0), ("id", 1), ("high_stress", 0)):
        for model, trust, effect_t, effect_s in (
            ("oracle", 1.0, 0.10, 0.20),
            ("mechanistic_calibrated", 0.0, 0.10, 0.40),
            ("residual_quarter", 0.25, 0.10, 0.22),
            ("residual_idcal", 0.5, 0.10, 0.19),
            ("residual_predictive", 1.0, 0.10, 0.50),
        ):
            for pol, val in (("throughput", effect_t), ("semantic", effect_s)):
                rows.append({
                    "regime": regime,
                    "scenario": scenario,
                    "replicate": 0,
                    "model": model,
                    "trust": trust,
                    "policy": pol,
                    "goal_utility_ratio": val,
                    "critical_success_rate": val,
                    "mean_latency": val,
                })
    return pd.DataFrame(rows)


def test_arm_selection_uses_declared_alpha_not_oracle():
    field = TrustField(protocol="toy")
    field.add(
        fit_cell(
            estimand="goal_utility_ratio",
            intervention="semantic_vs_throughput",
            regime="id",
            errors_by_alpha={0.0: [1.0], 0.5: [0.0]},
            lam=0.0,
        )
    )
    effects = scenario_effects(_toy_confirmatory(), "goal_utility_ratio")
    err = field_abs_error(effects, field, "goal_utility_ratio")
    id_rows = err[err.regime == "id"]
    assert set(id_rows.alpha) == {0.5}
    assert set(id_rows.model) == {ARM_BY_ALPHA[0.5]}
    stress = err[err.regime == "high_stress"].iloc[0]
    assert stress.alpha == 0.0
    assert stress.source == "default_mechanistic"


def test_selected_alpha_must_exist_as_executed_arm():
    field = TrustField(protocol="bad", grid=(0.0, 0.75))
    field.add(
        fit_cell(
            estimand="goal_utility_ratio",
            intervention="semantic_vs_throughput",
            regime="id",
            errors_by_alpha={0.75: [0.0]},
            lam=0.0,
            grid=(0.75,),
        )
    )
    effects = scenario_effects(_toy_confirmatory(), "goal_utility_ratio")
    with pytest.raises(ValueError, match="no confirmatory arm"):
        field_abs_error(effects, field, "goal_utility_ratio")
