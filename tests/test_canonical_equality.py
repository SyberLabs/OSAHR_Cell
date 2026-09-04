from __future__ import annotations

import pytest

from osahr import (
    AdaptiveParameter,
    AdaptiveRegistry,
    AttributeSpec,
    BoundaryDirection,
    BoundaryHandle,
    BoundaryState,
    EdgeCount,
    EntityCount,
    Expr,
    ExternalEvent,
    HyperedgeType,
    Hypergraph,
    InputMode,
    MetaParameter,
    MetaValueKind,
    Model,
    PatternGraph,
    PatternVertex,
    Rule,
    Runtime,
    Schema,
    StateAssignment,
    TemplateGraph,
    TemplateVertex,
    ValueKind,
    VertexType,
    compose_structural,
)
from osahr.canonical import canonical_equal
from osahr.causal import EventFootprint
from osahr.errors import MetaRewriteError, ValidationError


def _attribute_schema(*, mutable: bool = True) -> Schema:
    return Schema(
        [
            VertexType(
                "V",
                {
                    "value": AttributeSpec(
                        ValueKind.ANY,
                        required=True,
                        mutable=mutable,
                    )
                },
            )
        ],
        [
            HyperedgeType(
                "E",
                {},
                {},
                {
                    "value": AttributeSpec(
                        ValueKind.ANY,
                        required=True,
                        mutable=mutable,
                    )
                },
            )
        ],
    )


def test_canonical_equality_does_not_coerce_types() -> None:
    assert canonical_equal({"value": 1}, {"value": 1})
    assert not canonical_equal({"value": 1}, {"value": 1.0})
    assert not canonical_equal(False, 0)
    assert not canonical_equal([1], (1,))


def test_type_only_external_update_has_a_delta_and_replays() -> None:
    graph = Hypergraph(_attribute_schema())
    vertex = graph.add_vertex("V", {"value": 1})
    boundary = BoundaryState(
        {
            "input": BoundaryHandle(
                "input",
                BoundaryDirection.INPUT,
                "V",
                binding=vertex.entity_id,
                payload_schema={"value": AttributeSpec(ValueKind.ANY)},
                input_mode=InputMode.MERGE_BOUND_VERTEX_ATTRIBUTES,
            )
        }
    )
    model = Model(graph, boundary, ())
    runtime = Runtime(model, root_seed=1)
    initial = runtime.snapshot()

    runtime.inject(
        ExternalEvent(0.0, "source", 0, "event", "input", {"value": 1.0})
    )
    record = runtime.step().event

    assert record is not None
    assert record.graph_delta.updated_vertices_before[vertex.entity_id] == {"value": 1}
    assert record.graph_delta.updated_vertices_after[vertex.entity_id] == {"value": 1.0}
    assert type(
        record.graph_delta.updated_vertices_before[vertex.entity_id]["value"]
    ) is int
    assert type(
        record.graph_delta.updated_vertices_after[vertex.entity_id]["value"]
    ) is float
    assert runtime.graph.epoch == initial.graph.epoch + 1
    replayed = Runtime.replay_deltas(model, initial, runtime.event_log)
    assert replayed.state_hash == runtime.state_hash


def test_type_only_internal_update_has_a_delta_and_replays() -> None:
    graph = Hypergraph(_attribute_schema())
    vertex = graph.add_vertex("V", {"value": 1})
    rule = Rule(
        "convert",
        PatternGraph((PatternVertex("v", "V", {"value": 1}),)),
        TemplateGraph((TemplateVertex("v", "V", {"value": 1.0}),)),
        Expr("1.0"),
    )
    model = Model(graph, BoundaryState(), (rule,))
    runtime = Runtime(model, root_seed=2)
    initial = runtime.snapshot()

    record = runtime.step().event

    assert record is not None
    assert vertex.entity_id in record.graph_delta.updated_vertices_before
    assert vertex.entity_id in record.graph_delta.updated_vertices_after
    assert type(
        record.graph_delta.updated_vertices_before[vertex.entity_id]["value"]
    ) is int
    assert type(
        record.graph_delta.updated_vertices_after[vertex.entity_id]["value"]
    ) is float
    replayed = Runtime.replay_deltas(model, initial, runtime.event_log)
    assert replayed.state_hash == runtime.state_hash


def test_immutable_attributes_reject_python_equal_type_changes() -> None:
    graph = Hypergraph(_attribute_schema(mutable=False))
    vertex = graph.add_vertex("V", {"value": 1})
    edge = graph.add_edge("E", {}, {}, {"value": 1})

    with pytest.raises(ValidationError, match="immutable"):
        graph.set_vertex_attributes(vertex.entity_id, {"value": 1.0})
    with pytest.raises(ValidationError, match="immutable"):
        graph.set_edge_attributes(edge.entity_id, {"value": 1.0})

    assert type(graph.vertices[vertex.entity_id].attributes["value"]) is int
    assert type(graph.edges[edge.entity_id].attributes["value"]) is int


def test_pattern_literals_are_type_sensitive() -> None:
    graph = Hypergraph(_attribute_schema())
    graph.add_vertex("V", {"value": 1.0})
    rule = Rule(
        "integer-only",
        PatternGraph((PatternVertex("v", "V", {"value": 1}),)),
        TemplateGraph((TemplateVertex("v", "V"),)),
        Expr("1.0"),
    )

    assert Runtime(Model(graph, BoundaryState(), (rule,)), root_seed=3).total_activity() == 0.0


def test_observable_attribute_filters_are_type_sensitive() -> None:
    graph = Hypergraph(_attribute_schema())
    graph.add_vertex("V", {"value": 1})
    graph.add_vertex("V", {"value": 1.0})
    graph.add_edge("E", {}, {}, {"value": 1})
    graph.add_edge("E", {}, {}, {"value": 1.0})

    assert EntityCount("integers", "V", {"value": 1}).evaluate(graph, {}, {}) == 1
    assert EdgeCount("integers", "E", {"value": 1}).evaluate(graph, {}, {}) == 1


def test_type_only_adaptation_refreshes_hazards_and_causal_paths() -> None:
    rule = Rule(
        "change-type",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("1.0 if z.flag is False else 7.0"),
        adaptation=(StateAssignment("memory.flag", Expr("0")),),
    )
    model = Model(
        Hypergraph(Schema([], [])),
        BoundaryState(),
        (rule,),
        memory={"flag": False},
    )
    runtime = Runtime(model, root_seed=4)
    assert runtime.total_activity() == 1.0

    record = runtime.step().event

    assert record is not None
    assert type(runtime.memory["flag"]) is int
    assert runtime.total_activity() == 7.0
    assert EventFootprint.from_record(record).written_state_paths == frozenset(
        {"memory.flag"}
    )
    registry = AdaptiveRegistry((AdaptiveParameter("flag"),))
    assert registry.changed_paths({"flag": False}, {"flag": 0}) == frozenset(
        {"flag"}
    )


def test_composition_rejects_python_equal_different_state_types() -> None:
    schema = Schema([], [])
    integer = Model(
        Hypergraph(schema),
        BoundaryState(),
        (),
        parameters={"value": 1},
    )
    floating = Model(
        Hypergraph(schema),
        BoundaryState(),
        (),
        parameters={"value": 1.0},
    )

    with pytest.raises(ValidationError, match="Conflicting parameter"):
        compose_structural({"integer": integer, "floating": floating}, [])


def test_schema_and_meta_choices_are_type_sensitive() -> None:
    attribute = AttributeSpec(ValueKind.ANY, choices=frozenset({1}))
    with pytest.raises(ValidationError, match="not one of"):
        attribute.validate("value", 1.0)

    parameter = MetaParameter(
        "value",
        MetaValueKind.INT,
        choices=(True,),
    )
    with pytest.raises(MetaRewriteError, match="must be one of"):
        parameter.validate(1)
