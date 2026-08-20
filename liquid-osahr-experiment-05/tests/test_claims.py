from __future__ import annotations

import pytest

from liquid_osahr05.claims import (
    ActivationCounts,
    illegal_promotion,
    point_direction,
    score_claim,
    signed,
)

QUIET = ActivationCounts(0, 0, 0, 0)
ACTIVE = ActivationCounts(2, 0, 1, 0)
H = (0.0, 0.25, 0.5, 1.0)


def _score(oracle, ensemble, activation=ACTIVE, eps=0.0):
    return score_claim(
        estimand="goal_utility_ratio",
        regime="id",
        scenario=1,
        oracle_effect=oracle,
        effects_by_alpha=ensemble,
        activation=activation,
        horizon=22.0,
        eps=eps,
        hypotheses=H,
    )


def test_signed_dead_zone():
    assert signed(0.0, 0.0) == 0
    assert signed(0.01, 0.02) == 0
    assert signed(-0.03, 0.02) == -1
    assert signed(0.03, 0.02) == 1
    with pytest.raises(ValueError):
        signed(1.0, -0.1)


def test_unknown_when_oracle_is_zero():
    claim = _score(0.0, {0.0: 0.1, 0.25: 0.0, 0.5: -0.2, 1.0: 0.4}, activation=QUIET)
    assert claim.status == "outcome_unknown"
    assert claim.effect_expressed is False
    assert claim.activation_without_effect is False
    assert claim.response_activation is False


def test_activation_without_effect():
    claim = _score(0.0, {a: 0.0 for a in H}, activation=ACTIVE)
    assert claim.status == "outcome_unknown"
    assert claim.activation_without_effect is True
    assert claim.notes == "oracle contrast not expressed"


def test_admit_when_all_agree_with_oracle():
    claim = _score(0.2, {0.0: 0.18, 0.25: 0.21, 0.5: 0.19, 1.0: 0.22})
    assert claim.status == "admit"
    assert claim.oracle_sign == 1
    assert set(claim.signs_by_alpha.values()) == {1}


def test_hold_when_signs_flip():
    claim = _score(0.2, {0.0: 0.1, 0.25: 0.1, 0.5: -0.1, 1.0: 0.1})
    assert claim.status == "hold_unresolved"
    assert claim.notes == "residual signs disagree"


def test_hold_when_some_hypotheses_are_silent():
    claim = _score(0.2, {0.0: 0.1, 0.25: 0.0, 0.5: 0.1, 1.0: 0.1})
    assert claim.status == "hold_unresolved"


def test_reject_when_ensemble_agrees_against_oracle():
    claim = _score(0.2, {0.0: -0.1, 0.25: -0.2, 0.5: -0.15, 1.0: -0.11})
    assert claim.status == "reject"
    assert claim.notes == "ensemble agrees, disagrees with oracle"


def test_reject_when_ensemble_silent_and_oracle_expressed():
    claim = _score(0.2, {a: 0.0 for a in H}, activation=QUIET)
    assert claim.status == "reject"
    assert claim.notes == "ensemble silent while oracle expressed"
    assert claim.response_activation is False


def test_incomplete_ensemble_is_an_error():
    with pytest.raises(ValueError, match="ensemble must be exactly"):
        _score(0.2, {0.0: 0.1, 1.0: 0.1})


def test_illegal_promotion_only_when_point_matches_and_ensemble_withholds():
    assert illegal_promotion("hold_unresolved", "match") is True
    assert illegal_promotion("reject", "match") is True
    assert illegal_promotion("admit", "match") is False
    assert illegal_promotion("hold_unresolved", "mismatch") is False
    assert illegal_promotion("hold_unresolved", "unknown") is False
    assert illegal_promotion("outcome_unknown", "match") is False


def test_point_direction_unknown_if_either_side_is_silent():
    assert point_direction(0.0, 0.2, 0.0) == "unknown"
    assert point_direction(0.2, 0.0, 0.0) == "unknown"
    assert point_direction(0.2, 0.1, 0.0) == "match"
    assert point_direction(0.2, -0.1, 0.0) == "mismatch"
