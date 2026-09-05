from dataclasses import replace
import json
import math

import pytest

pytest.importorskip("rdflib", reason="Install .[benchmark] for the optional ontology probe")

from osahr import Expr, Model, Runtime
from benchmarks.ontology.baseline import DirectSSA, transitions
from benchmarks.ontology.compare import (
    OSAHRRunner, check_first_jump, check_generator, measure, run, runtime_transitions,
)
from benchmarks.ontology.model import (
    FIXTURE, compile_model, load_snapshot, project_state, replicate,
)


def test_complete_transition_generator_and_rewritten_graphs():
    assert check_generator(load_snapshot()) == {"states": 8, "transitions": 24, "passed": True}


def test_gate_rejects_wrong_hazard_even_if_event_names_match():
    def broken_compiler(snapshot, state):
        model = compile_model(snapshot, state)
        rules = (replace(model.rules[0], hazard=Expr("2 * rate")), model.rules[1])
        return Model(model.graph, model.boundary, rules)

    with pytest.raises(AssertionError, match="generator mismatch"):
        check_generator(load_snapshot(), broken_compiler)


def test_incremental_occurrences_stay_equivalent_after_real_events():
    snapshot = load_snapshot()
    runtime = Runtime(compile_model(snapshot), root_seed=908)
    for _ in range(30):
        state = project_state(runtime.graph, snapshot)
        assert runtime_transitions(runtime, snapshot) == transitions(snapshot, state)
        assert runtime.step().event is not None


def test_first_jump_against_analytic_oracle():
    report = check_first_jump(load_snapshot(), samples=256)
    assert all(engine["passed"] for engine in report["engines"].values())


@pytest.mark.parametrize("engine", [DirectSSA, OSAHRRunner])
def test_trace_replay_and_within_engine_reproducibility(engine):
    snapshot = load_snapshot()
    first = measure(snapshot, engine, 345, 30)
    second = measure(snapshot, engine, 345, 30)
    assert first["events"] == 30
    assert first["output_sha256"] == second["output_sha256"]
    assert first["simulation_time"] == second["simulation_time"]


def test_absorption_and_no_spurious_repair():
    snapshot = load_snapshot()
    snapshot = replace(snapshot, routes=tuple(replace(r, failure=0.0, repair=0.0) for r in snapshot.routes))
    assert transitions(snapshot, snapshot.initial) == {}
    assert DirectSSA(snapshot, 0).step() is None
    assert OSAHRRunner(snapshot, 0).step() is None
    assert check_generator(snapshot)["transitions"] == 0


def test_projection_rejects_duplicate_and_missing_relations():
    snapshot = load_snapshot()
    graph = compile_model(snapshot).graph
    edge = next(iter(graph.edges.values()))
    graph.remove_edge(edge.entity_id)
    with pytest.raises(ValueError, match="Availability"):
        project_state(graph, snapshot)
    graph = compile_model(snapshot).graph
    edge = next(iter(graph.edges.values()))
    graph.add_edge(edge.type_id, {i.role: (i.vertex_id,) for i in edge.tail},
                   {i.role: (i.vertex_id,) for i in edge.head})
    with pytest.raises(ValueError, match="Availability"):
        project_state(graph, snapshot)


def test_projection_rejects_changed_endpoints():
    snapshot = load_snapshot()
    graph = compile_model(snapshot).graph
    route = next(v for v in graph.vertices.values() if v.type_id == "Route")
    graph.set_vertex_attributes(route.entity_id, {"source": "urn:wrong"})
    with pytest.raises(ValueError, match="Static"):
        project_state(graph, snapshot)


def test_replication_preserves_route_laws():
    original = load_snapshot()
    scaled = replicate(original, 3)
    assert len(scaled.routes) == len(scaled.sites) == 9
    assert len({r.uri for r in scaled.routes}) == 9
    assert project_state(compile_model(scaled).graph, scaled) == scaled.initial
    expected_total = sum(transitions(original, original.initial).values())
    actual_total = sum(x.hazard for x in Runtime(compile_model(scaled), root_seed=0).enabled_occurrences())
    assert actual_total == pytest.approx(3 * expected_total)


@pytest.mark.parametrize("old,new", [
    ("ex:failureRate 0.2", "ex:failureRate -0.2"),
    ("ex:failureRate 0.2", 'ex:failureRate "NaN"^^<http://www.w3.org/2001/XMLSchema#double>'),
    ("ex:failureRate 0.2", 'ex:failureRate "0.2"'),
    ("ex:failureRate 0.2", "ex:failureRate true"),
    ("ex:failureRate 0.2", "ex:failureRate 0.2, 0.3"),
    ("ex:up true", 'ex:up "true"'),
    ("ex:source ex:A ; ex:target ex:B", "ex:source ex:A ; ex:target ex:A"),
    ("ex:source ex:A", "ex:source ex:Missing"),
    ("ex:repairRate 0.8", "ex:unknown 0.8"),
    ("ex:AB a ex:Route", "_:route a ex:Route"),
])
def test_bad_ontology_is_rejected(tmp_path, old, new):
    fixture = tmp_path / "bad.ttl"
    fixture.write_text(FIXTURE.read_text().replace(old, new, 1))
    with pytest.raises(ValueError):
        load_snapshot(fixture)


def test_report_has_raw_timings_and_provenance():
    result = run(copies=(1,), events=2, samples=128)
    assert result["claim_status"] == "development_probe_only"
    assert "osahr/runtime.py" in result["source"]["sha256"]
    assert result["correctness"]["passed"]
    row = result["measurements"][0]
    assert set(row["runs"]) == {"direct_ssa", "osahr"}
    assert all(len(values) == 3 for values in row["runs"].values())
    assert math.isfinite(row["osahr_over_baseline_total_ratio"])
    json.dumps(result, allow_nan=False)


def test_size_and_statistical_guardrails():
    snapshot = load_snapshot()
    with pytest.raises(ValueError):
        compile_model(snapshot, (True,))
    with pytest.raises(ValueError):
        replicate(snapshot, 0)
    with pytest.raises(ValueError):
        check_generator(replicate(snapshot, 3))
    with pytest.raises(ValueError):
        check_first_jump(snapshot, 1)
