"""Construction twin: the system graph. Messages never become occurrence types."""
from __future__ import annotations

from osahr import (
    AttributeSpec,
    BoundaryDirection,
    BoundaryHandle,
    BoundaryState,
    Expr,
    ExternalEvent,
    HyperedgeType,
    Hypergraph,
    InputMode,
    Model,
    PatternGraph,
    PatternVertex,
    PortSpec,
    Rule,
    Runtime,
    Schema,
    TemplateEdge,
    TemplateGraph,
    TemplateVertex,
    ValueKind,
    Var,
    VertexType,
)

from .protocol import ASSEMBLE_RATE, CONSTRUCTION_RULE_ID, MOUTH_OWNER, ROOT_SEED


def construction_schema() -> Schema:
    return Schema(
        [
            VertexType("Cell", {}),
            VertexType(
                "Slot",
                {
                    "pending": AttributeSpec(ValueKind.BOOL, required=True),
                    "name": AttributeSpec(ValueKind.STRING, required=True),
                    "constraint": AttributeSpec(ValueKind.STRING, required=True),
                },
            ),
            VertexType(
                "Component",
                {"name": AttributeSpec(ValueKind.STRING, required=True)},
            ),
        ],
        [
            HyperedgeType(
                "PartOf",
                {"part": PortSpec("part", "Component")},
                {"cell": PortSpec("cell", "Cell")},
                {},
            )
        ],
        schema_id="grokcell-construction",
        version="0.1.0",
    )


def assemble_rule() -> Rule:
    return Rule(
        CONSTRUCTION_RULE_ID,
        PatternGraph(
            (
                PatternVertex("cell", "Cell"),
                PatternVertex(
                    "slot",
                    "Slot",
                    {
                        "pending": True,
                        "name": Var("comp_name"),
                        "constraint": Var("constraint"),
                    },
                ),
            )
        ),
        TemplateGraph(
            (
                TemplateVertex("cell", "Cell"),
                TemplateVertex(
                    "slot",
                    "Slot",
                    {
                        "pending": False,
                        "name": Expr("comp_name"),
                        "constraint": Expr("constraint"),
                    },
                ),
                TemplateVertex(
                    "comp",
                    "Component",
                    {"name": Expr("comp_name")},
                ),
            ),
            (
                TemplateEdge(
                    "part",
                    "PartOf",
                    {"part": ("comp",)},
                    {"cell": ("cell",)},
                ),
            ),
        ),
        Expr("p.assemble_rate"),
    )


def build_runtime(*, root_seed: int = ROOT_SEED) -> Runtime:
    schema = construction_schema()
    graph = Hypergraph(schema, namespace=0x6C11)
    graph.add_vertex("Cell", {})
    slot = graph.add_vertex(
        "Slot",
        {"pending": False, "name": "", "constraint": ""},
    )
    boundary = BoundaryState()
    boundary.add(
        BoundaryHandle(
            "proposal",
            BoundaryDirection.INPUT,
            "Slot",
            binding=slot.entity_id,
            payload_schema={
                "pending": AttributeSpec(ValueKind.BOOL, required=True),
                "name": AttributeSpec(ValueKind.STRING, required=True),
                "constraint": AttributeSpec(ValueKind.STRING, required=True),
            },
            input_mode=InputMode.REPLACE_BOUND_VERTEX_ATTRIBUTES,
        )
    )
    model = Model(
        graph,
        boundary,
        (assemble_rule(),),
        parameters={"assemble_rate": ASSEMBLE_RATE},
        memory={
            "owners": [MOUTH_OWNER],
            "skills": {MOUTH_OWNER: []},
            "bots_spawned": 0,
            "components": [],
        },
        model_id="grokcell-construction",
        version="0.1.0",
    )
    return Runtime(model, root_seed=root_seed)


def graph_component_names(runtime: Runtime) -> list[str]:
    names = [
        str(vertex.attributes["name"])
        for vertex in runtime.graph.vertices.values()
        if vertex.type_id == "Component"
    ]
    log = [str(item) for item in runtime.memory.get("components", [])]
    if log and set(log) == set(names):
        return log
    return sorted(names)


def licensed_assemble(runtime: Runtime, *, name: str, constraint: str, seq: int) -> None:
    """Admit path: boundary payload, then the kernel fires assemble-component."""
    runtime.inject(
        ExternalEvent(
            runtime.time,
            "grokcell",
            seq,
            f"proposal-{seq}",
            "proposal",
            {"pending": True, "name": name, "constraint": constraint},
        )
    )
    external = runtime.step()
    if external.event is None or external.event.kind.value != "external_input":
        raise RuntimeError("proposal did not preempt as an external input")
    assembled = runtime.step()
    if assembled.event is None:
        raise RuntimeError("assemble-component did not fire")
    if assembled.event.cause.get("rule_id") != CONSTRUCTION_RULE_ID:
        kind = assembled.event.kind.value
        rule = assembled.event.cause.get("rule_id")
        raise RuntimeError(f"expected assemble-component, got {kind} {rule}")
    components = list(runtime.memory.get("components", []))
    components.append(name)
    runtime.memory["components"] = components
