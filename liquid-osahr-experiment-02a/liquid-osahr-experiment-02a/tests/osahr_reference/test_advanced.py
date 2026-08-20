from __future__ import annotations

import math
import statistics

import pytest

from osahr import (
    AdaptiveParameter,
    BoundaryState,
    ConstraintPolicy,
    Expr,
    HyperedgeType,
    Hypergraph,
    MetaParameter,
    MetaRuleAction,
    MetaRuleEvent,
    MetaValueKind,
    Model,
    ParameterConstraint,
    PatternEdge,
    PatternGraph,
    PatternVertex,
    PortSpec,
    Rule,
    RuleTemplate,
    Runtime,
    RuntimeConfig,
    ScheduledAdaptation,
    SchedulerKind,
    Schema,
    StateAssignment,
    TemplateGraph,
    TemplateVertex,
    ValueKind,
    Var,
    VertexType,
    AttributeSpec,
    path_log_likelihood,
    run_ensemble,
)
from osahr.errors import AdaptationError, HazardBoundError


def agent_schema() -> Schema:
    return Schema(
        [VertexType("Agent", {"x": AttributeSpec(ValueKind.FLOAT, required=True)})],
        [
            HyperedgeType(
                "Link",
                {"source": PortSpec("source", "Agent")},
                {"target": PortSpec("target", "Agent")},
            )
        ],
        schema_id="advanced-agent",
    )


def two_channel_model() -> Model:
    schema = Schema([], [])
    graph = Hypergraph(schema)
    a = Rule(
        "a",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("p.a"),
        adaptation=(StateAssignment("memory.last", "a"),),
    )
    b = Rule(
        "b",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("p.b"),
        adaptation=(StateAssignment("memory.last", "b"),),
    )
    return Model(graph, BoundaryState(), (a, b), {"a": 1.0, "b": 3.0}, {"last": None})


def test_dpo_invalid_matches_do_not_enter_stochastic_activity() -> None:
    schema = agent_schema()
    graph = Hypergraph(schema)
    a = graph.add_vertex("Agent", {"x": 0.0})
    b = graph.add_vertex("Agent", {"x": 0.0})
    isolated = graph.add_vertex("Agent", {"x": 0.0})
    graph.add_edge("Link", {"source": (a.entity_id,)}, {"target": (b.entity_id,)})
    delete = Rule(
        "delete",
        PatternGraph((PatternVertex("x", "Agent"),)),
        TemplateGraph(()),
        Expr("1.0"),
    )
    runtime = Runtime(Model(graph, BoundaryState(), (delete,)), root_seed=1)
    matches = runtime.enabled_occurrences()
    assert len(matches) == 1
    assert matches[0].match.vertex_map["x"] == isolated.entity_id
    assert runtime.total_activity() == pytest.approx(1.0)


def test_incremental_dpo_reenable_after_incident_edge_deletion() -> None:
    schema = agent_schema()
    graph = Hypergraph(schema)
    a = graph.add_vertex("Agent", {"x": 0.0})
    b = graph.add_vertex("Agent", {"x": 0.0})
    graph.add_edge("Link", {"source": (a.entity_id,)}, {"target": (b.entity_id,)})
    remove_link = Rule(
        "remove-link",
        PatternGraph(
            (PatternVertex("a", "Agent"), PatternVertex("b", "Agent")),
            (PatternEdge("link", "Link", {"source": ("a",)}, {"target": ("b",)}),),
        ),
        TemplateGraph((TemplateVertex("a", "Agent"), TemplateVertex("b", "Agent"))),
        Expr("1.0"),
    )
    delete_agent = Rule(
        "delete-agent",
        PatternGraph((PatternVertex("x", "Agent"),)),
        TemplateGraph(()),
        Expr("1.0"),
    )
    runtime = Runtime(
        Model(graph, BoundaryState(), (remove_link, delete_agent)),
        root_seed=3,
        config=RuntimeConfig(incremental_verify=True),
    )
    assert [x.rule.rule_id for x in runtime.enabled_occurrences()] == ["remove-link"]
    runtime.step()
    enabled = runtime.enabled_occurrences()
    assert len(enabled) == 2
    assert {x.match.vertex_map["x"] for x in enabled} == {a.entity_id, b.entity_id}
    assert runtime.occurrence_index.incremental.localized_recomputations >= 1


def test_next_reaction_has_correct_competing_frequency_and_wait_mean() -> None:
    model = two_channel_model()
    waits: list[float] = []
    b_count = 0
    samples = 1200
    config = RuntimeConfig(scheduler=SchedulerKind.NEXT_REACTION)
    for seed in range(samples):
        runtime = Runtime(model, root_seed=seed, config=config)
        event = runtime.step().event
        assert event is not None
        waits.append(event.delta_time)
        b_count += runtime.memory["last"] == "b"
    assert abs(statistics.fmean(waits) - 0.25) < 0.025
    assert 0.70 < b_count / samples < 0.80


def test_next_reaction_noop_preemption_preserves_planned_clock() -> None:
    model = two_channel_model()
    config = RuntimeConfig(scheduler=SchedulerKind.NEXT_REACTION)
    runtime = Runtime(model, root_seed=42, config=config)
    proposed = runtime.peek_next_event_time()
    assert proposed is not None and proposed > 0.0
    runtime.schedule_adaptation(
        ScheduledAdaptation(
            proposed / 2.0,
            1,
            "noop",
            (StateAssignment("memory.last", Expr("z.last")),),
        )
    )
    first = runtime.step()
    assert first.event is not None
    assert first.event.kind.value == "scheduled_adaptation"
    assert runtime.peek_next_event_time() == pytest.approx(proposed)


def time_varying_model(*, bound: str = "1.0 + horizon") -> Model:
    schema = Schema([], [])
    graph = Hypergraph(schema)
    rule = Rule(
        "clock",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("1.0 + time"),
        hazard_upper_bound=Expr(bound),
    )
    return Model(graph, BoundaryState(), (rule,))


def test_thinning_matches_analytic_integrated_hazard_distribution() -> None:
    model = time_varying_model()
    config = RuntimeConfig(scheduler=SchedulerKind.THINNING, thinning_window=0.5)
    transformed: list[float] = []
    for seed in range(900):
        runtime = Runtime(model, root_seed=seed, config=config)
        event = runtime.step().event
        assert event is not None
        t = event.post_time
        # Lambda(t)=1+t => cumulative hazard Lambda_0^t = t+t^2/2.
        transformed.append(t + 0.5 * t * t)
    assert abs(statistics.fmean(transformed) - 1.0) < 0.07


def test_thinning_rejects_invalid_declared_bound() -> None:
    runtime = Runtime(
        time_varying_model(bound="0.5"),
        root_seed=1,
        config=RuntimeConfig(scheduler=SchedulerKind.THINNING),
    )
    with pytest.raises(HazardBoundError):
        runtime.step()


def test_strict_adaptive_constraint_rolls_back_event() -> None:
    schema = Schema([], [])
    graph = Hypergraph(schema)
    rule = Rule(
        "bad-learning",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("1.0"),
        adaptation=(StateAssignment("parameters.rate", -1.0),),
    )
    model = Model(
        graph,
        BoundaryState(),
        (rule,),
        {"rate": 1.0},
        {},
        adaptive_parameters=(
            AdaptiveParameter("rate", constraint=ParameterConstraint.POSITIVE),
        ),
    )
    runtime = Runtime(model, root_seed=1)
    before = runtime.state_hash
    with pytest.raises(AdaptationError):
        runtime.step()
    assert runtime.state_hash == before
    assert runtime.event_index == 0
    assert runtime.parameters["rate"] == 1.0


def test_projecting_adaptive_constraint_is_explicit_semantics() -> None:
    schema = Schema([], [])
    graph = Hypergraph(schema)
    rule = Rule(
        "learn",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("1.0"),
        adaptation=(StateAssignment("parameters.p", 2.0),),
    )
    model = Model(
        graph,
        BoundaryState(),
        (rule,),
        {"p": 0.5},
        {},
        adaptive_parameters=(
            AdaptiveParameter(
                "p",
                constraint=ParameterConstraint.PROBABILITY,
                policy=ConstraintPolicy.PROJECT,
            ),
        ),
    )
    runtime = Runtime(model, root_seed=2)
    runtime.step()
    assert runtime.parameters["p"] == 1.0


def test_path_likelihood_uses_exact_survival_integrals() -> None:
    runtime = Runtime(two_channel_model(), root_seed=11)
    records = runtime.run_events(5)
    result = path_log_likelihood(records)
    manual_log_hazard = sum(math.log(float(r.cause["hazard"])) for r in records)
    manual_integral = sum(float(r.cause["survival_integral"]) for r in records)
    assert result.log_hazard_sum == pytest.approx(manual_log_hazard)
    assert result.integrated_activity == pytest.approx(manual_integral)
    assert result.log_likelihood == pytest.approx(manual_log_hazard - manual_integral)


def test_ensemble_seed_partition_is_reproducible() -> None:
    model = two_channel_model()
    a = run_ensemble(
        model,
        replicates=16,
        root_seed=1234,
        event_count=3,
        observations={"last_b": lambda r: 1.0 if r.memory["last"] == "b" else 0.0},
    )
    b = run_ensemble(
        model,
        replicates=16,
        root_seed=1234,
        event_count=3,
        observations={"last_b": lambda r: 1.0 if r.memory["last"] == "b" else 0.0},
    )
    assert a.samples == b.samples
    assert 0.0 <= a.summary("last_b")["mean"] <= 1.0


def test_safe_meta_rule_template_changes_transition_repertoire() -> None:
    schema = Schema([], [])
    graph = Hypergraph(schema)
    prototype = Rule(
        "prototype",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("meta.rate"),
        adaptation=(StateAssignment("memory.last", Expr("meta.label")),),
    )
    template = RuleTemplate(
        "spawnable",
        prototype,
        (
            MetaParameter("rate", MetaValueKind.FLOAT, lower=0.0),
            MetaParameter("label", MetaValueKind.STRING),
        ),
    )
    model = Model(
        graph,
        BoundaryState(),
        (),
        {},
        {"last": None},
        rule_templates=(template,),
    )
    runtime = Runtime(model, root_seed=7)
    initial_hash = runtime.state_hash
    runtime.schedule_meta(
        MetaRuleEvent(
            0.0,
            1,
            "install-1",
            MetaRuleAction.INSTANTIATE,
            "learned-rule",
            "spawnable",
            {"rate": 2.0, "label": "born"},
        )
    )
    meta_record = runtime.step().event
    assert meta_record is not None and meta_record.kind.value == "meta_rule_update"
    assert runtime.state_hash != initial_hash
    assert "learned-rule" in runtime.rules
    runtime.step()
    assert runtime.memory["last"] == "born"

    runtime.schedule_meta(
        MetaRuleEvent(
            runtime.time,
            2,
            "disable-1",
            MetaRuleAction.DISABLE,
            "learned-rule",
        )
    )
    runtime.step()
    assert not runtime.rules["learned-rule"].enabled
    assert runtime.step().status.value == "absorbed"


def test_next_reaction_snapshot_preserves_internal_clocks() -> None:
    model = two_channel_model()
    config = RuntimeConfig(scheduler=SchedulerKind.NEXT_REACTION)
    runtime = Runtime(model, root_seed=123, config=config)
    proposed = runtime.peek_next_event_time()
    assert proposed is not None
    restored = Runtime.from_snapshot(model, runtime.snapshot(), config=config)
    assert restored.peek_next_event_time() == pytest.approx(proposed)


def test_meta_delta_replay_preserves_dynamic_rule_state_hash() -> None:
    schema = Schema([], [])
    graph = Hypergraph(schema)
    prototype = Rule("p", PatternGraph(()), TemplateGraph(()), Expr("meta.rate"))
    template = RuleTemplate(
        "t",
        prototype,
        (MetaParameter("rate", MetaValueKind.FLOAT, lower=0.0),),
    )
    model = Model(graph, BoundaryState(), (), rule_templates=(template,))
    runtime = Runtime(model, root_seed=5)
    initial = runtime.snapshot()
    runtime.schedule_meta(
        MetaRuleEvent(0.0, 1, "m", MetaRuleAction.INSTANTIATE, "r", "t", {"rate": 1.0})
    )
    runtime.step()
    replayed = Runtime.replay_deltas(model, initial, runtime.event_log)
    assert replayed.state_hash == runtime.state_hash
    assert replayed.rules["r"].hash == runtime.rules["r"].hash


def time_varying_integrable_model() -> Model:
    schema = Schema([], [])
    graph = Hypergraph(schema)
    rule = Rule(
        "clock-integrable",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("1.0 + time"),
        hazard_upper_bound=Expr("1.0 + horizon"),
        hazard_integral=Expr(
            "(horizon - time) + 0.5 * (horizon * horizon - time * time)"
        ),
    )
    return Model(graph, BoundaryState(), (rule,))


def test_thinning_integral_contract_produces_exact_path_likelihood() -> None:
    runtime = Runtime(
        time_varying_integrable_model(),
        root_seed=91,
        config=RuntimeConfig(scheduler=SchedulerKind.THINNING, thinning_window=0.25),
    )
    record = runtime.step().event
    assert record is not None
    t = record.post_time
    expected = t + 0.5 * t * t
    assert record.cause["survival_integral_exact"] is True
    assert record.cause["survival_integral"] == pytest.approx(expected)
    likelihood = path_log_likelihood([record])
    assert likelihood.integrated_activity == pytest.approx(expected)
    assert likelihood.log_likelihood == pytest.approx(math.log(1.0 + t) - expected)


def test_thinning_peek_is_observational_and_can_be_preempted_afterward() -> None:
    runtime = Runtime(
        time_varying_integrable_model(),
        root_seed=92,
        config=RuntimeConfig(scheduler=SchedulerKind.THINNING, thinning_window=0.25),
    )
    proposed = runtime.peek_next_event_time()
    assert proposed is not None and proposed > 0.0
    assert runtime.time == 0.0
    preempt = proposed / 2.0
    runtime.schedule_adaptation(
        ScheduledAdaptation(preempt, 1, "noop-thinning", ())
    )
    result = runtime.step()
    assert result.event is not None
    assert result.event.kind.value == "scheduled_adaptation"
    expected = preempt + 0.5 * preempt * preempt
    assert result.event.cause["survival_integral"] == pytest.approx(expected)
    assert result.event.cause["survival_integral_exact"] is True
    assert any(draw.discarded for draw in result.event.random_draws)


def test_scheduling_only_names_are_rejected_inside_hazard() -> None:
    with pytest.raises(Exception):
        Rule(
            "invalid-horizon-hazard",
            PatternGraph(()),
            TemplateGraph(()),
            Expr("1.0 + horizon"),
            hazard_upper_bound=Expr("1.0 + horizon"),
        )


def subtype_schema() -> Schema:
    return Schema(
        [
            VertexType("Agent", {}),
            VertexType("SpecialAgent", {}, parents=("Agent",)),
        ],
        [
            HyperedgeType(
                "Blocker",
                {"source": PortSpec("source", "Agent")},
                {"target": PortSpec("target", "Agent")},
            )
        ],
        schema_id="subtype-incremental",
    )


def test_incremental_dependency_relevance_respects_subtyping() -> None:
    schema = subtype_schema()
    graph = Hypergraph(schema)
    a = graph.add_vertex("SpecialAgent", {})
    b = graph.add_vertex("SpecialAgent", {})
    delete = Rule(
        "delete-supertype",
        PatternGraph((PatternVertex("x", "Agent", allow_subtypes=True),)),
        TemplateGraph(()),
        Expr("1.0"),
    )
    remove_blocker = Rule(
        "remove-blocker",
        PatternGraph(
            (
                PatternVertex("a", "Agent", allow_subtypes=True),
                PatternVertex("b", "Agent", allow_subtypes=True),
            ),
            (PatternEdge("block", "Blocker", {"source": ("a",)}, {"target": ("b",)}),),
        ),
        TemplateGraph(
            (
                TemplateVertex("a", "Agent"),
                TemplateVertex("b", "Agent"),
            )
        ),
        Expr("1.0"),
    )
    graph.add_edge("Blocker", {"source": (a.entity_id,)}, {"target": (b.entity_id,)})
    runtime = Runtime(
        Model(graph, BoundaryState(), (remove_blocker, delete)),
        root_seed=15,
        config=RuntimeConfig(incremental_verify=True),
    )
    assert [item.rule.rule_id for item in runtime.enabled_occurrences()] == ["remove-blocker"]
    runtime.step()
    assert {item.match.vertex_map["x"] for item in runtime.enabled_occurrences()} == {
        a.entity_id,
        b.entity_id,
    }


def test_reference_and_incremental_backends_are_eventwise_identical() -> None:
    schema = Schema(
        [VertexType("Agent", {"x": AttributeSpec(ValueKind.FLOAT, required=True)})],
        [],
        schema_id="differential-runtime",
    )
    graph = Hypergraph(schema)
    for i in range(8):
        graph.add_vertex("Agent", {"x": float(i)})
    left = PatternGraph((PatternVertex("a", "Agent", {"x": Var("x")}),))
    right = TemplateGraph(
        (TemplateVertex("a", "Agent", {"x": Expr("x + 1.0")}),)
    )
    rule = Rule("increment", left, right, Expr("1.0 + 0.01 * x"))
    model = Model(graph, BoundaryState(), (rule,))

    for seed in range(12):
        incremental = Runtime(
            model,
            root_seed=seed,
            config=RuntimeConfig(matcher_backend="incremental", incremental_verify=True),
        )
        reference = Runtime(
            model,
            root_seed=seed,
            config=RuntimeConfig(matcher_backend="reference"),
        )
        for _ in range(25):
            a_event = incremental.step().event
            b_event = reference.step().event
            assert a_event is not None and b_event is not None
            assert a_event.post_time == pytest.approx(b_event.post_time, rel=0, abs=1e-14)
            assert a_event.cause["rule_id"] == b_event.cause["rule_id"]
            assert a_event.cause["match_id"] == b_event.cause["match_id"]
            assert incremental.state_hash == reference.state_hash
