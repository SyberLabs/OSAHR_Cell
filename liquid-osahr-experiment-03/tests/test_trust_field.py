from __future__ import annotations

import json
from pathlib import Path

import pytest

from liquid_osahr03.calibration import fit_from_02b_multi, loso_cell_alphas
from liquid_osahr03.trust import (
    QueryContext,
    TrustField,
    cell_objective,
    errors_are_invariant,
    fit_cell,
    select_alpha,
)

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = (
    REPO.parent
    / "liquid-osahr-experiment-02b"
    / "liquid-osahr-exp02b-stage-final"
    / "artifacts"
    / "intervention_calibration_multi.json"
)


def test_ties_break_toward_smaller_alpha():
    assert select_alpha({0.0: 1.0, 0.25: 1.0, 1.0: 1.0}) == 0.0
    assert select_alpha({1.0: 0.5, 0.25: 0.5}) == 0.25


def test_unknown_cell_falls_back_to_mechanistic():
    field = TrustField(protocol="unit")
    d = field.select(QueryContext("mean_latency", regime="weak_channel"))
    assert d.alpha == 0.0
    assert d.source == "default_mechanistic"


def test_select_never_returns_off_grid_alpha():
    field = TrustField(protocol="unit", grid=(0.0, 0.5, 1.0))
    with pytest.raises(ValueError):
        field.add(
            fit_cell(
                estimand="goal_utility_ratio",
                intervention="semantic_vs_throughput",
                regime="id",
                errors_by_alpha={0.25: [0.1, 0.2]},
                lam=0.0,
                grid=(0.25,),
            )
        )


def test_predictive_term_breaks_intervention_mae_tie():
    mae = {0.0: 0.1, 0.5: 0.1, 1.0: 0.2}
    pred = {0.0: 0.05, 0.5: 0.01, 1.0: 0.0}
    obj = cell_objective(mae, predictive_nmae=pred, lam=0.1)
    assert select_alpha(obj) == 0.5


def test_primary_share_inherits_only_matching_regime():
    field = TrustField(protocol="share", share_primary=True)
    field.add(
        fit_cell(
            estimand="goal_utility_ratio",
            intervention="semantic_vs_throughput",
            regime="id",
            errors_by_alpha={0.0: [0.2], 0.5: [0.05]},
            lam=0.0,
        )
    )
    inherited = field.select(QueryContext("mean_latency", regime="id"))
    assert inherited.alpha == 0.5
    assert inherited.source == "inherit_primary_estimand"
    fallback = field.select(QueryContext("mean_latency", regime="weak_channel"))
    assert fallback.alpha == 0.0
    assert fallback.source == "default_mechanistic"


def test_invariance_detects_identical_error_vectors():
    errors = {0.0: [0.1, 0.0, 0.2], 0.5: [0.1, 0.0, 0.2], 1.0: [0.1, 0.0, 0.2]}
    assert errors_are_invariant(errors)
    errors[1.0] = [0.1, 0.0, 0.3]
    assert not errors_are_invariant(errors)


def test_roundtrip_json():
    field = TrustField(protocol="roundtrip", share_primary=True, calibration_horizon=2.0)
    field.add(
        fit_cell(
            estimand="goal_utility_ratio",
            intervention="semantic_vs_throughput",
            regime="id",
            errors_by_alpha={0.0: [0.1, 0.2], 1.0: [0.3, 0.0]},
            lam=0.0,
            calibration_horizon=2.0,
        )
    )
    restored = TrustField.from_json(field.to_json())
    d = restored.select(QueryContext("goal_utility_ratio", regime="id"))
    assert d.alpha == field.select(QueryContext("goal_utility_ratio", regime="id")).alpha
    assert restored.share_primary is True


@pytest.mark.skipif(not CALIBRATION.exists(), reason="02B calibration artifact missing")
def test_frozen_fit_uses_only_calibration_payload():
    payload = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    field = fit_from_02b_multi(payload, protocol="T_strict")
    assert set(c.regime for c in field.cells.values()) == {"id", "high_mobility", "high_stress"}
    assert all(c.estimand == "goal_utility_ratio" for c in field.cells.values())
    assert field.select(QueryContext("goal_utility_ratio", regime="weak_channel")).alpha == 0.0
    assert field.select(QueryContext("mean_latency", regime="id")).alpha == 0.0
    assert field.select(QueryContext("goal_utility_ratio", regime="id")).alpha == 0.5
    assert field.select(QueryContext("goal_utility_ratio", regime="high_stress")).alpha == 0.0


@pytest.mark.skipif(not CALIBRATION.exists(), reason="02B calibration artifact missing")
def test_calibration_loso_does_not_invent_alphas():
    payload = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    picks = loso_cell_alphas(payload)
    for regime, alphas in picks.items():
        assert len(alphas) == 6
        assert set(alphas) <= set(field_grid := {0.0, 0.25, 0.5, 1.0})
        del field_grid, regime
