from __future__ import annotations

import pytest

from osahr import (
    AttributeSpec,
    BoundaryState,
    EntityId,
    Expr,
    Hypergraph,
    Match,
    Matcher,
    Model,
    PatternGraph,
    PatternVertex,
    Rule,
    Runtime,
    Schema,
    TemplateGraph,
    TemplateVertex,
    ValueKind,
    Var,
    VertexType,
)
from osahr.errors import MatchError, ReplayError
from osahr.rewrite import RewriteEngine


def _runtime() -> tuple[Runtime, EntityId, EntityId]:
    schema = Schema(
        [VertexType("V", {"value": AttributeSpec(ValueKind.INT, required=True)})],
        [],
    )
    graph = Hypergraph(schema)
    matching = graph.add_vertex("V", {"value": 0})
    nonmatching = graph.add_vertex("V", {"value": 99})
    rule = Rule(
        "rewrite",
        PatternGraph((PatternVertex("v", "V", {"value": 0}),)),
        TemplateGraph((TemplateVertex("v", "V", {"value": 1}),)),
        Expr("1.0"),
    )
    runtime = Runtime(Model(graph, BoundaryState(), (rule,)), root_seed=1)
    return runtime, matching.entity_id, nonmatching.entity_id


def test_mutated_pending_match_cannot_redirect_rewrite() -> None:
    runtime, matching_id, nonmatching_id = _runtime()
    assert runtime.peek_next_event_time() is not None
    assert runtime.pending_internal is not None
    match = runtime.pending_internal.occurrence.match
    match.vertex_map["v"] = nonmatching_id
    state_before = runtime.state_hash
    rng_before = runtime.random.snapshot()

    with pytest.raises(ReplayError, match="integrity"):
        runtime.step()

    assert runtime.state_hash == state_before
    assert runtime.random.snapshot() == rng_before
    assert runtime.graph.vertices[matching_id].attributes == {"value": 0}
    assert runtime.graph.vertices[nonmatching_id].attributes == {"value": 99}


def test_forged_match_with_self_consistent_id_is_rejected() -> None:
    runtime, _, nonmatching_id = _runtime()
    rule = runtime.rules["rewrite"]
    forged = Match.create(
        rule_id=rule.rule_id,
        vertex_map={"v": nonmatching_id},
        edge_map={},
        bindings={},
        graph_epoch=runtime.graph.epoch,
    )

    with pytest.raises(MatchError, match="authoritative"):
        RewriteEngine().apply(
            graph=runtime.graph,
            boundary=runtime.boundary,
            parameters=runtime.parameters,
            memory=runtime.memory,
            rule=rule,
            match=forged,
            time=runtime.time,
            delta_time=0.0,
            event_index=1,
            event_id="forged",
        )


def test_forged_binding_with_python_equal_wrong_type_is_rejected() -> None:
    schema = Schema(
        [VertexType("V", {"value": AttributeSpec(ValueKind.FLOAT, required=True)})],
        [],
    )
    graph = Hypergraph(schema)
    vertex = graph.add_vertex("V", {"value": 1.0})
    rule = Rule(
        "typed",
        PatternGraph((PatternVertex("v", "V", {"value": Var("bound")}),)),
        TemplateGraph((TemplateVertex("v", "V"),)),
        Expr("1.0"),
    )
    forged = Match.create(
        rule_id=rule.rule_id,
        vertex_map={"v": vertex.entity_id},
        edge_map={},
        bindings={"bound": 1},
        graph_epoch=graph.epoch,
    )

    with pytest.raises(MatchError, match="authoritative"):
        RewriteEngine().apply(
            graph=graph,
            boundary=BoundaryState(),
            parameters={},
            memory={},
            rule=rule,
            match=forged,
            time=0.0,
            delta_time=0.0,
            event_index=1,
            event_id="typed-forgery",
        )


def test_pending_rule_must_match_authoritative_runtime_rule() -> None:
    runtime, matching_id, _ = _runtime()
    assert runtime.peek_next_event_time() is not None
    original = runtime.rules["rewrite"]
    runtime.rules["rewrite"] = Rule(
        original.rule_id,
        original.left,
        TemplateGraph((TemplateVertex("v", "V", {"value": 2}),)),
        original.hazard,
    )

    with pytest.raises(ReplayError, match="not authoritative"):
        runtime.step()

    assert runtime.graph.vertices[matching_id].attributes == {"value": 0}


def test_nested_authoritative_rule_mutation_is_rejected_before_fire() -> None:
    runtime, matching_id, _ = _runtime()
    assert runtime.peek_next_event_time() is not None
    runtime.rules["rewrite"].right.vertices[0].attributes["value"] = 2

    with pytest.raises(ReplayError, match="not authoritative|rule map is stale"):
        runtime.step()

    assert runtime.graph.vertices[matching_id].attributes == {"value": 0}


def test_pending_plan_rejects_authoritative_state_drift() -> None:
    runtime, matching_id, _ = _runtime()
    runtime.parameters["rate"] = 1
    assert runtime.peek_next_event_time() is not None
    runtime.parameters["rate"] = 1000

    with pytest.raises(ReplayError, match="changed since planning"):
        runtime.step()

    assert runtime.graph.vertices[matching_id].attributes == {"value": 0}


def test_public_pending_rehash_cannot_replace_runtime_plan_fingerprint() -> None:
    runtime, matching_id, _ = _runtime()
    assert runtime.peek_next_event_time() is not None
    assert runtime.pending_internal is not None
    runtime.pending_internal.absolute_time = runtime.time
    runtime.pending_internal.integrity_hash = (
        runtime.pending_internal.calculate_integrity_hash()
    )

    with pytest.raises(ReplayError, match="changed after planning"):
        runtime.step()

    assert runtime.graph.vertices[matching_id].attributes == {"value": 0}


def test_repeated_variable_unification_is_type_sensitive() -> None:
    schema = Schema(
        [
            VertexType("Integer", {"value": AttributeSpec(ValueKind.INT, required=True)}),
            VertexType("Float", {"value": AttributeSpec(ValueKind.FLOAT, required=True)}),
        ],
        [],
    )
    graph = Hypergraph(schema)
    graph.add_vertex("Integer", {"value": 1})
    graph.add_vertex("Float", {"value": 1.0})
    rule = Rule(
        "typed-unification",
        PatternGraph(
            (
                PatternVertex("integer", "Integer", {"value": Var("shared")}),
                PatternVertex("float", "Float", {"value": Var("shared")}),
            )
        ),
        TemplateGraph(
            (
                TemplateVertex("integer", "Integer"),
                TemplateVertex("float", "Float"),
            )
        ),
        Expr("1.0"),
    )

    assert Matcher().find_rule_matches(
        graph,
        rule,
        parameters={},
        memory={},
        time=0.0,
    ) == []
