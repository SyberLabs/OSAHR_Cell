from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from liquid_osahr02b.field import HazardBounds, Scenario, HEADS, HEAD_INDEX, graph_view
from liquid_osahr02b.hybrid import HybridLiquidRuntime, NEURAL_RULES
from liquid_osahr02b.ran import (
    RANConfig,
    RANPhysics,
    RANOracleField,
    RANMechanisticField,
    ResidualGraphCfC,
    ResidualRANField,
    RAN_STRUCT_DIM,
)
from liquid_osahr02b.ran_experiment import run_counterfactual
from liquid_osahr02b.telemetry import SrsRANKPMAdapter, SrsRANNativeJSONAdapter, FiveGLenaCSVAdapter
from liquid_osahr02b.twin import TwinConfig, build_model

from osahr import RuntimeConfig, SchedulerKind

ROOT = Path(__file__).resolve().parents[1]
BOUNDS = HazardBounds()
SCENARIO = Scenario(1.0, 1.0, 1.0, 1.0)


def _residual_model() -> ResidualGraphCfC:
    ck = torch.load(ROOT / "artifacts" / "residual_cfc.pt", map_location="cpu", weights_only=False)
    model = ResidualGraphCfC(RAN_STRUCT_DIM, int(ck["config"]["hidden_size"]))
    model.load_state_dict(ck["state_dict"])
    model.eval()
    return model


def _runtime(*, trust: float = 1.0, seed: int = 9231, horizon: float = 3.0, verify: bool = False):
    model, index = build_model("semantic", SCENARIO, TwinConfig(horizon=horizon), BOUNDS)
    field = ResidualRANField(_residual_model(), index, SCENARIO, BOUNDS, seed=seed + 77, trust=trust)
    return HybridLiquidRuntime(
        model,
        field=field,
        root_seed=seed,
        config=RuntimeConfig(
            scheduler=SchedulerKind.THINNING,
            matcher_backend="incremental",
            incremental_verify=verify,
            max_simulation_time=horizon,
            thinning_window=0.35,
            max_events=100_000,
            max_thinning_windows_per_plan=250_000,
        ),
    )


def test_umi_pathloss_increases_with_distance():
    model, index = build_model("semantic", SCENARIO, TwinConfig(horizon=1), BOUNDS)
    p = RANPhysics(index, SCENARIO, seed=1)
    near = p._pathloss_umi(15.0, 1.0)
    far = p._pathloss_umi(120.0, 1.0)
    assert far > near


def test_los_probability_is_bounded_and_decreases_over_site_scale():
    assert 0 <= RANPhysics._los_probability(10.0) <= 1
    assert 0 <= RANPhysics._los_probability(120.0) <= 1
    assert RANPhysics._los_probability(10.0) > RANPhysics._los_probability(120.0)


def test_radio_telemetry_is_deterministic_for_seed_time_graph():
    model, index = build_model("semantic", SCENARIO, TwinConfig(horizon=1), BOUNDS)
    a = RANPhysics(index, SCENARIO, seed=100)
    b = RANPhysics(index, SCENARIO, seed=100)
    np.testing.assert_allclose(a.telemetry(0.731, model.graph), b.telemetry(0.731, model.graph), rtol=0, atol=0)


def test_radio_seed_changes_hidden_channel_realization():
    model, index = build_model("semantic", SCENARIO, TwinConfig(horizon=1), BOUNDS)
    a = RANPhysics(index, SCENARIO, seed=100).telemetry(0.731, model.graph)
    b = RANPhysics(index, SCENARIO, seed=101).telemetry(0.731, model.graph)
    assert np.max(np.abs(a - b)) > 1e-8


def test_link_kpis_are_finite_and_engineering_bounded():
    model, index = build_model("semantic", SCENARIO, TwinConfig(horizon=1), BOUNDS)
    p = RANPhysics(index, SCENARIO, seed=17)
    metrics = p.link_metrics(0.9)
    assert metrics
    for by_cell in metrics.values():
        for m in by_cell.values():
            assert np.isfinite(list(m.values())).all()
            assert 1 <= m["cqi"] <= 15
            assert 0.05 <= m["spectral_eff"] <= p.cfg.max_se_bps_hz
            assert 0 <= m["drop_prob"] <= 1
            assert 0 <= m["p_los"] <= 1


def test_srsran_adapter_normalizes_documented_metric_names():
    rec = SrsRANKPMAdapter(throughput_scale_to_mbps=1.0).parse({
        "time_s": 1.25,
        "rnti": 42,
        "pci": 7,
        "CQI": 11,
        "RSRP": -87.5,
        "RSRQ": -10.1,
        "SINR": 14.2,
        "DRB.UEThpDl": 82.0,
        "DRB.RlcPacketDropRateDl": 2.5,
    })
    assert rec.time_s == pytest.approx(1.25)
    assert rec.ue_id == "42"
    assert rec.cell_id == "7"
    assert rec.cqi == pytest.approx(11)
    assert rec.rsrp_dbm == pytest.approx(-87.5)
    assert rec.rsrq_db == pytest.approx(-10.1)
    assert rec.sinr_db == pytest.approx(14.2)
    assert rec.dl_throughput_mbps == pytest.approx(82.0)
    assert rec.dl_drop_rate == pytest.approx(0.025)



def test_srsran_native_scheduler_adapter_handles_nested_ue_metrics_and_units():
    payload = {
        "timestamp": "2026-08-18T10:00:00Z",
        "cells": [{
            "cell_metrics": {"pci": 17},
            "ue_list": [{
                "rnti": 17921,
                "cqi": 12,
                "dl_brate": 42000,
                "ul_brate": 6500,
                "pusch_snr_db": 16.5,
                "pusch_rsrp_db": -91.0,
                "dl_nof_ok": 98,
                "dl_nof_nok": 2,
                "ul_nof_ok": 49,
                "ul_nof_nok": 1,
            }],
        }],
    }
    recs = SrsRANNativeJSONAdapter().parse_records(payload, default_time_s=1.75)
    assert len(recs) == 1
    r = recs[0]
    assert r.time_s == pytest.approx(1.75)
    assert r.ue_id == "17921" and r.cell_id == "17"
    assert r.cqi == pytest.approx(12)
    assert r.sinr_db == pytest.approx(16.5)
    assert r.rsrp_dbm == pytest.approx(-91.0)
    assert r.dl_throughput_mbps == pytest.approx(42.0)
    assert r.ul_throughput_mbps == pytest.approx(6.5)
    assert r.dl_drop_rate == pytest.approx(0.02)
    assert r.ul_success_rate == pytest.approx(0.98)

def test_5glena_adapter_requires_time_and_normalizes_row():
    adapter = FiveGLenaCSVAdapter()
    with pytest.raises(ValueError):
        adapter.parse_row({"SINR": 10})
    rec = adapter.parse_row({"Time": "0.5", "IMSI": "3", "CellId": "2", "SINR": "12.5", "CQI": "10"})
    assert rec.time_s == pytest.approx(0.5)
    assert rec.ue_id == "3"
    assert rec.cell_id == "2"
    assert rec.sinr_db == pytest.approx(12.5)


def test_oracle_and_mechanistic_rates_obey_global_bounds():
    model, index = build_model("semantic", Scenario(1.2, 1.3, 0.8, 1.1), TwinConfig(horizon=1), BOUNDS)
    p = RANPhysics(index, Scenario(1.2, 1.3, 0.8, 1.1), seed=19)
    upper = BOUNDS.vector().reshape(1, -1)
    for t in (0.0, 0.13, 0.91, 2.7):
        for rates in (p.oracle_rates(t, model.graph, BOUNDS), p.mechanistic_rates(t, model.graph, BOUNDS)):
            assert np.isfinite(rates).all()
            assert (rates >= 0).all()
            assert (rates <= upper + 1e-12).all()


def test_mechanistic_prior_is_not_identical_to_oracle():
    scenario = Scenario(1.25, 1.25, 0.9, 1.1)
    model, index = build_model("semantic", scenario, TwinConfig(horizon=1), BOUNDS)
    p = RANPhysics(index, scenario, seed=21)
    oracle = p.oracle_rates(0.7, model.graph, BOUNDS)
    mech = p.mechanistic_rates(0.7, model.graph, BOUNDS)
    assert np.max(np.abs(oracle - mech)) > 1e-5




def test_trust_zero_rate_query_then_state_query_is_cache_safe():
    model, index = build_model("semantic", SCENARIO, TwinConfig(horizon=1), BOUNDS)
    field = ResidualRANField(_residual_model(), index, SCENARIO, BOUNDS, seed=113, trust=0.0)
    field.initialize(model.graph)
    rates = field.base_rates_at(0.41, model.graph)
    state = field.state_at(0.41, model.graph)
    assert np.isfinite(rates).all()
    assert np.isfinite(state).all()
    np.testing.assert_array_equal(rates, field.physics.mechanistic_rates(0.41, model.graph, BOUNDS))

def test_residual_trust_zero_recovers_mechanistic_prior_exactly():
    model, index = build_model("semantic", SCENARIO, TwinConfig(horizon=1), BOUNDS)
    net = _residual_model()
    field = ResidualRANField(net, index, SCENARIO, BOUNDS, seed=88, trust=0.0)
    field.initialize(model.graph)
    for t in (0.0, 0.37, 1.11):
        got = field.base_rates_at(t, model.graph)
        expected = field.physics.mechanistic_rates(t, model.graph, BOUNDS)
        np.testing.assert_array_equal(got, expected)


def test_residual_head_is_bounded_even_for_extreme_latents():
    net = _residual_model()
    bounds = torch.tensor(BOUNDS.vector(), dtype=torch.float32)
    mechanism = torch.tensor(BOUNDS.vector(), dtype=torch.float32).view(1, 1, -1) * 0.35
    x = torch.zeros((1, 1, RAN_STRUCT_DIM), dtype=torch.float32)
    for mag in (0.0, 10.0, 1000.0):
        for sign in (-1.0, 1.0):
            h = torch.full((1, 1, net.hidden_size), sign * mag)
            for trust in (0.0, 0.25, 0.5, 1.0):
                rates = net.rates(h, x, mechanism, bounds, BOUNDS.floor, trust)
                assert torch.isfinite(rates).all()
                assert torch.all(rates >= BOUNDS.floor - 1e-7)
                assert torch.all(rates <= bounds.view(1, 1, -1) + 1e-6)


def test_residual_logit_correction_is_explicitly_limited():
    net = _residual_model()
    h = torch.randn(2, 5, net.hidden_size) * 100
    x = torch.randn(2, 5, RAN_STRUCT_DIM) * 100
    residual = net.residual(h, x)
    assert torch.max(torch.abs(residual)) <= net.residual_limit + 1e-6


def test_flow_is_identity_at_zero_elapsed_time():
    model, index = build_model("semantic", SCENARIO, TwinConfig(horizon=1), BOUNDS)
    p = RANPhysics(index, SCENARIO, seed=7)
    x = torch.from_numpy(p.telemetry(0.0, model.graph)).unsqueeze(0)
    A = torch.from_numpy(graph_view(model.graph, index, SCENARIO).adjacency).unsqueeze(0)
    net = _residual_model()
    h = net.initial_state(x)
    out = net.flow(h, x, A, torch.zeros((1, 1)))
    torch.testing.assert_close(out, h, rtol=0, atol=0)


def test_topology_changes_residual_continuous_evolution():
    model, index = build_model("semantic", Scenario(1.8, 1.0, 1.0, 1.0), TwinConfig(horizon=1), BOUNDS)
    p = RANPhysics(index, Scenario(1.8, 1.0, 1.0, 1.0), seed=7)
    net = _residual_model()
    x = torch.from_numpy(p.telemetry(0.0, model.graph)).unsqueeze(0)
    h = net.initial_state(x)
    A0 = torch.from_numpy(graph_view(model.graph, index, Scenario(1.8, 1.0, 1.0, 1.0)).adjacency).unsqueeze(0)
    g = model.graph.clone()
    ue = next(v for v in g.vertices.values() if v.type_id == "UE")
    assoc_id = next(eid for eid in g.edges_by_type["Association"] if any(i.vertex_id == ue.entity_id for i in g.edges[eid].incidences))
    old = g.edges[assoc_id]
    old_gnb = next(i.vertex_id for i in old.incidences if g.vertices[i.vertex_id].type_id == "GNB")
    g.remove_edge(assoc_id)
    new_gnb = next(v.entity_id for v in g.vertices.values() if v.type_id == "GNB" and v.entity_id != old_gnb)
    g.add_edge("Association", {"ue": (ue.entity_id,)}, {"gnb": (new_gnb,)})
    A1 = torch.from_numpy(graph_view(g, index, Scenario(1.8, 1.0, 1.0, 1.0)).adjacency).unsqueeze(0)
    dt = torch.tensor([[0.5]], dtype=x.dtype)
    y0 = net.flow(h, x, A0, dt)
    y1 = net.flow(h, x, A1, dt)
    assert torch.max(torch.abs(y0 - y1)) > 1e-7


def test_candidate_time_queries_are_pure_and_cached(monkeypatch):
    rt = _runtime(trust=1.0)
    before_hash = rt.state_hash
    before = copy.deepcopy(rt.field.snapshot())
    calls = {"n": 0}
    orig = rt.field.model.flow

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(rt.field.model, "flow", wrapped)
    t = 0.347
    r1 = rt.field.base_rates_at(t, rt.graph)
    r2 = rt.field.base_rates_at(t, rt.graph)
    s = rt.field.state_at(t, rt.graph)
    np.testing.assert_allclose(r1, r2)
    assert s.shape[0] == rt.field.index.n
    assert calls["n"] == 1
    assert rt.state_hash == before_hash
    np.testing.assert_allclose(before["anchor_state"], rt.field.snapshot()["anchor_state"], rtol=0, atol=0)


def test_every_neural_occurrence_actual_hazard_is_within_bound():
    rt = _runtime(trust=1.0)
    rt._refresh_occurrences(force=True, state_changed=True)
    for occ in rt.occurrence_index.occurrences.values():
        if occ.rule.rule_id not in NEURAL_RULES:
            continue
        actual = rt.occurrence_index.hazard_at(occ, graph=rt.graph, parameters=rt.parameters, memory=rt.memory, time=0.19)
        bound = rt.occurrence_index.bound_at(occ, graph=rt.graph, parameters=rt.parameters, memory=rt.memory, time=0.19, horizon=0.35)
        assert 0 <= actual <= bound + 1e-12


def test_accepted_event_commits_residual_liquid_anchor():
    rt = _runtime(trust=0.5, horizon=4.0)
    result = rt.step()
    assert result.event is not None
    assert rt.field.anchor_time == pytest.approx(result.event.post_time)
    assert result.event.cause["liquid_jump"]["residual_jump"] is False
    assert result.event.post_state_hash == rt.state_hash


def test_snapshot_restore_reproduces_next_event_and_augmented_hash():
    rt = _runtime(trust=0.5, seed=8812, horizon=4.0)
    for _ in range(3):
        rt.step()
    snap = rt.snapshot_hybrid()
    h0 = rt.state_hash
    t1 = rt.peek_next_event_time()
    e1 = rt.step().event
    h1 = rt.state_hash
    rt.restore_hybrid(snap)
    assert rt.state_hash == h0
    t2 = rt.peek_next_event_time()
    e2 = rt.step().event
    assert t2 == t1
    assert e1 is not None and e2 is not None
    assert e2.post_time == e1.post_time
    assert e2.cause.get("rule_id") == e1.cause.get("rule_id")
    assert rt.state_hash == h1


def test_incremental_reference_verification_survives_residual_run():
    rt = _runtime(trust=0.25, seed=114, horizon=1.5, verify=True)
    rt.run_until_time(1.5)
    assert rt.event_index > 0


def test_model_and_policy_independent_physics_seed_in_counterfactual_runner(monkeypatch):
    # Common random numbers require the physical realization to depend on
    # scenario/replicate, never the candidate model or policy.
    seen = []
    original = RANPhysics.__init__

    def wrapped(self, index, scenario, *, seed=0, cfg=None):
        seen.append(seed)
        original(self, index, scenario, seed=seed, cfg=cfg)

    monkeypatch.setattr(RANPhysics, "__init__", wrapped)
    net = _residual_model()
    for kind, trust, policy in (("mechanistic", 0.0, "throughput"), ("residual_test", 0.5, "semantic")):
        run_counterfactual(kind, SCENARIO, policy, scenario_id=901, replicate=0, root_seed=2026, model=net, trust=trust, horizon=0.25, bounds=BOUNDS)
    assert len(seen) >= 2
    assert seen[0] == seen[1]


def test_frozen_intervention_calibration_artifact_is_self_consistent():
    cal = json.loads((ROOT / "artifacts" / "intervention_calibration_multi.json").read_text())
    assert cal["selected_trust"] in {0.0, 0.25, 0.5, 0.75, 1.0}
    best = min(cal["grid"], key=lambda r: (r["objective"], r["intervention_effect_mae"], r["predictive_nmae"]))
    assert cal["selected_trust"] == best["trust"]
    assert cal["selection_stability"]["leave_one_scenario_out"]["folds"] == 18


def test_confirmatory_release_has_complete_paired_design():
    import pandas as pd
    df = pd.read_csv(ROOT / "artifacts" / "confirmatory_release.csv")
    assert len(df) == 400
    assert set(df["regime"]) == {"id", "high_mobility", "high_stress", "weak_channel"}
    assert df.duplicated(["regime", "scenario", "replicate", "model", "policy"]).sum() == 0
    assert df["final_hash"].nunique() == len(df)
    assert set(df.groupby("regime")["scenario"].nunique()) == {5}
