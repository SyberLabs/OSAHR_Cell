from __future__ import annotations

import statistics

from osahr import (
    BoundaryState,
    Expr,
    Hypergraph,
    Model,
    PatternGraph,
    Rule,
    Runtime,
    Schema,
    StateAssignment,
    TemplateGraph,
)


def competing_model() -> Model:
    schema = Schema([], [])
    graph = Hypergraph(schema)
    rule_a = Rule(
        "a",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("p.a"),
        adaptation=(StateAssignment("memory.last", "a"),),
    )
    rule_b = Rule(
        "b",
        PatternGraph(()),
        TemplateGraph(()),
        Expr("p.b"),
        adaptation=(StateAssignment("memory.last", "b"),),
    )
    return Model(graph, BoundaryState(), (rule_a, rule_b), {"a": 1.0, "b": 3.0}, {"last": None})


def test_competing_event_frequency() -> None:
    model = competing_model()
    b_count = 0
    samples = 2000
    for seed in range(samples):
        runtime = Runtime(model, root_seed=seed)
        runtime.step()
        b_count += runtime.memory["last"] == "b"
    frequency = b_count / samples
    assert 0.71 < frequency < 0.79


def test_waiting_time_mean() -> None:
    model = competing_model()
    waits = []
    for seed in range(1500):
        runtime = Runtime(model, root_seed=seed)
        event = runtime.step().event
        assert event is not None
        waits.append(event.delta_time)
    # Total activity is 4, so E[Delta t] = 0.25.
    assert abs(statistics.mean(waits) - 0.25) < 0.02
