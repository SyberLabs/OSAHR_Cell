"""Fit T(q,I,r) from an Experiment 04 calibration rollout table."""
from __future__ import annotations

import sys
from typing import Any, Mapping

import pandas as pd

from .protocol import CAL_REGIMES, ESTIMANDS, EXP03, GRID, HORIZON, LAMBDA

if str(EXP03) not in sys.path:
    sys.path.insert(0, str(EXP03))

from liquid_osahr03.confirmatory import ARM_BY_ALPHA, scenario_effects  # type: ignore
from liquid_osahr03.trust import (  # type: ignore
    DEFAULT_INTERVENTION,
    PRIMARY_ESTIMAND,
    TrustField,
    cell_objective,
    fit_cell,
    select_alpha,
)


def errors_by_alpha(effects: pd.DataFrame, regime: str, grid=GRID) -> dict[float, list[float]]:
    part = effects[effects.regime == regime]
    oracle = part[part.model == "oracle"].set_index("scenario")["effect"].sort_index()
    if oracle.empty:
        raise ValueError(f"no oracle effects for regime {regime}")
    out: dict[float, list[float]] = {}
    for alpha in grid:
        model = ARM_BY_ALPHA[alpha]
        hat = part[part.model == model].set_index("scenario")["effect"].reindex(oracle.index)
        if hat.isna().any():
            raise ValueError(f"missing arm {model} in regime {regime}")
        out[float(alpha)] = (hat - oracle).abs().astype(float).tolist()
    return out


def fit_from_calibration_table(
    df: pd.DataFrame,
    *,
    predictive_nmae: Mapping[float, float],
    protocol: str,
    lam: float = LAMBDA,
    grid: tuple[float, ...] = GRID,
    share_primary: bool = False,
    horizon: float = HORIZON,
    regimes: tuple[str, ...] = CAL_REGIMES,
) -> TrustField:
    field = TrustField(
        protocol=protocol,
        grid=grid,
        lam=lam,
        share_primary=share_primary,
        calibration_horizon=horizon,
        notes={
            "calibration_regimes": list(regimes),
            "predictive_weight_source": "02b_validation_nmae_frozen",
        },
    )
    for estimand in ESTIMANDS:
        effects = scenario_effects(df, estimand)
        for regime in regimes:
            field.add(
                fit_cell(
                    estimand=estimand,
                    intervention=DEFAULT_INTERVENTION,
                    regime=regime,
                    errors_by_alpha=errors_by_alpha(effects, regime, grid),
                    predictive_nmae=dict(predictive_nmae),
                    lam=lam,
                    grid=grid,
                    calibration_horizon=horizon,
                )
            )
    return field


def loso_cell_alphas(
    df: pd.DataFrame,
    *,
    predictive_nmae: Mapping[float, float] | None,
    lam: float,
    grid: tuple[float, ...] = GRID,
    regimes: tuple[str, ...] = CAL_REGIMES,
) -> dict[str, dict[str, list[float]]]:
    out: dict[str, dict[str, list[float]]] = {}
    for estimand in ESTIMANDS:
        effects = scenario_effects(df, estimand)
        out[estimand] = {}
        for regime in regimes:
            errors = errors_by_alpha(effects, regime, grid)
            n = len(next(iter(errors.values())))
            picks: list[float] = []
            for i in range(n):
                mae = {a: (sum(v) - v[i]) / (n - 1) for a, v in errors.items()}
                picks.append(
                    select_alpha(
                        cell_objective(
                            mae,
                            predictive_nmae=None if predictive_nmae is None else dict(predictive_nmae),
                            lam=lam,
                            grid=grid,
                        )
                    )
                )
            out[estimand][regime] = picks
    return out


def load_02b_predictive_nmae(payload: Mapping[str, Any], grid: tuple[float, ...] = GRID) -> dict[float, float]:
    return {
        float(row["trust"]): float(row["predictive_nmae"])
        for row in payload["grid"]
        if float(row["trust"]) in grid
    }
