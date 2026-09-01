from __future__ import annotations

from liquid_osahr05.claims import score_claim as score_claim_05

from osahr_cell.claims_bridge import (
    ActivationCounts,
    illegal_promotion,
    score_claim,
    score_semantic_contrast,
)

H = (0.0, 0.25, 0.5, 1.0)
ACTIVE = ActivationCounts(2, 0, 1, 0)


def test_reuses_05_score_claim_object():
    assert score_claim is score_claim_05


def test_semantic_vs_vault_contrast_uses_05_grammar():
    claim = score_semantic_contrast(
        oracle_effect=0.2,
        effects_by_alpha={0.0: 0.1, 0.25: 0.1, 0.5: -0.1, 1.0: 0.1},
        activation=ACTIVE,
        scenario=1,
        regime="id",
        horizon=60.0,
    )
    assert claim.status == "hold_unresolved"
    assert claim.grammar == "osahr05_claim_v0"
    assert claim.horizon == 60.0


def test_illegal_promotion_still_05_law():
    assert illegal_promotion("hold_unresolved", "match") is True
    assert illegal_promotion("admit", "match") is False
    assert illegal_promotion("outcome_unknown", "match") is False
