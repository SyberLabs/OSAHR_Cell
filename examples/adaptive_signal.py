"""Executable adaptive-network example."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osahr import (
    AttributeSpec,
    BoundaryDirection,
    BoundaryHandle,
    BoundaryState,
    EntityCount,
    Expr,
    ExternalEvent,
    HyperedgeType,
    Hypergraph,
    InputMode,
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
)


def build_model() -> tuple[Model, object]:
    schema = Schema(
        [
            VertexType(
                "Agent",
                {
                    "active": AttributeSpec(ValueKind.BOOL, required=True),
                    "value": AttributeSpec(ValueKind.FLOAT, required=True),
                    "responsiveness": AttributeSpec(
                        ValueKind.FLOAT,
                        required=True,
                        minimum=0.0,
                        maximum=1.0,
                    ),
                },
            )
        ],
        [
            HyperedgeType(
                "Signal",
                {"source": PortSpec("source", "Agent")},
                {"target": PortSpec("target", "Agent")},
                {
                    "intensity": AttributeSpec(
                        ValueKind.FLOAT,
                        required=True,
                        minimum=0.0,
                    )
                },
            )
        ],
        schema_id="adaptive-signal",
    )

    graph = Hypergraph(schema, namespace=0xA11CE)
    sender = graph.add_vertex(
        "Agent", {"active": True, "value": 1.0, "responsiveness": 0.2}
    )
    receiver = graph.add_vertex(
        "Agent", {"active": True, "value": 0.0, "responsiveness": 0.1}
    )
    graph.add_edge(
        "Signal",
        {"source": (sender.entity_id,)},
        {"target": (receiver.entity_id,)},
        {"intensity": 0.5},
    )

    receive = Rule(
        "receive-signal",
        PatternGraph(
            (
                PatternVertex("sender", "Agent"),
                PatternVertex(
                    "receiver",
                    "Agent",
                    {
                        "active": True,
                        "value": Var("old_value"),
                        "responsiveness": Var("responsiveness"),
                    },
                ),
            ),
            (
                PatternEdge(
                    "signal",
                    "Signal",
                    {"source": ("sender",)},
                    {"target": ("receiver",)},
                    {"intensity": Var("intensity")},
                ),
            ),
        ),
        TemplateGraph(
            (
                TemplateVertex("sender", "Agent"),
                TemplateVertex(
                    "receiver",
                    "Agent",
                    {
                        "value": Expr("old_value + intensity"),
                        "responsiveness": Expr(
                            "clip(responsiveness + p.learning_rate * intensity, 0.0, 1.0)"
                        ),
                    },
                ),
            )
        ),
        Expr("p.base_rate * intensity * (0.1 + responsiveness)"),
        adaptation=(
            StateAssignment("memory.received_count", Expr("z.received_count + 1")),
            StateAssignment(
                "memory.intensity_ema",
                Expr("(1.0 - p.ema_alpha) * z.intensity_ema + p.ema_alpha * intensity"),
            ),
        ),
    )

    regenerate = Rule(
        "regenerate-signal",
        PatternGraph(
            (
                PatternVertex("sender", "Agent"),
                PatternVertex("receiver", "Agent"),
            )
        ),
        TemplateGraph(
            (
                TemplateVertex("sender", "Agent"),
                TemplateVertex("receiver", "Agent"),
            ),
            (
                TemplateEdge(
                    "new_signal",
                    "Signal",
                    {"source": ("sender",)},
                    {"target": ("receiver",)},
                    {"intensity": Expr("p.generated_intensity")},
                ),
            ),
        ),
        Expr("p.regeneration_rate"),
    )

    boundary = BoundaryState(
        {
            "receiver-input": BoundaryHandle(
                "receiver-input",
                BoundaryDirection.INPUT,
                "Agent",
                binding=receiver.entity_id,
                payload_schema={
                    "responsiveness": AttributeSpec(
                        ValueKind.FLOAT,
                        required=True,
                        minimum=0.0,
                        maximum=1.0,
                    )
                },
                input_mode=InputMode.MERGE_BOUND_VERTEX_ATTRIBUTES,
            )
        }
    )

    model = Model(
        graph,
        boundary,
        (receive, regenerate),
        {
            "base_rate": 2.0,
            "learning_rate": 0.2,
            "ema_alpha": 0.1,
            "regeneration_rate": 0.5,
            "generated_intensity": 0.25,
        },
        {"received_count": 0, "intensity_ema": 0.0},
        model_id="adaptive-signal",
    )
    return model, receiver.entity_id


def main() -> None:
    model, receiver_id = build_model()
    runtime = Runtime(model, root_seed=20260729)
    runtime.register_observable(EntityCount("agents", "Agent"))

    runtime.inject(
        ExternalEvent(
            3.0,
            "environment",
            1,
            "external-1",
            "receiver-input",
            {"responsiveness": 0.8},
        )
    )
    runtime.schedule_adaptation(
        ScheduledAdaptation(
            6.0,
            1,
            "slow-regeneration",
            (
                StateAssignment(
                    "parameters.regeneration_rate",
                    Expr("p.regeneration_rate * 0.5"),
                ),
            ),
        )
    )

    events = runtime.run_until_time(10.0)
    receiver = runtime.graph.vertices[receiver_id]

    print(f"events: {len(events)}")
    print(f"simulation time: {runtime.time:.6f}")
    print(f"agents: {runtime.observe('agents')}")
    print(f"receiver: {receiver.attributes}")
    print(f"memory: {runtime.memory}")
    print(f"state hash: {runtime.state_hash}")


if __name__ == "__main__":
    main()
