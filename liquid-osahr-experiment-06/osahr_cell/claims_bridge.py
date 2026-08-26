"""Reuse Experiment 05 claim grammar. Do not copy-rewrite score_claim."""
from __future__ import annotations

import sys
from typing import Any

from .protocol import EXP05


def _ensure_05() -> None:
    path = str(EXP05)
    if path not in sys.path:
        sys.path.insert(0, path)


_ensure_05()

from liquid_osahr05.claims import (  # noqa: E402
    ActivationCounts,
    ClaimStatus,
    InterventionClaim,
    illegal_promotion,
    point_direction,
    score_claim,
    signed,
)

__all__ = [
    "ActivationCounts",
    "ClaimStatus",
    "InterventionClaim",
    "illegal_promotion",
    "point_direction",
    "score_claim",
    "signed",
    "score_semantic_contrast",
]


def score_semantic_contrast(
    *,
    oracle_effect: float,
    effects_by_alpha: dict[float, float],
    activation: ActivationCounts,
    scenario: int,
    regime: str,
    horizon: float,
    eps: float = 0.0,
    estimand: str = "goal_utility_ratio",
    intervention: str = "semantic_vs_throughput",
) -> InterventionClaim:
    return score_claim(
        estimand=estimand,
        regime=regime,
        scenario=scenario,
        oracle_effect=oracle_effect,
        effects_by_alpha=effects_by_alpha,
        activation=activation,
        horizon=horizon,
        eps=eps,
        intervention=intervention,
    )


def claim_to_dict(claim: InterventionClaim) -> dict[str, Any]:
    return claim.to_json()
