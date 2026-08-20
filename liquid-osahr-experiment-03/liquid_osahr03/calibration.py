"""Fit frozen trust fields from 02B calibration artifacts only."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .trust import (
    DEFAULT_GRID,
    DEFAULT_INTERVENTION,
    DEFAULT_LAMBDA,
    PRIMARY_ESTIMAND,
    TrustField,
    fit_cell,
)

CALIBRATION_ESTIMAND = PRIMARY_ESTIMAND


def predictive_nmae_from_multi(payload: Mapping[str, Any]) -> dict[float, float]:
    return {float(row["trust"]): float(row["predictive_nmae"]) for row in payload["grid"]}


def errors_from_multi(payload: Mapping[str, Any], regime: str) -> dict[float, list[float]]:
    out: dict[float, list[float]] = {}
    for row in payload["grid"]:
        alpha = float(row["trust"])
        out[alpha] = [float(x) for x in row["scenario_errors_by_regime"][regime]]
    return out


def fit_from_02b_multi(
    payload: Mapping[str, Any],
    *,
    protocol: str,
    lam: float = DEFAULT_LAMBDA,
    grid: tuple[float, ...] = DEFAULT_GRID,
    share_primary: bool = False,
) -> TrustField:
    """Construct T from the frozen 02B multi-regime calibration JSON.

    The payload is the only allowed data source. Confirmatory files must not
    be passed here.
    """
    pred = predictive_nmae_from_multi(payload)
    horizon = float(payload.get("horizon", 2.0))
    field = TrustField(
        protocol=protocol,
        grid=grid,
        lam=lam,
        share_primary=share_primary,
        calibration_horizon=horizon,
        notes={
            "calibration_regimes": list(payload.get("regimes", [])),
            "predictive_weight_source": "02b_intervention_calibration_multi",
            "excluded_alpha_0.75": 0.75 not in grid,
        },
    )
    for regime in payload["regimes"]:
        errors = errors_from_multi(payload, regime)
        restricted = {a: errors[a] for a in grid if a in errors}
        field.add(
            fit_cell(
                estimand=CALIBRATION_ESTIMAND,
                intervention=DEFAULT_INTERVENTION,
                regime=regime,
                errors_by_alpha=restricted,
                predictive_nmae=pred,
                lam=lam,
                grid=grid,
                calibration_horizon=horizon,
            )
        )
    return field


def load_02b_multi(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def loso_cell_alphas(
    payload: Mapping[str, Any],
    *,
    lam: float = DEFAULT_LAMBDA,
    grid: tuple[float, ...] = DEFAULT_GRID,
) -> dict[str, list[float]]:
    """Leave-one-scenario-out selected alpha inside each calibration regime."""
    from .trust import cell_objective, select_alpha

    pred = predictive_nmae_from_multi(payload)
    out: dict[str, list[float]] = {}
    for regime in payload["regimes"]:
        errors = {a: errors_from_multi(payload, regime)[a] for a in grid}
        n = len(next(iter(errors.values())))
        picks: list[float] = []
        for i in range(n):
            mae = {a: (sum(v) - v[i]) / (n - 1) for a, v in errors.items()}
            picks.append(select_alpha(cell_objective(mae, predictive_nmae=pred, lam=lam, grid=grid)))
        out[regime] = picks
    return out
