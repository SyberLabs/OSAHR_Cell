"""Query-conditioned residual trust for Liquid-OSAHR.

T(q, I, r, h) is an answering policy over the 02B residual coefficient α.
It does not alter typed graph legality or the declared stochastic process.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_GRID: tuple[float, ...] = (0.0, 0.25, 0.5, 1.0)
DEFAULT_ALPHA = 0.0
DEFAULT_LAMBDA = 0.1
PRIMARY_ESTIMAND = "goal_utility_ratio"
DEFAULT_INTERVENTION = "semantic_vs_throughput"
INVARIANCE_TOL = 1e-12


@dataclass(frozen=True)
class QueryContext:
    estimand: str
    intervention: str = DEFAULT_INTERVENTION
    regime: str = "id"
    horizon: float | None = None

    def cell_key(self) -> tuple[str, str, str]:
        return (self.estimand, self.intervention, self.regime)


@dataclass(frozen=True)
class TrustCell:
    estimand: str
    intervention: str
    regime: str
    alpha: float
    objective_by_alpha: dict[str, float]
    mae_by_alpha: dict[str, float]
    predictive_nmae_by_alpha: dict[str, float]
    inadequacy: bool
    n_scenarios: int
    calibration_horizon: float | None = None

    def key(self) -> tuple[str, str, str]:
        return (self.estimand, self.intervention, self.regime)


@dataclass(frozen=True)
class TrustDecision:
    alpha: float
    source: str
    context: QueryContext
    cell: TrustCell | None = None
    notes: str = ""


def _fmt(alpha: float) -> str:
    return f"{alpha:.2f}"


def cell_objective(
    mae_by_alpha: Mapping[float, float],
    *,
    predictive_nmae: Mapping[float, float] | None = None,
    lam: float = DEFAULT_LAMBDA,
    grid: Sequence[float] = DEFAULT_GRID,
) -> dict[float, float]:
    out: dict[float, float] = {}
    for alpha in grid:
        if alpha not in mae_by_alpha:
            continue
        pred = 0.0 if predictive_nmae is None else float(predictive_nmae[alpha])
        out[float(alpha)] = float(mae_by_alpha[alpha]) + float(lam) * pred
    if not out:
        raise ValueError("no overlapping alphas between grid and mae_by_alpha")
    return out


def select_alpha(
    objective_by_alpha: Mapping[float, float],
) -> float:
    """Minimize objective; ties break toward smaller alpha."""
    ranked = sorted((float(j), float(a)) for a, j in objective_by_alpha.items())
    return ranked[0][1]


def errors_are_invariant(
    errors_by_alpha: Mapping[float, Sequence[float]],
    *,
    tol: float = INVARIANCE_TOL,
) -> bool:
    series = [tuple(float(x) for x in v) for v in errors_by_alpha.values()]
    if len(series) < 2:
        return False
    ref = series[0]
    return all(
        len(s) == len(ref) and all(abs(a - b) <= tol for a, b in zip(s, ref))
        for s in series[1:]
    )


def fit_cell(
    *,
    estimand: str,
    intervention: str,
    regime: str,
    errors_by_alpha: Mapping[float, Sequence[float]],
    predictive_nmae: Mapping[float, float] | None = None,
    lam: float = DEFAULT_LAMBDA,
    grid: Sequence[float] = DEFAULT_GRID,
    calibration_horizon: float | None = None,
) -> TrustCell:
    mae = {float(a): float(sum(v) / len(v)) for a, v in errors_by_alpha.items() if len(v)}
    objective = cell_objective(mae, predictive_nmae=predictive_nmae, lam=lam, grid=grid)
    alpha = select_alpha(objective)
    n = len(next(iter(errors_by_alpha.values())))
    return TrustCell(
        estimand=estimand,
        intervention=intervention,
        regime=regime,
        alpha=alpha,
        objective_by_alpha={_fmt(a): j for a, j in objective.items()},
        mae_by_alpha={_fmt(a): mae[a] for a in objective},
        predictive_nmae_by_alpha={
            _fmt(a): (0.0 if predictive_nmae is None else float(predictive_nmae[a]))
            for a in objective
        },
        inadequacy=errors_are_invariant({a: errors_by_alpha[a] for a in objective}),
        n_scenarios=n,
        calibration_horizon=calibration_horizon,
    )


@dataclass
class TrustField:
    """Lookup table plus conservative fallback. Not a learned map."""

    protocol: str
    cells: dict[tuple[str, str, str], TrustCell] = field(default_factory=dict)
    grid: tuple[float, ...] = DEFAULT_GRID
    default_alpha: float = DEFAULT_ALPHA
    lam: float = DEFAULT_LAMBDA
    primary_estimand: str = PRIMARY_ESTIMAND
    share_primary: bool = False
    calibration_horizon: float | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    def add(self, cell: TrustCell) -> None:
        if cell.alpha not in self.grid:
            raise ValueError(f"cell alpha {cell.alpha} outside grid {self.grid}")
        self.cells[cell.key()] = cell

    def select(self, context: QueryContext) -> TrustDecision:
        key = context.cell_key()
        cell = self.cells.get(key)
        if cell is not None:
            return TrustDecision(
                alpha=cell.alpha,
                source="calibrated_cell",
                context=context,
                cell=cell,
            )
        if self.share_primary and context.estimand != self.primary_estimand:
            inherited = self.cells.get(
                (self.primary_estimand, context.intervention, context.regime)
            )
            if inherited is not None:
                return TrustDecision(
                    alpha=inherited.alpha,
                    source="inherit_primary_estimand",
                    context=context,
                    cell=inherited,
                    notes=f"uncalibrated query inherits {self.primary_estimand}",
                )
        reason = "unknown_cell"
        if all(c.estimand != context.estimand for c in self.cells.values()):
            reason = "unknown_estimand"
        elif all(c.regime != context.regime for c in self.cells.values()):
            reason = "unknown_regime"
        return TrustDecision(
            alpha=self.default_alpha,
            source="default_mechanistic",
            context=context,
            notes=reason,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "grid": list(self.grid),
            "default_alpha": self.default_alpha,
            "lam": self.lam,
            "primary_estimand": self.primary_estimand,
            "share_primary": self.share_primary,
            "calibration_horizon": self.calibration_horizon,
            "notes": self.notes,
            "cells": [asdict(c) for c in sorted(self.cells.values(), key=lambda c: c.key())],
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "TrustField":
        field_obj = cls(
            protocol=str(payload["protocol"]),
            grid=tuple(float(a) for a in payload.get("grid", DEFAULT_GRID)),
            default_alpha=float(payload.get("default_alpha", DEFAULT_ALPHA)),
            lam=float(payload.get("lam", DEFAULT_LAMBDA)),
            primary_estimand=str(payload.get("primary_estimand", PRIMARY_ESTIMAND)),
            share_primary=bool(payload.get("share_primary", False)),
            calibration_horizon=payload.get("calibration_horizon"),
            notes=dict(payload.get("notes") or {}),
        )
        for raw in payload.get("cells", []):
            field_obj.add(
                TrustCell(
                    estimand=raw["estimand"],
                    intervention=raw["intervention"],
                    regime=raw["regime"],
                    alpha=float(raw["alpha"]),
                    objective_by_alpha=dict(raw["objective_by_alpha"]),
                    mae_by_alpha=dict(raw["mae_by_alpha"]),
                    predictive_nmae_by_alpha=dict(raw["predictive_nmae_by_alpha"]),
                    inadequacy=bool(raw["inadequacy"]),
                    n_scenarios=int(raw["n_scenarios"]),
                    calibration_horizon=raw.get("calibration_horizon"),
                )
            )
        return field_obj

    def map_table(self, estimands: Iterable[str], regimes: Iterable[str], intervention: str) -> dict[str, dict[str, TrustDecision]]:
        out: dict[str, dict[str, TrustDecision]] = {}
        for q in estimands:
            out[q] = {}
            for r in regimes:
                out[q][r] = self.select(QueryContext(q, intervention, r, self.calibration_horizon))
        return out
