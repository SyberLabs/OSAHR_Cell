from __future__ import annotations

import copy
from pathlib import Path
import sys

import numpy as np
import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for _parent in (ROOT, *ROOT.parents):
    if (_parent / "osahr" / "__init__.py").exists():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break

from osahr import RuntimeConfig, SchedulerKind
from liquid_osahr02a.field import (
    AnchoredGraphCfC,
    HazardBounds,
    NeuralLiquidField,
    OracleField,
    Scenario,
    graph_view,
)
from liquid_osahr02a.hybrid import HybridLiquidRuntime, NEURAL_RULES
from liquid_osahr02a.twin import TwinConfig, build_model
from liquid_osahr02a.training import load_checkpoint


BOUNDS = HazardBounds()
SCENARIO = Scenario(1.0, 1.0, 1.0, 1.0)


def _runtime(field_kind='oracle', seed=1234, horizon=7.0, verify=False):
    model, index = build_model('semantic', SCENARIO, TwinConfig(horizon=horizon), BOUNDS)
    if field_kind == 'oracle':
        field = OracleField(index, SCENARIO, BOUNDS, seed=seed, initial_noise=0.0)
    elif field_kind == 'cfc_random':
        torch.manual_seed(7)
        net = AnchoredGraphCfC(graph_view(model.graph, index, SCENARIO).structural.shape[1], hidden_size=8)
        field = NeuralLiquidField(net, index, SCENARIO, BOUNDS, name='cfc_random')
    else:
        ckpt = ROOT / 'artifacts' / f'{field_kind}_seed260218.pt'
        net, _ = load_checkpoint(ckpt)
        field = NeuralLiquidField(net, index, SCENARIO, BOUNDS, name=field_kind)
    rt = HybridLiquidRuntime(
        model,
        field=field,
        root_seed=seed,
        config=RuntimeConfig(
            scheduler=SchedulerKind.THINNING,
            matcher_backend='incremental',
            incremental_verify=verify,
            max_simulation_time=horizon,
            thinning_window=.55,
            max_events=50_000,
            max_thinning_windows_per_plan=100_000,
        ),
    )
    return rt


def test_oracle_rates_respect_certified_bounds():
    rt = _runtime('oracle')
    maxima = BOUNDS.vector()[None, :]
    for t in np.linspace(0.0, 4.0, 17):
        rates = rt.field.base_rates_at(float(t), rt.graph)
        assert np.all(np.isfinite(rates))
        assert np.all(rates >= 0.0)
        assert np.all(rates <= maxima + 1e-12)


def test_neural_rates_respect_certified_bounds():
    rt = _runtime('cfc_closed')
    maxima = BOUNDS.vector()[None, :]
    for t in np.linspace(0.0, 3.0, 13):
        rates = rt.field.base_rates_at(float(t), rt.graph)
        assert np.all(rates >= 0.0)
        assert np.all(rates <= maxima + 1e-6)


def test_state_query_is_pure_and_anchor_continuous():
    rt = _runtime('cfc_closed')
    before = copy.deepcopy(rt.field.snapshot())
    h0 = rt.field.state_at(rt.time, rt.graph)
    h1 = rt.field.state_at(rt.time, rt.graph)
    after = rt.field.snapshot()
    np.testing.assert_allclose(h0, h1, rtol=0, atol=0)
    np.testing.assert_allclose(before['anchor_state'], after['anchor_state'], rtol=0, atol=0)
    assert before['anchor_time'] == after['anchor_time'] == rt.time


def test_repeated_candidate_peek_does_not_mutate_augmented_state():
    rt = _runtime('cfc_closed')
    hash0 = rt.state_hash
    snap0 = copy.deepcopy(rt.field.snapshot())
    time0 = rt.time
    p1 = rt.peek_next_event_time()
    hash1 = rt.state_hash
    p2 = rt.peek_next_event_time()
    assert p1 == p2
    assert rt.time == time0
    assert rt.state_hash == hash0 == hash1
    np.testing.assert_allclose(snap0['anchor_state'], rt.field.snapshot()['anchor_state'])


def test_neural_field_evaluation_cache_reuses_flow_for_same_time_epoch(monkeypatch):
    rt = _runtime('cfc_closed')
    calls = {'n': 0}
    original = rt.field.model.flow

    def wrapped(*args, **kwargs):
        calls['n'] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(rt.field.model, 'flow', wrapped)
    t = .371
    a = rt.field.base_rates_at(t, rt.graph)
    b = rt.field.base_rates_at(t, rt.graph)
    c = rt.field.state_at(t, rt.graph)
    np.testing.assert_allclose(a, b)
    assert c.shape[0] == rt.field.index.n
    assert calls['n'] == 1


def test_every_neural_occurrence_actual_hazard_is_bounded():
    rt = _runtime('cfc_closed')
    rt._refresh_occurrences(force=True, state_changed=True)
    for occ in rt.occurrence_index.occurrences.values():
        if occ.rule.rule_id not in NEURAL_RULES:
            continue
        actual = rt.occurrence_index.hazard_at(
            occ, graph=rt.graph, parameters=rt.parameters, memory=rt.memory, time=.123
        )
        bound = rt.occurrence_index.bound_at(
            occ, graph=rt.graph, parameters=rt.parameters, memory=rt.memory,
            time=.123, horizon=.55,
        )
        assert 0.0 <= actual <= bound + 1e-12


def test_accepted_structural_event_commits_liquid_anchor():
    rt = _runtime('oracle', horizon=8.0)
    start_anchor = rt.field.anchor_time
    result = rt.step()
    assert result.event is not None
    assert rt.field.anchor_time == pytest.approx(result.event.post_time)
    assert rt.field.anchor_time >= start_anchor
    assert 'liquid_jump' in result.event.cause
    assert result.event.post_state_hash == rt.state_hash


def test_graph_rewrite_changes_topology_view_on_handover_when_it_occurs():
    # Increase mobility to make a handover likely, but keep the test deterministic.
    scenario = Scenario(2.0, 1.0, 1.0, 1.0)
    model, index = build_model('semantic', scenario, TwinConfig(horizon=20.0), BOUNDS)
    field = OracleField(index, scenario, BOUNDS, seed=88, initial_noise=0.0)
    rt = HybridLiquidRuntime(model, field=field, root_seed=88, config=RuntimeConfig(
        scheduler=SchedulerKind.THINNING, matcher_backend='incremental', max_simulation_time=20,
        thinning_window=.55, max_events=100_000, max_thinning_windows_per_plan=200_000,
    ))
    initial = graph_view(rt.graph, index, scenario).adjacency[0].copy()
    changed = False
    for _ in range(500):
        if rt.time >= 20: break
        res = rt.step()
        if res.event and res.event.cause.get('rule_id') == 'handover':
            current = graph_view(rt.graph, index, scenario).adjacency[0]
            changed = not np.array_equal(initial, current)
            break
    assert changed, 'expected deterministic seed to produce a handover and topology change'


def test_snapshot_restore_reproduces_next_event_time_and_state():
    rt = _runtime('cfc_closed', seed=9182, horizon=8.0)
    for _ in range(4): rt.step()
    snap = rt.snapshot_hybrid()
    hash_at_snap = rt.state_hash
    next_a = rt.peek_next_event_time()
    event_a = rt.step().event
    hash_a = rt.state_hash
    rt.restore_hybrid(snap)
    assert rt.state_hash == hash_at_snap
    next_b = rt.peek_next_event_time()
    event_b = rt.step().event
    assert next_b == next_a
    assert event_a is not None and event_b is not None
    assert event_b.post_time == event_a.post_time
    assert event_b.cause.get('rule_id') == event_a.cause.get('rule_id')
    assert rt.state_hash == hash_a


def test_incremental_reference_verification_survives_closed_loop_run():
    rt = _runtime('cfc_closed', seed=121, horizon=4.0, verify=True)
    rt.run_until_time(4.0)
    assert rt.event_index > 0


def test_dynamic_topology_field_differs_from_frozen_topology_after_handover():
    # Use identical trained weights and latent anchors but freeze one model's initial adjacency.
    model, index = build_model('semantic', Scenario(2.0,1.0,1.0,1.0), TwinConfig(horizon=12), BOUNDS)
    net, _ = load_checkpoint(ROOT/'artifacts'/'cfc_closed_seed260218.pt')
    initial_view = graph_view(model.graph, index, Scenario(2.0,1.0,1.0,1.0))
    dyn = NeuralLiquidField(copy.deepcopy(net), index, Scenario(2.0,1.0,1.0,1.0), BOUNDS, name='dyn')
    frozen = NeuralLiquidField(copy.deepcopy(net), index, Scenario(2.0,1.0,1.0,1.0), BOUNDS, name='frozen', frozen_adjacency=initial_view.adjacency)
    dyn.initialize(model.graph); frozen.initialize(model.graph)
    # Create a legal topology-modified graph manually by moving first UE association.
    g = model.graph.clone()
    ue = next(v for v in g.vertices.values() if v.type_id=='UE')
    assocs = [g.edges[e] for e in list(g.edges_by_type.get('Association',set())) if any(i.vertex_id==ue.entity_id for i in g.edges[e].incidences)]
    old = assocs[0]
    g.remove_edge(old.entity_id)
    gnbs = sorted([v for v in g.vertices.values() if v.type_id=='GNB'], key=lambda v:v.entity_id)
    old_gnb = next(i.vertex_id for i in old.incidences if g.vertices.get(i.vertex_id) and g.vertices[i.vertex_id].type_id=='GNB')
    new_gnb = next(v.entity_id for v in gnbs if v.entity_id != old_gnb)
    g.add_edge('Association', {'ue':(ue.entity_id,)}, {'gnb':(new_gnb,)})
    hd = dyn.state_at(.7, g)
    hf = frozen.state_at(.7, g)
    assert np.max(np.abs(hd-hf)) > 1e-7


def test_openloop_field_ignores_event_feedback_but_respects_legality_mask():
    from liquid_osahr02a.field import FrozenOpenLoopNeuralField, HEAD_INDEX
    model,index=build_model('semantic',SCENARIO,TwinConfig(horizon=5),BOUNDS)
    net,_=load_checkpoint(ROOT/'artifacts'/'cfc_closed_seed260218.pt')
    fld=FrozenOpenLoopNeuralField(net,index,SCENARIO,BOUNDS)
    fld.initialize(model.graph)
    h_before=fld.state_at(1.0,model.graph)
    # Fail one edge manually. Continuous open-loop state must not change.
    g=model.graph.clone(); edge=next(v for v in g.vertices.values() if v.type_id=='EdgeNode')
    edge.attributes['available']=False; g.epoch += 1
    h_after=fld.state_at(1.0,g)
    np.testing.assert_allclose(h_before,h_after,rtol=0,atol=0)
    rates=fld.base_rates_at(1.0,g); idx=index.id_to_index[edge.entity_id]
    assert rates[idx,HEAD_INDEX['failure']]==0.0
    assert rates[idx,HEAD_INDEX['recovery']]>0.0


def test_openloop_field_commit_is_state_noop():
    from liquid_osahr02a.field import FrozenOpenLoopNeuralField
    model,index=build_model('semantic',SCENARIO,TwinConfig(horizon=5),BOUNDS)
    net,_=load_checkpoint(ROOT/'artifacts'/'cfc_closed_seed260218.pt')
    fld=FrozenOpenLoopNeuralField(net,index,SCENARIO,BOUNDS); fld.initialize(model.graph)
    # Obtain a real match from a runtime so the affected mask is meaningful.
    rt=_runtime('cfc_closed',seed=44,horizon=5); rt._refresh_occurrences(force=True,state_changed=True)
    occ=next(iter(rt.occurrence_index.occurrences.values()))
    before=fld.snapshot()['initial_state'].copy()
    fld.commit_event(0.5,model.graph,model.graph,occ.rule.rule_id,occ.match)
    np.testing.assert_allclose(before,fld.snapshot()['initial_state'],rtol=0,atol=0)
    assert fld.anchor_time==0.0


def test_cfc_and_gru_flow_are_exact_identity_at_zero_elapsed_time():
    from liquid_osahr02a.field import AnchoredGraphGRU
    model,index=build_model('semantic',SCENARIO,TwinConfig(horizon=5),BOUNDS)
    view=graph_view(model.graph,index,SCENARIO)
    structural=torch.from_numpy(view.structural).unsqueeze(0)
    adjacency=torch.from_numpy(view.adjacency).unsqueeze(0)
    for net in (
        AnchoredGraphCfC(structural.shape[-1],hidden_size=8),
        AnchoredGraphGRU(structural.shape[-1],hidden_size=8),
    ):
        h=net.initial_state(structural)
        out=net.flow(h,structural,adjacency,torch.zeros(1,1))
        torch.testing.assert_close(out,h,rtol=0,atol=0)


def test_neural_jump_changes_only_explicitly_affected_entities():
    model,index=build_model('semantic',SCENARIO,TwinConfig(horizon=5),BOUNDS)
    view=graph_view(model.graph,index,SCENARIO)
    structural=torch.from_numpy(view.structural).unsqueeze(0)
    net=AnchoredGraphCfC(structural.shape[-1],hidden_size=8,use_jumps=True)
    h=net.initial_state(structural)
    affected=torch.zeros(1,index.n)
    affected[0,0]=1.0
    event=torch.tensor([1],dtype=torch.long)
    post=net.jump(h,event,affected,structural)
    torch.testing.assert_close(post[:,1:],h[:,1:],rtol=0,atol=0)
    assert not torch.equal(post[:,0],h[:,0])


def test_sigmoid_hazard_heads_are_globally_inside_declared_bounds():
    model,index=build_model('semantic',SCENARIO,TwinConfig(horizon=5),BOUNDS)
    view=graph_view(model.graph,index,SCENARIO)
    structural=torch.from_numpy(view.structural).unsqueeze(0)
    net=AnchoredGraphCfC(structural.shape[-1],hidden_size=8)
    bounds=torch.tensor(BOUNDS.vector(),dtype=structural.dtype)
    # Deliberately extreme latent inputs exercise saturation in both directions.
    for magnitude in (0.0,10.0,1000.0):
        for sign in (-1.0,1.0):
            h=torch.full((1,index.n,8),sign*magnitude,dtype=structural.dtype)
            rates=net.rates(h,structural,bounds,BOUNDS.floor)
            assert torch.all(torch.isfinite(rates))
            assert torch.all(rates >= BOUNDS.floor - 1e-7)
            assert torch.all(rates <= bounds.view(1,1,-1) + 1e-6)


def test_cfc_and_gru_are_near_matched_parameter_budget():
    from liquid_osahr02a.field import AnchoredGraphGRU, parameter_count
    cfc=AnchoredGraphCfC(14,hidden_size=20)
    gru=AnchoredGraphGRU(14,hidden_size=26)
    nc,ng=parameter_count(cfc),parameter_count(gru)
    assert abs(nc-ng)/((nc+ng)/2.0) < 0.02
