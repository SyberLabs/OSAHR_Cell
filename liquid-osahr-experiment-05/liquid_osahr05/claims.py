"""HLMG-inspired claim status over a residual-hypothesis ensemble.

This module does not select α. Incomplete ensembles raise.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Mapping

HYPOTHESES = (0.0, 0.25, 0.5, 1.0)
ClaimStatus = Literal["admit", "hold_unresolved", "reject", "outcome_unknown"]
PointDirection = Literal["match", "mismatch", "unknown"]
Sign = Literal[-1, 0, 1]


def signed(value: float, eps: float) -> Sign:
    if eps < 0:
        raise ValueError("eps must be nonnegative")
    if value > eps:
        return 1
    if value < -eps:
        return -1
    return 0


@dataclass(frozen=True)
class ActivationCounts:
    events: float
    outages: float
    handovers: float
    reroutes: float

    def activated(self) -> bool:
        return any(abs(float(x)) > 0.0 for x in (self.events, self.outages, self.handovers, self.reroutes))


@dataclass(frozen=True)
class InterventionClaim:
    grammar: str
    estimand: str
    intervention: str
    regime: str
    scenario: int
    horizon: float
    eps: float
    oracle_effect: float
    effects_by_alpha: dict[str, float]
    oracle_sign: int
    signs_by_alpha: dict[str, int]
    response_activation: bool
    effect_expressed: bool
    activation_without_effect: bool
    status: ClaimStatus
    notes: str
    spread: float

    def to_json(self) -> dict:
        return asdict(self)


def _alpha_key(alpha: float) -> str:
    return f"{float(alpha):.2f}"


def _require_ensemble(effects_by_alpha: Mapping[float, float], hypotheses: tuple[float, ...]) -> dict[float, float]:
    missing = [a for a in hypotheses if a not in effects_by_alpha]
    extra = [a for a in effects_by_alpha if a not in hypotheses]
    if missing or extra:
        raise ValueError(f"ensemble must be exactly {hypotheses}; missing={missing} extra={extra}")
    return {float(a): float(effects_by_alpha[a]) for a in hypotheses}


def score_claim(
    *,
    estimand: str,
    regime: str,
    scenario: int,
    oracle_effect: float,
    effects_by_alpha: Mapping[float, float],
    activation: ActivationCounts,
    horizon: float,
    eps: float = 0.0,
    intervention: str = "semantic_vs_throughput",
    hypotheses: tuple[float, ...] = HYPOTHESES,
    grammar: str = "osahr05_claim_v0",
) -> InterventionClaim:
    ensemble = _require_ensemble(effects_by_alpha, hypotheses)
    oracle_sign = signed(oracle_effect, eps)
    signs = {a: signed(ensemble[a], eps) for a in hypotheses}
    sign_set = set(signs.values())
    expressed = oracle_sign != 0
    activated = activation.activated()

    if not expressed:
        status: ClaimStatus = "outcome_unknown"
        notes = "oracle contrast not expressed"
    elif sign_set == {0}:
        status = "reject"
        notes = "ensemble silent while oracle expressed"
    elif sign_set == {1} or sign_set == {-1}:
        common = next(iter(sign_set))
        if common == oracle_sign:
            status = "admit"
            notes = "all hypotheses and oracle agree"
        else:
            status = "reject"
            notes = "ensemble agrees, disagrees with oracle"
    else:
        status = "hold_unresolved"
        notes = "residual signs disagree"

    keyed = {_alpha_key(a): ensemble[a] for a in hypotheses}
    keyed_signs = {_alpha_key(a): int(signs[a]) for a in hypotheses}
    return InterventionClaim(
        grammar=grammar,
        estimand=estimand,
        intervention=intervention,
        regime=regime,
        scenario=int(scenario),
        horizon=float(horizon),
        eps=float(eps),
        oracle_effect=float(oracle_effect),
        effects_by_alpha=keyed,
        oracle_sign=int(oracle_sign),
        signs_by_alpha=keyed_signs,
        response_activation=activated,
        effect_expressed=expressed,
        activation_without_effect=activated and not expressed,
        status=status,
        notes=notes,
        spread=float(max(ensemble.values()) - min(ensemble.values())),
    )


def point_direction(oracle_effect: float, point_effect: float, eps: float) -> PointDirection:
    oracle_sign = signed(oracle_effect, eps)
    point_sign = signed(point_effect, eps)
    if oracle_sign == 0 or point_sign == 0:
        return "unknown"
    if point_sign == oracle_sign:
        return "match"
    return "mismatch"


def illegal_promotion(status: ClaimStatus, direction: PointDirection) -> bool:
    return direction == "match" and status in ("hold_unresolved", "reject")
