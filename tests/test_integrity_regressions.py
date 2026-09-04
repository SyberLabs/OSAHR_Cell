from __future__ import annotations

import base64
import math
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

from osahr import (
    AdaptiveParameter,
    AttributeSpec,
    BoundaryDirection,
    BoundaryHandle,
    BoundaryState,
    Expr,
    EntityId,
    ExternalEvent,
    HyperedgeType,
    Hypergraph,
    InputMode,
    MetaRuleAction,
    MetaRuleEvent,
    Model,
    OutputSpec,
    PatternGraph,
    Rule,
    RuleTemplate,
    Runtime,
    RuntimeConfig,
    ScheduledAdaptation,
    SchedulerKind,
    Schema,
    StateAssignment,
    TemplateGraph,
    ValueKind,
    VertexType,
    compose_structural,
    load_checkpoint,
)
from osahr.canonical import stable_hash
from osahr.errors import (
    MetaRewriteError,
    PatternError,
    ReplayError,
    ResourceLimitError,
    ValidationError,
)


def _clock_model(*, model_id: str = "clock") -> Model:
    graph = Hypergraph(Schema([], [], schema_id="clock-schema"), namespace=11)
    tick = Rule(
        "tick",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("1.0"),
        adaptation=(StateAssignment("memory.count", Expr("z.count + 1")),),
    )
    return Model(graph, BoundaryState(), (tick,), {}, {"count": 0}, model_id=model_id)


def test_canonical_hash_is_type_unambiguous() -> None:
    class StringToken(str, Enum):
        VALUE = "value"

    @dataclass(frozen=True)
    class Record:
        value: int

    entity = EntityId(1, 2)
    collision_candidates = (
        (1.0, {"__float_hex__": 1.0.hex()}),
        (entity, {"__entity_id__": str(entity)}),
        ({entity: "value"}, {"__entity_id_map__": [[str(entity), "value"]]}),
        (StringToken.VALUE, "value"),
        (Record(1), {"value": 1}),
        ({1, 2}, [1, 2]),
        ((1, 2), [1, 2]),
        (True, 1),
    )
    for left, right in collision_candidates:
        assert stable_hash(left) != stable_hash(right)


def test_behavior_bearing_container_subclasses_are_not_authoritative_state() -> None:
    first = defaultdict(lambda: 1.0)
    second = defaultdict(lambda: 2.0)
    with pytest.raises(TypeError, match="plain dicts"):
        stable_hash(first)
    with pytest.raises(TypeError, match="plain dicts"):
        stable_hash(second)

    graph = Hypergraph(Schema([], []))
    with pytest.raises(ValidationError, match="non-canonical authoritative state"):
        Model(graph, BoundaryState(), (), memory={"d": first})
    assert not first
    assert not second


@pytest.mark.parametrize(
    "field_name",
    (
        "max_simulation_time",
        "max_total_activity",
        "explosion_window",
        "thinning_window",
    ),
)
def test_runtime_config_identity_preserves_large_integer_limits(
    field_name: str,
) -> None:
    lower = RuntimeConfig(**{field_name: 2**53})
    upper = RuntimeConfig(**{field_name: 2**53 + 1})
    assert stable_hash(lower.to_canonical()) != stable_hash(upper.to_canonical())

    model = _clock_model()
    assert Runtime(model, root_seed=1, config=lower).run_id != Runtime(
        model,
        root_seed=1,
        config=upper,
    ).run_id


@pytest.mark.parametrize("bad_time", [-1.0, math.inf, -math.inf, math.nan])
def test_scheduled_inputs_require_finite_nonnegative_time(bad_time: float) -> None:
    with pytest.raises(ValidationError):
        ExternalEvent(bad_time, "source", 0, "event", "input")
    with pytest.raises(ValidationError):
        ScheduledAdaptation(bad_time, 0, "update", ())


def test_meta_rule_events_reject_noncanonical_bindings() -> None:
    with pytest.raises(MetaRewriteError, match="canonical state"):
        MetaRuleEvent(
            0.0,
            0,
            "meta",
            MetaRuleAction.REMOVE,
            "rule",
            bindings={"blob": b"x"},
        )


def test_scheduled_assignment_literals_must_be_canonical_state() -> None:
    with pytest.raises(PatternError, match="canonical state"):
        StateAssignment("memory.blob", b"x")


def test_failed_graph_additions_do_not_consume_ids_and_allocator_is_hashed() -> None:
    schema = Schema(
        [VertexType("V", {"x": AttributeSpec(ValueKind.FLOAT, required=True)})],
        [
            HyperedgeType(
                "E",
                {},
                {},
                {"weight": AttributeSpec(ValueKind.FLOAT, required=True)},
            )
        ],
    )
    vertices = Hypergraph(schema, namespace=7)
    with pytest.raises(ValidationError):
        vertices.add_vertex("V", {"x": math.inf})
    assert vertices.add_vertex("V", {"x": 1.0}).entity_id.counter == 0

    edges = Hypergraph(schema, namespace=8)
    with pytest.raises(ValidationError):
        edges.add_edge("E", {}, {}, {"weight": math.nan})
    assert edges.add_edge("E", {}, {}, {"weight": 1.0}).entity_id.counter == 0

    different_namespace = Hypergraph(schema, namespace=9)
    assert Hypergraph(schema, namespace=8).state_hash != different_namespace.state_hash
    used_then_emptied = Hypergraph(schema, namespace=8)
    vertex = used_then_emptied.add_vertex("V", {"x": 1.0})
    used_then_emptied.remove_vertex(vertex.entity_id)
    assert used_then_emptied.state_hash != Hypergraph(schema, namespace=8).state_hash


def test_replace_preserves_omitted_immutable_attributes() -> None:
    schema = Schema(
        [
            VertexType(
                "V",
                {
                    "key": AttributeSpec(ValueKind.STRING, required=True, mutable=False),
                    "value": AttributeSpec(ValueKind.FLOAT, required=True),
                },
            )
        ],
        [
            HyperedgeType(
                "E",
                {},
                {},
                {
                    "key": AttributeSpec(ValueKind.STRING, required=True, mutable=False),
                    "value": AttributeSpec(ValueKind.FLOAT, required=True),
                },
            )
        ],
    )
    graph = Hypergraph(schema)
    vertex = graph.add_vertex("V", {"key": "vertex", "value": 1.0})
    edge = graph.add_edge("E", {}, {}, {"key": "edge", "value": 1.0})

    graph.set_vertex_attributes(vertex.entity_id, {"value": 2.0}, replace=True)
    graph.set_edge_attributes(edge.entity_id, {"value": 2.0}, replace=True)

    assert graph.vertices[vertex.entity_id].attributes == {"key": "vertex", "value": 2.0}
    assert graph.edges[edge.entity_id].attributes == {"key": "edge", "value": 2.0}
    with pytest.raises(ValidationError, match="immutable"):
        graph.set_vertex_attributes(
            vertex.entity_id, {"key": "changed", "value": 3.0}, replace=True
        )


@pytest.mark.parametrize(
    "scheduler",
    [
        SchedulerKind.DIRECT_SSA,
        SchedulerKind.NEXT_REACTION,
        SchedulerKind.THINNING,
    ],
)
def test_step_rolls_back_after_late_post_commit_failure(
    monkeypatch: pytest.MonkeyPatch, scheduler: SchedulerKind
) -> None:
    model = _clock_model()
    config = RuntimeConfig(scheduler=scheduler)
    runtime = Runtime(model, root_seed=41, config=config)
    initial = runtime.snapshot()
    control = Runtime.from_snapshot(model, initial)
    state_before = runtime.state_hash
    rng_before = runtime.random.snapshot()
    original_refresh = runtime._post_commit_refresh

    def fail_after_refresh(**kwargs: object) -> list[object]:
        original_refresh(**kwargs)
        raise RuntimeError("injected late failure")

    monkeypatch.setattr(runtime, "_post_commit_refresh", fail_after_refresh)
    with pytest.raises(RuntimeError, match="late failure"):
        runtime.step()

    assert runtime.state_hash == state_before
    assert runtime.random.snapshot() == rng_before
    assert runtime.event_index == 0
    assert runtime.event_log == []
    assert runtime.output_events == []
    monkeypatch.setattr(runtime, "_post_commit_refresh", original_refresh)
    assert runtime.step().event == control.step().event


def test_event_and_time_limits_are_checked_before_commit() -> None:
    model = _clock_model()
    runtime = Runtime(model, root_seed=9, config=RuntimeConfig(max_events=1))
    runtime.step()
    state_before = runtime.state_hash
    rng_before = runtime.random.snapshot()
    log_before = list(runtime.event_log)
    with pytest.raises(ResourceLimitError, match="Event limit"):
        runtime.step()
    assert runtime.state_hash == state_before
    assert runtime.random.snapshot() == rng_before
    assert runtime.event_log == log_before

    schema = Schema([VertexType("V", {})], [])
    graph = Hypergraph(schema)
    vertex = graph.add_vertex("V")
    boundary = BoundaryState(
        {
            "in": BoundaryHandle(
                "in",
                BoundaryDirection.INPUT,
                "V",
                binding=vertex.entity_id,
                input_mode=InputMode.SIGNAL_ONLY,
            )
        }
    )
    limited = Runtime(
        Model(graph, boundary, ()),
        root_seed=1,
        config=RuntimeConfig(max_simulation_time=1.0),
    )
    event = ExternalEvent(2.0, "source", 0, "late", "in")
    limited.inject(event)
    with pytest.raises(ResourceLimitError, match="Simulation-time"):
        limited.step()
    assert limited.time == 0.0
    assert limited.event_index == 0
    assert limited.external_queue == [event]

    unbounded = Runtime(model, root_seed=10)
    with pytest.raises(ValueError, match="finite"):
        unbounded.run_until_time(math.inf)
    assert unbounded.time == 0.0


def test_snapshot_verifies_model_config_and_preserves_explosion_history() -> None:
    model = _clock_model()
    config = RuntimeConfig(
        max_events=20,
        max_events_per_time_window=5,
        explosion_window=100.0,
        matcher_backend="reference",
    )
    runtime = Runtime(model, root_seed=22, config=config)
    runtime.run_events(2)
    snapshot = runtime.snapshot()
    restored = Runtime.from_snapshot(model, snapshot)

    assert restored.config == config
    assert tuple(restored._recent_event_times) == tuple(runtime._recent_event_times)
    assert restored.step().event == runtime.step().event

    with pytest.raises(ReplayError, match="model hash"):
        Runtime.from_snapshot(_clock_model(model_id="different"), snapshot)
    with pytest.raises(ReplayError, match="RuntimeConfig"):
        Runtime.from_snapshot(model, snapshot, config=RuntimeConfig(max_events=21))

    tampered = runtime.snapshot()
    tampered.config = RuntimeConfig(max_events=21)
    with pytest.raises(ReplayError, match="run identity"):
        Runtime.from_snapshot(model, tampered)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("max_events", 0),
        ("max_vertices", -1),
        ("max_edges", True),
        ("max_incidences", -1),
        ("max_matches_per_rule", 0),
        ("max_total_activity", math.nan),
        ("max_simulation_time", math.nan),
        ("max_events_per_time_window", 0),
        ("explosion_window", math.inf),
        ("incremental_verify", 1),
        ("thinning_window", 0.0),
        ("max_thinning_windows_per_plan", 0),
    ],
)
def test_runtime_config_rejects_invalid_resource_contracts(
    name: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        RuntimeConfig(**{name: value})


def test_runtime_config_identity_normalizes_equal_numeric_forms() -> None:
    model = _clock_model()
    integer_form = RuntimeConfig(
        max_total_activity=1,
        max_simulation_time=2,
        explosion_window=0,
        thinning_window=1,
    )
    float_form = RuntimeConfig(
        max_total_activity=1.0,
        max_simulation_time=2.0,
        explosion_window=0.0,
        thinning_window=1.0,
    )
    assert integer_form == float_form
    assert Runtime(model, root_seed=1, config=integer_form).run_id == Runtime(
        model,
        root_seed=1,
        config=float_form,
    ).run_id
    positive_zero = RuntimeConfig(
        max_total_activity=0.0,
        max_simulation_time=0.0,
        explosion_window=0.0,
    )
    negative_zero = RuntimeConfig(
        max_total_activity=-0.0,
        max_simulation_time=-0.0,
        explosion_window=-0.0,
    )
    assert positive_zero == negative_zero
    assert Runtime(model, root_seed=2, config=positive_zero).run_id == Runtime(
        model,
        root_seed=2,
        config=negative_zero,
    ).run_id


@pytest.mark.parametrize("root_seed", [True, -1, 1 << 128])
def test_runtime_rejects_invalid_root_seed(root_seed: object) -> None:
    with pytest.raises(ValueError, match="unsigned 128-bit"):
        Runtime(_clock_model(), root_seed=root_seed)


@pytest.mark.parametrize(
    "field_name,value,error",
    [
        ("time", math.nan, "time state"),
        ("last_event_time", 1.0, "time state"),
        ("event_index", -1, "event index"),
    ],
)
def test_snapshot_rejects_invalid_scalar_state(
    field_name: str,
    value: object,
    error: str,
) -> None:
    model = _clock_model()
    snapshot = Runtime(model, root_seed=2).snapshot()
    setattr(snapshot, field_name, value)
    with pytest.raises(ReplayError, match=error):
        Runtime.from_snapshot(model, snapshot)


def test_snapshot_rejects_corrupt_graph_indexes_and_rule_maps() -> None:
    schema = Schema([VertexType("V", {})], [])
    graph = Hypergraph(schema)
    vertex = graph.add_vertex("V")
    model = Model(graph, BoundaryState(), ())

    corrupt_graph = Runtime(model, root_seed=3).snapshot()
    corrupt_graph.graph.vertices_by_type["V"].remove(vertex.entity_id)
    with pytest.raises(ReplayError, match="authoritative state"):
        Runtime.from_snapshot(model, corrupt_graph)

    clock = _clock_model()
    corrupt_rules = Runtime(clock, root_seed=4).snapshot()
    corrupt_rules.rules["wrong-key"] = corrupt_rules.rules.pop("tick")
    with pytest.raises(ReplayError, match="rule map"):
        Runtime.from_snapshot(clock, corrupt_rules)


def test_direct_snapshot_rejects_scheduler_invariant_forgery() -> None:
    model = _clock_model()
    source = Runtime(model, root_seed=13)
    assert source.peek_next_event_time() is not None
    snapshot = source.snapshot()
    assert snapshot.pending_internal is not None
    snapshot.pending_internal.survival_integral_exact = False
    snapshot.pending_internal.survival_integral = 123.0
    snapshot.pending_internal.integrity_hash = (
        snapshot.pending_internal.calculate_integrity_hash()
    )
    snapshot.seal()

    with pytest.raises(ReplayError, match="direct-SSA scheduler state"):
        Runtime.from_snapshot(model, snapshot)


def test_restored_pending_plan_retains_private_integrity_binding() -> None:
    model = _clock_model()
    source = Runtime(model, root_seed=14)
    assert source.peek_next_event_time() is not None
    restored = Runtime.from_snapshot(model, source.snapshot())
    assert restored.pending_internal is not None
    restored.pending_internal.absolute_time = restored.time
    restored.pending_internal.integrity_hash = (
        restored.pending_internal.calculate_integrity_hash()
    )

    with pytest.raises(ReplayError, match="changed after planning"):
        restored.step()


def test_genuine_v1_checkpoint_migrates_as_audit_only(tmp_path: Path) -> None:
    model = _clock_model()
    config = RuntimeConfig(
        max_events_per_time_window=3,
        explosion_window=100.0,
    )
    path = tmp_path / "legacy.osahr.gz"
    fixture = Path(__file__).with_name("fixtures") / "genuine_v1_clock.osahr.gz.b64"
    path.write_bytes(base64.b64decode(fixture.read_text(encoding="ascii")))

    with pytest.raises(ValueError, match="legacy_model"):
        load_checkpoint(path)
    with pytest.raises(ValueError, match="legacy_config"):
        load_checkpoint(path, legacy_model=model)
    migrated = load_checkpoint(
        path,
        legacy_model=model,
        legacy_config=config,
    )
    assert migrated.recent_event_times == (migrated.last_event_time,)
    assert migrated.run_id == (
        "9b0f7fc44e45239cc801a82195c25e6681d71ed8ba7aa8c55b49004b38cb1107"
    )
    assert migrated.identity_version == 1
    assert migrated.continuation_allowed is False
    restored = Runtime.from_snapshot(model, migrated)
    assert restored.config == config
    assert restored.event_index == 1
    assert restored.memory == {"count": 1}
    assert restored.snapshot().run_id == migrated.run_id
    with pytest.raises(ReplayError, match="audit-only"):
        restored.step()


def test_queued_inputs_and_schema_attributes_do_not_alias_callers() -> None:
    schema = Schema(
        [VertexType("V", {"data": AttributeSpec(ValueKind.ANY, required=True)})],
        [],
    )
    source = {"items": [1]}
    graph = Hypergraph(schema)
    vertex = graph.add_vertex("V", {"data": source})
    source["items"].append(2)
    assert graph.vertices[vertex.entity_id].attributes["data"] == {"items": [1]}

    boundary = BoundaryState(
        {
            "in": BoundaryHandle(
                "in",
                BoundaryDirection.INPUT,
                "V",
                binding=vertex.entity_id,
                allow_payload_extensions=True,
                input_mode=InputMode.SIGNAL_ONLY,
            )
        }
    )
    runtime = Runtime(Model(graph, boundary, ()), root_seed=5)
    original_payload = {"nested": [1]}
    event = ExternalEvent(0.0, "source", 0, "event", "in", original_payload)
    runtime.inject(event)
    original_payload["nested"].append(2)
    event.payload["nested"].append(3)
    assert runtime.external_queue[0].payload == {"nested": [1]}

    assignment_value = {"nested": [1]}
    update = ScheduledAdaptation(
        0.0,
        0,
        "adaptation",
        (StateAssignment("memory.value", assignment_value),),
    )
    runtime.schedule_adaptation(update)
    assignment_value["nested"].append(2)
    update.assignments[0].value["nested"].append(3)
    assert runtime.adaptation_queue[0].assignments[0].value == {"nested": [1]}

    bindings = {"nested": [1]}
    meta = MetaRuleEvent(0.0, 0, "meta", MetaRuleAction.ENABLE, "missing", bindings=bindings)
    runtime.schedule_meta(meta)
    bindings["nested"].append(2)
    meta.bindings["nested"].append(3)
    assert runtime.meta_queue[0].bindings == {"nested": [1]}


def test_any_and_extension_attributes_reject_nested_nonfinite_values() -> None:
    any_schema = Schema(
        [VertexType("V", {"data": AttributeSpec(ValueKind.ANY, required=True)})],
        [],
    )
    with pytest.raises(ValidationError, match="finite canonical"):
        Hypergraph(any_schema).add_vertex("V", {"data": {"bad": math.nan}})

    extension_schema = Schema([VertexType("V", allow_extensions=True)], [])
    with pytest.raises(ValidationError, match="finite canonical"):
        Hypergraph(extension_schema).add_vertex("V", {"bad": [math.inf]})


@pytest.mark.parametrize(
    "value",
    [
        {object(): 1},
        {1: "integer", "1": "string"},
    ],
)
def test_any_attributes_reject_unstable_or_colliding_mapping_keys(value: dict) -> None:
    schema = Schema(
        [VertexType("V", {"data": AttributeSpec(ValueKind.ANY, required=True)})],
        [],
    )
    with pytest.raises(ValidationError, match="finite canonical"):
        Hypergraph(schema).add_vertex("V", {"data": value})

    valid = Hypergraph(schema)
    valid.add_vertex("V", {"data": {"stable": [1, 2]}})
    assert valid.clone().state_hash == valid.state_hash


def test_model_owns_mutable_inputs_and_runtime_rejects_later_model_mutation() -> None:
    schema = Schema([], [])
    parameters = {"nested": {"value": 1}}
    memory = {"items": [1]}
    model = Model(
        Hypergraph(schema),
        BoundaryState(),
        (),
        parameters,
        memory,
    )
    first = Runtime(model, root_seed=7)
    parameters["nested"]["value"] = 99
    memory["items"].append(2)
    second = Runtime(model, root_seed=7)

    assert first.parameters == second.parameters == {"nested": {"value": 1}}
    assert first.memory == second.memory == {"items": [1]}
    assert first.run_id == second.run_id

    model.memory["items"].append(3)
    with pytest.raises(ValidationError, match="Model hash is stale"):
        Runtime(model, root_seed=7)


def test_mutated_runtime_rule_template_is_rejected_before_instantiation() -> None:
    prototype = Rule(
        "prototype",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("1.0"),
        adaptation=(StateAssignment("memory.value", {"v": 1}),),
    )
    model = Model(
        Hypergraph(Schema([], [])),
        BoundaryState(),
        (),
        memory={},
        rule_templates=(RuleTemplate("template", prototype),),
    )
    runtime = Runtime(model, root_seed=18)
    runtime.rule_templates["template"].prototype.adaptation[0].value["v"] = 999
    runtime.schedule_meta(
        MetaRuleEvent(
            0.0,
            0,
            "instantiate",
            MetaRuleAction.INSTANTIATE,
            "instance",
            template_id="template",
        )
    )

    with pytest.raises(ReplayError, match="Rule template .* is stale"):
        runtime.step()
    assert runtime.rules == {}


def test_runtime_does_not_alias_model_schema_or_rule_definitions() -> None:
    schema = Schema(
        [VertexType("V", {"value": AttributeSpec(ValueKind.INT, required=True)})],
        [],
    )
    graph = Hypergraph(schema)
    graph.add_vertex("V", {"value": 1})
    rule = Rule(
        "rule",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("1.0"),
        meta={"nested": {"value": 1}},
    )
    model = Model(graph, BoundaryState(), (rule,))
    runtime = Runtime(model, root_seed=8)

    model.graph.schema.vertex_types["V"].attributes["extra"] = AttributeSpec(
        ValueKind.STRING
    )
    model.rules[0].meta["nested"]["value"] = 99

    assert "extra" not in runtime.graph.schema.vertex_types["V"].attributes
    assert runtime.rules["rule"].meta == {"nested": {"value": 1}}
    runtime.step()


def test_delta_replay_is_audit_only_even_after_resnapshot() -> None:
    model = _clock_model()
    source = Runtime(model, root_seed=30)
    initial = source.snapshot()
    source.run_events(1)
    replayed = Runtime.replay_deltas(model, initial, source.event_log)

    with pytest.raises(ReplayError, match="audit-only"):
        replayed.peek_next_event_time()
    with pytest.raises(ReplayError, match="audit-only"):
        replayed.step()
    with pytest.raises(ReplayError, match="audit-only"):
        replayed.run_until_time(replayed.time + 1.0)
    with pytest.raises(ReplayError, match="audit-only"):
        replayed.inject(ExternalEvent(replayed.time, "source", 0, "event", "missing"))

    restored_replay = Runtime.from_snapshot(model, replayed.snapshot())
    with pytest.raises(ReplayError, match="audit-only"):
        restored_replay.step()


def test_boundary_payload_contracts_are_hashed_and_enforced_on_output() -> None:
    schema = Schema([], [], schema_id="boundary-contract")
    graph = Hypergraph(schema)
    float_boundary = BoundaryState(
        {
            "out": BoundaryHandle(
                "out",
                BoundaryDirection.OUTPUT,
                "unused",
                nullable=True,
                payload_schema={"value": AttributeSpec(ValueKind.FLOAT, required=True)},
            )
        }
    )
    string_boundary = BoundaryState(
        {
            "out": BoundaryHandle(
                "out",
                BoundaryDirection.OUTPUT,
                "unused",
                nullable=True,
                payload_schema={"value": AttributeSpec(ValueKind.STRING, required=True)},
            )
        }
    )
    assert Model(graph.clone(), float_boundary, ()).hash != Model(
        graph.clone(), string_boundary, ()
    ).hash

    invalid_output = Rule(
        "emit-invalid",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("1.0"),
        outputs=(OutputSpec("out", "value", {"value": "not-a-float"}),),
    )
    runtime = Runtime(Model(graph, float_boundary, (invalid_output,)), root_seed=4)
    state_before = runtime.state_hash
    rng_before = runtime.random.snapshot()
    with pytest.raises(ValidationError, match="expected float"):
        runtime.step()
    assert runtime.state_hash == state_before
    assert runtime.random.snapshot() == rng_before
    assert runtime.output_events == []


def test_composition_rejects_state_it_cannot_preserve() -> None:
    schema = Schema([], [])
    adaptive = Model(
        Hypergraph(schema),
        BoundaryState(),
        (),
        {"p": 1.0},
        {},
        adaptive_parameters=(AdaptiveParameter("p"),),
    )
    prototype = Rule("prototype", PatternGraph(()), TemplateGraph(()), Expr("1.0"))
    templated = Model(
        Hypergraph(schema),
        BoundaryState(),
        (),
        rule_templates=(RuleTemplate("template", prototype),),
    )

    for model in (adaptive, templated):
        with pytest.raises(ValidationError, match="cannot preserve"):
            compose_structural({"component": model}, [])
