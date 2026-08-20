from __future__ import annotations

import math
from pathlib import Path

import pytest

from osahr import (
    ANY,
    AttributeSpec,
    BoundaryDirection,
    BoundaryHandle,
    BoundaryState,
    ConditionPolarity,
    EntityCount,
    Expr,
    ExternalEvent,
    GraphCondition,
    HyperedgeType,
    Hypergraph,
    InputMode,
    Matcher,
    Model,
    PatternEdge,
    PatternGraph,
    PatternVertex,
    PortSpec,
    Rule,
    Runtime,
    ScheduledAdaptation,
    Schema,
    StateAssignment,
    TemplateEdge,
    TemplateGraph,
    TemplateVertex,
    ValueKind,
    Var,
    VertexType,
    Wire,
    compose_structural,
    load_checkpoint,
    save_checkpoint,
)
from osahr.errors import PatternError, ReplayError, RewriteError, ValidationError


def make_schema() -> Schema:
    return Schema(
        [
            VertexType(
                "Agent",
                {
                    "active": AttributeSpec(ValueKind.BOOL, required=True),
                    "value": AttributeSpec(ValueKind.FLOAT, required=True),
                },
            ),
            VertexType(
                "SpecialAgent",
                {
                    "active": AttributeSpec(ValueKind.BOOL, required=True),
                    "value": AttributeSpec(ValueKind.FLOAT, required=True),
                },
                parents=frozenset({"Agent"}),
            ),
        ],
        [
            HyperedgeType(
                "Signal",
                {"source": PortSpec("source", "Agent")},
                {"target": PortSpec("target", "Agent")},
                {"weight": AttributeSpec(ValueKind.FLOAT, required=True, minimum=0.0)},
            ),
            HyperedgeType(
                "Link",
                {"members": PortSpec("members", "Agent", minimum=2, maximum=2, ordered=False)},
                {},
            ),
        ],
        schema_id="test",
    )


def make_signal_model(*, deletion_rule: bool = True) -> tuple[Model, object, object, object]:
    schema = make_schema()
    graph = Hypergraph(schema, namespace=7)
    sender = graph.add_vertex("Agent", {"active": True, "value": 2.0})
    receiver = graph.add_vertex("Agent", {"active": True, "value": 1.0})
    signal = graph.add_edge(
        "Signal",
        {"source": (sender.entity_id,)},
        {"target": (receiver.entity_id,)},
        {"weight": 0.5},
    )
    right_edges = () if deletion_rule else (
        TemplateEdge(
            "signal",
            "Signal",
            {"source": ("sender",)},
            {"target": ("receiver",)},
        ),
    )
    rule = Rule(
        "receive",
        PatternGraph(
            (
                PatternVertex("sender", "Agent"),
                PatternVertex("receiver", "Agent", {"value": Var("old")}),
            ),
            (
                PatternEdge(
                    "signal",
                    "Signal",
                    {"source": ("sender",)},
                    {"target": ("receiver",)},
                    {"weight": Var("w")},
                ),
            ),
        ),
        TemplateGraph(
            (
                TemplateVertex("sender", "Agent"),
                TemplateVertex("receiver", "Agent", {"value": Expr("old + p.gain * w")}),
            ),
            right_edges,
        ),
        Expr("p.rate * w"),
        adaptation=(StateAssignment("memory.count", Expr("z.count + 1")),),
    )
    model = Model(
        graph,
        BoundaryState(),
        (rule,),
        {"rate": 2.0, "gain": 4.0},
        {"count": 0},
        model_id="signal",
    )
    return model, sender, receiver, signal


def test_schema_and_unordered_hyperedge() -> None:
    schema = make_schema()
    graph = Hypergraph(schema)
    a = graph.add_vertex("Agent", {"active": True, "value": 0.0})
    b = graph.add_vertex("SpecialAgent", {"active": True, "value": 1.0})
    graph.add_edge("Link", {"members": (a.entity_id, b.entity_id)}, {}, {})
    graph.validate()

    pattern = PatternGraph(
        (PatternVertex("x", "Agent"), PatternVertex("y", "Agent")),
        (PatternEdge("l", "Link", {"members": ("y", "x")}, {}),),
    )
    matches = Matcher().find_pattern_matches(graph, pattern)
    assert len(matches) == 2  # embedding semantics over symmetric vertex roles


def test_variable_binding_and_rewrite() -> None:
    model, _sender, receiver, signal = make_signal_model()
    runtime = Runtime(model, root_seed=123)
    occurrence = runtime.enabled_occurrences()[0]
    assert occurrence.hazard == pytest.approx(1.0)
    result = runtime.step()
    assert result.event is not None
    assert signal.entity_id not in runtime.graph.edges
    assert runtime.graph.vertices[receiver.entity_id].attributes["value"] == pytest.approx(3.0)
    assert runtime.memory["count"] == 1
    assert result.event.pre_state_hash != result.event.post_state_hash


def test_dpo_dangling_condition() -> None:
    schema = make_schema()
    graph = Hypergraph(schema)
    a = graph.add_vertex("Agent", {"active": True, "value": 0.0})
    b = graph.add_vertex("Agent", {"active": True, "value": 0.0})
    graph.add_edge("Signal", {"source": (a.entity_id,)}, {"target": (b.entity_id,)}, {"weight": 1.0})
    rule = Rule(
        "bad-delete",
        PatternGraph((PatternVertex("a", "Agent"),)),
        TemplateGraph(()),
        Expr("1.0"),
    )
    model = Model(graph, BoundaryState(), (rule,))
    runtime = Runtime(model, root_seed=1)
    match = next(m for m in runtime.matcher.find_rule_matches(
        runtime.graph, rule, parameters={}, memory={}, time=0.0
    ) if m.vertex_map["a"] == a.entity_id)
    with pytest.raises(RewriteError):
        runtime.rewrite_engine.apply(
            graph=runtime.graph,
            boundary=runtime.boundary,
            parameters=runtime.parameters,
            memory=runtime.memory,
            rule=rule,
            match=match,
            time=0.1,
            delta_time=0.1,
            event_index=1,
            event_id="x",
        )


def test_negative_application_condition() -> None:
    schema = make_schema()
    graph = Hypergraph(schema)
    a = graph.add_vertex("Agent", {"active": True, "value": 0.0})
    b = graph.add_vertex("Agent", {"active": True, "value": 0.0})
    graph.add_edge("Signal", {"source": (a.entity_id,)}, {"target": (b.entity_id,)}, {"weight": 1.0})

    nac = GraphCondition(
        PatternGraph(
            (PatternVertex("x", "Agent"), PatternVertex("other", "Agent")),
            (PatternEdge("s", "Signal", {"source": ("x",)}, {"target": ("other",)}),),
        ),
        ConditionPolarity.NEGATIVE,
        shared_vertices={"x": "x"},
    )
    rule = Rule(
        "isolated-only",
        PatternGraph((PatternVertex("x", "Agent"),)),
        TemplateGraph((TemplateVertex("x", "Agent"),)),
        Expr("1.0"),
        conditions=(nac,),
    )
    matches = Matcher().find_rule_matches(graph, rule, parameters={}, memory={}, time=0.0)
    assert [match.vertex_map["x"] for match in matches] == [b.entity_id]


def test_replay_deltas_exact() -> None:
    model, *_ = make_signal_model()
    runtime = Runtime(model, root_seed=9)
    initial = runtime.snapshot()
    runtime.run_events(1)
    replayed = Runtime.replay_deltas(model, initial, runtime.event_log)
    assert replayed.state_hash == runtime.state_hash
    assert replayed.graph.state_hash == runtime.graph.state_hash


def test_checkpoint_roundtrip(tmp_path: Path) -> None:
    model, *_ = make_signal_model()
    runtime = Runtime(model, root_seed=5)
    runtime.peek_next_event_time()
    path = tmp_path / "checkpoint.osahr.gz"
    digest = save_checkpoint(path, runtime.snapshot())
    loaded = load_checkpoint(path)
    assert digest
    restored = Runtime.from_snapshot(model, loaded)
    assert restored.state_hash == runtime.state_hash
    assert restored.peek_next_event_time() == runtime.peek_next_event_time()


def test_external_event_preempts_and_discards_draws() -> None:
    model, _sender, receiver, _signal = make_signal_model(deletion_rule=False)
    boundary = BoundaryState(
        {
            "in": BoundaryHandle(
                "in",
                BoundaryDirection.INPUT,
                "Agent",
                binding=receiver.entity_id,
                payload_schema={"value": AttributeSpec(ValueKind.FLOAT, required=True)},
                input_mode=InputMode.MERGE_BOUND_VERTEX_ATTRIBUTES,
            )
        }
    )
    model = Model(model.graph, boundary, model.rules, model.parameters, model.memory)
    runtime = Runtime(model, root_seed=22)
    runtime.inject(ExternalEvent(0.0, "test", 1, "e1", "in", {"value": 10.0}))
    result = runtime.step()
    assert result.event is not None
    assert result.event.kind.value == "external_input"
    assert all(draw.discarded for draw in result.event.random_draws)
    assert runtime.graph.vertices[receiver.entity_id].attributes["value"] == 10.0


def test_run_until_time_retains_pending_internal_event() -> None:
    model, *_ = make_signal_model()
    runtime = Runtime(model, root_seed=333)
    proposed = runtime.peek_next_event_time()
    assert proposed is not None and proposed > 0
    runtime.run_until_time(proposed / 2)
    assert runtime.time == pytest.approx(proposed / 2)
    assert runtime.peek_next_event_time() == proposed
    runtime.run_until_time(proposed)
    assert runtime.event_index == 1
    assert runtime.time == pytest.approx(proposed)


def test_scheduled_adaptation_preempts_internal() -> None:
    model, *_ = make_signal_model(deletion_rule=False)
    runtime = Runtime(model, root_seed=77)
    runtime.schedule_adaptation(
        ScheduledAdaptation(
            0.0,
            1,
            "rate-zero",
            (StateAssignment("parameters.rate", Expr("0.0")),),
        )
    )
    result = runtime.step()
    assert result.event is not None
    assert runtime.parameters["rate"] == 0.0
    assert all(draw.discarded for draw in result.event.random_draws)
    assert runtime.step().status.value == "absorbed"


def test_hazard_cannot_depend_continuously_on_time() -> None:
    with pytest.raises(PatternError):
        Rule(
            "bad-time",
            PatternGraph(()),
            TemplateGraph(()),
            Expr("1.0 + time"),
        )


def test_structural_composition_identifies_wired_vertices() -> None:
    schema = make_schema()

    ga = Hypergraph(schema, namespace=1)
    va = ga.add_vertex("Agent", {"active": True, "value": 1.0})
    ba = BoundaryState({
        "out": BoundaryHandle("out", BoundaryDirection.OUTPUT, "Agent", binding=va.entity_id)
    })
    ma = Model(ga, ba, (), model_id="a")

    gb = Hypergraph(schema, namespace=2)
    vb = gb.add_vertex("Agent", {"active": True, "value": 1.0})
    bb = BoundaryState({
        "in": BoundaryHandle("in", BoundaryDirection.INPUT, "Agent", binding=vb.entity_id)
    })
    mb = Model(gb, bb, (), model_id="b")

    result = compose_structural(
        {"a": ma, "b": mb},
        [Wire("a", "out", "b", "in")],
    )
    assert len(result.model.graph.vertices) == 1
    assert not result.model.boundary.handles


def test_observable() -> None:
    model, *_ = make_signal_model()
    runtime = Runtime(model, root_seed=1)
    runtime.register_observable(EntityCount("agents", "Agent"))
    assert runtime.observe("agents") == 2


def test_event_log_replays_after_observation_horizon() -> None:
    model, *_ = make_signal_model()
    runtime = Runtime(model, root_seed=444)
    initial = runtime.snapshot()
    event_time = runtime.peek_next_event_time()
    assert event_time is not None
    runtime.run_until_time(event_time / 2.0)
    runtime.run_until_time(event_time)
    replayed = Runtime.replay_deltas(model, initial, runtime.event_log)
    assert replayed.state_hash == runtime.state_hash


def test_boundary_rebind_and_output_are_atomic() -> None:
    from osahr import BoundaryEffect, BoundaryEffectKind, OutputSpec

    schema = Schema(
        [VertexType("Agent", {"value": AttributeSpec(ValueKind.FLOAT, required=True)})],
        [],
    )
    graph = Hypergraph(schema)
    old = graph.add_vertex("Agent", {"value": 2.0})
    boundary = BoundaryState({
        "out": BoundaryHandle(
            "out", BoundaryDirection.OUTPUT, "Agent", binding=old.entity_id
        )
    })
    rule = Rule(
        "replace",
        PatternGraph((PatternVertex("old", "Agent", {"value": Var("x")}),)),
        TemplateGraph((TemplateVertex("new", "Agent", {"value": Expr("x + 1")}),)),
        Expr("1.0"),
        boundary_effects=(
            BoundaryEffect(BoundaryEffectKind.REBIND, "out", "new"),
        ),
        outputs=(
            OutputSpec("out", "replacement", {"value": Expr("v.new.value")}),
        ),
    )
    runtime = Runtime(Model(graph, boundary, (rule,)), root_seed=8)
    event = runtime.step().event
    assert event is not None
    assert old.entity_id not in runtime.graph.vertices
    new_id = runtime.boundary.handles["out"].binding
    assert new_id is not None
    assert runtime.graph.vertices[new_id].attributes["value"] == 3.0
    assert event.outputs[0].payload == {"value": 3.0}


def test_safe_schema_invariant_is_hashed_and_enforced() -> None:
    schema = Schema(
        [
            VertexType(
                "Probability",
                {"value": AttributeSpec(ValueKind.FLOAT, required=True)},
                invariants=(Expr("0.0 <= value <= 1.0"),),
            )
        ],
        [],
    )
    graph = Hypergraph(schema)
    graph.add_vertex("Probability", {"value": 0.5})
    with pytest.raises(ValidationError):
        graph.add_vertex("Probability", {"value": 2.0})


def test_causal_trace_links_repeated_writes() -> None:
    from osahr import CausalTrace

    model, *_ = make_signal_model(deletion_rule=False)
    runtime = Runtime(model, root_seed=101)
    runtime.run_events(2)
    trace = CausalTrace.from_records(runtime.event_log)
    first, second = runtime.event_log
    assert first.event_id in trace.predecessors[second.event_id]
    assert trace.ancestors(second.event_id) == [first.event_id]
