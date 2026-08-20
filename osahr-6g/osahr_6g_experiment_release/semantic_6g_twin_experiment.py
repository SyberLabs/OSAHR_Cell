"""OSAHR 6G Experiment 01: goal-aware semantic RAN control twin.

This experiment deliberately lives above the PHY/RF layer. It models a small
Open-RAN-like control plane in which robot UEs generate task-bearing messages,
UE/gNB associations rewire under mobility, two MEC paths have different
speed/reliability/fidelity trade-offs, and the fast MEC node suffers an
exogenous outage. Three routing policies share the exact same stochastic world
model and differ only in the hazard assigned to admissible (task, route)
occurrences:

* throughput: conventional speed/load-oriented control;
* qos: task-agnostic reliability/fidelity-aware control;
* semantic: goal-aware control that weights route value by task utility/deadline.

The model uses OSAHR's typed directed hypergraph, DPO rewrites, open boundary
inputs, incremental matching, and modified-next-reaction scheduler.
"""

from __future__ import annotations

import argparse
import csv
import concurrent.futures
import json
import math
import statistics
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

# Allow running directly from a source checkout.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    PatternEdge,
    PatternGraph,
    PatternVertex,
    PortSpec,
    Rule,
    Runtime,
    RuntimeConfig,
    ScheduledAdaptation,
    SchedulerKind,
    Schema,
    StateAssignment,
    TemplateEdge,
    TemplateGraph,
    TemplateVertex,
    ValueKind,
    Var,
    VertexType,
)
from osahr.rng import derive_seed


POLICIES = ("throughput", "qos", "semantic")


@dataclass(frozen=True)
class ExperimentConfig:
    horizon: float = 60.0
    arrivals_stop: float = 50.0
    fast_outage_start: float = 20.0
    fast_outage_end: float = 35.0
    n_ues: int = 4
    critical_rate_per_ue: float = 0.22
    background_rate_per_ue: float = 0.48
    mobility_rate_per_ue: float = 0.045
    route_rate: float = 18.0
    reroute_rate: float = 25.0
    congestion_penalty: float = 0.55
    critical_payload: float = 1.0
    background_payload: float = 3.0
    critical_utility: float = 1.0
    background_utility: float = 0.18
    critical_deadline: float = 1.5
    background_deadline: float = 6.0


@dataclass
class RunMetrics:
    policy: str
    replicate: int
    seed: int
    events: int
    final_time: float
    state_hash: str
    generated: int
    generated_critical: int
    generated_background: int
    delivered: int
    delivered_critical: int
    delivered_background: int
    timely: int
    timely_critical: int
    timely_background: int
    generated_utility: float
    delivered_utility: float
    timely_semantic_utility: float
    energy: float
    bytes_delivered: float
    reroutes: int
    handovers: int
    mean_latency: float
    max_queued: int
    max_inflight: int
    final_queued: int
    final_inflight: int
    critical_success_rate: float
    background_success_rate: float
    timely_task_rate: float
    goal_utility_ratio: float
    semantic_efficiency: float


def _f(required: bool = True, *, minimum: float | None = None, maximum: float | None = None):
    return AttributeSpec(ValueKind.FLOAT, required=required, minimum=minimum, maximum=maximum)


def _i(required: bool = True, *, minimum: int | None = None, maximum: int | None = None):
    return AttributeSpec(ValueKind.INT, required=required, minimum=minimum, maximum=maximum)


def build_schema() -> Schema:
    return Schema(
        [
            VertexType(
                "UE",
                {
                    "name": AttributeSpec(ValueKind.STRING, required=True),
                    "critical_rate": _f(minimum=0.0),
                    "background_rate": _f(minimum=0.0),
                    "mobility_rate": _f(minimum=0.0),
                },
            ),
            VertexType(
                "GNB",
                {"name": AttributeSpec(ValueKind.STRING, required=True)},
            ),
            VertexType(
                "EdgeNode",
                {
                    "name": AttributeSpec(ValueKind.STRING, required=True),
                    "available": AttributeSpec(ValueKind.BOOL, required=True),
                    "load": _i(minimum=0),
                    "capacity": _i(minimum=1),
                    "service_rate": _f(minimum=0.0),
                    "reliability": _f(minimum=0.0, maximum=1.0),
                    "fidelity": _f(minimum=0.0, maximum=1.0),
                    "energy_cost": _f(minimum=0.0),
                },
            ),
            VertexType(
                "Task",
                {
                    "kind": AttributeSpec(
                        ValueKind.STRING,
                        required=True,
                        choices=frozenset({"critical", "background"}),
                    ),
                    "utility": _f(minimum=0.0),
                    "payload": _f(minimum=0.0),
                    "deadline": _f(minimum=0.0),
                    "born": _f(minimum=0.0),
                    "status": AttributeSpec(
                        ValueKind.STRING,
                        required=True,
                        choices=frozenset({"queued", "inflight", "delivered"}),
                    ),
                    "latency": _f(minimum=-1.0),
                    "delivered_fidelity": _f(minimum=0.0, maximum=1.0),
                    "path_energy": _f(minimum=0.0),
                    "reroutes": _i(minimum=0),
                },
            ),
        ],
        [
            HyperedgeType(
                "Association",
                {"ue": PortSpec("ue", "UE")},
                {"gnb": PortSpec("gnb", "GNB")},
            ),
            HyperedgeType(
                "Neighbor",
                {"from_gnb": PortSpec("from_gnb", "GNB")},
                {"to_gnb": PortSpec("to_gnb", "GNB")},
            ),
            HyperedgeType(
                "Path",
                {"gnb": PortSpec("gnb", "GNB")},
                {"edge": PortSpec("edge", "EdgeNode")},
                {
                    "link_quality": _f(minimum=0.0, maximum=1.0),
                    "name": AttributeSpec(ValueKind.STRING, required=True),
                },
            ),
            HyperedgeType(
                "Queued",
                {"source": PortSpec("source", "UE")},
                {"task": PortSpec("task", "Task")},
            ),
            # A true higher-order relation: one transmission occurrence relates
            # the source UE, task, current gNB and selected edge node.
            HyperedgeType(
                "Transit",
                {"source": PortSpec("source", "UE")},
                {
                    "task": PortSpec("task", "Task"),
                    "gnb": PortSpec("gnb", "GNB"),
                    "edge": PortSpec("edge", "EdgeNode"),
                },
            ),
        ],
        schema_id="osahr-6g-semantic-control-twin",
        version="1.0.0",
    )


def _generation_rule(kind: str) -> Rule:
    if kind == "critical":
        rate_var = "critical_rate"
        payload = "p.critical_payload"
        utility = "p.critical_utility"
        deadline = "p.critical_deadline"
    else:
        rate_var = "background_rate"
        payload = "p.background_payload"
        utility = "p.background_utility"
        deadline = "p.background_deadline"

    return Rule(
        f"generate-{kind}",
        PatternGraph(
            (
                PatternVertex("ue", "UE", {rate_var: Var("arrival_rate")}),
            )
        ),
        TemplateGraph(
            (
                TemplateVertex("ue", "UE"),
                TemplateVertex(
                    "task",
                    "Task",
                    {
                        "kind": kind,
                        "utility": Expr(utility),
                        "payload": Expr(payload),
                        "deadline": Expr(deadline),
                        "born": Expr("time"),
                        "status": "queued",
                        "latency": -1.0,
                        "delivered_fidelity": 0.0,
                        "path_energy": 0.0,
                        "reroutes": 0,
                    },
                ),
            ),
            (
                TemplateEdge(
                    "queue",
                    "Queued",
                    {"source": ("ue",)},
                    {"task": ("task",)},
                ),
            ),
        ),
        Expr("p.arrival_scale * arrival_rate"),
        adaptation=(
            StateAssignment("memory.generated", Expr("z.generated + 1")),
            StateAssignment(
                "memory.generated_critical",
                Expr("z.generated_critical + (1 if meta.kind == 'critical' else 0)"),
            ),
            StateAssignment(
                "memory.generated_background",
                Expr("z.generated_background + (1 if meta.kind == 'background' else 0)"),
            ),
            StateAssignment(
                "memory.generated_utility",
                Expr(f"z.generated_utility + {utility}"),
            ),
        ),
        meta={"kind": kind},
    )


def _route_hazard(policy: str) -> Expr:
    # Hazards are unnormalized utilities. Because OSAHR samples occurrences in
    # proportion to hazard, competing (task, path) embeddings induce a stochastic
    # softmax-like resource allocator while remaining in exact CTMC semantics.
    base = (
        "p.route_rate * exp(p.choice_beta * ("
        "p.speed_weight * (service_rate / p.service_scale) "
        "+ p.link_weight * link_quality "
        "- p.load_weight * (load / capacity) "
        "- p.energy_weight * energy_cost"
    )
    if policy == "throughput":
        return Expr(base + "))")
    if policy == "qos":
        return Expr(
            base
            + " + p.qos_reliability_weight * reliability"
            + " + p.qos_fidelity_weight * fidelity))"
        )
    if policy == "semantic":
        return Expr(
            base
            + " + p.qos_reliability_weight * reliability"
            + " + p.qos_fidelity_weight * fidelity"
            + " + p.semantic_weight * (utility / deadline) * reliability * fidelity"
            + "))"
        )
    raise ValueError(policy)


def _routing_rule(policy: str) -> Rule:
    return Rule(
        "route-task",
        PatternGraph(
            (
                PatternVertex("ue", "UE"),
                PatternVertex("gnb", "GNB"),
                PatternVertex(
                    "edge",
                    "EdgeNode",
                    {
                        "available": True,
                        "load": Var("load"),
                        "capacity": Var("capacity"),
                        "service_rate": Var("service_rate"),
                        "reliability": Var("reliability"),
                        "fidelity": Var("fidelity"),
                        "energy_cost": Var("energy_cost"),
                    },
                ),
                PatternVertex(
                    "task",
                    "Task",
                    {
                        "kind": Var("task_kind"),
                        "utility": Var("utility"),
                        "payload": Var("task_payload"),
                        "deadline": Var("deadline"),
                        "status": "queued",
                    },
                ),
            ),
            (
                PatternEdge(
                    "association",
                    "Association",
                    {"ue": ("ue",)},
                    {"gnb": ("gnb",)},
                ),
                PatternEdge(
                    "path",
                    "Path",
                    {"gnb": ("gnb",)},
                    {"edge": ("edge",)},
                    {"link_quality": Var("link_quality")},
                ),
                PatternEdge(
                    "queue",
                    "Queued",
                    {"source": ("ue",)},
                    {"task": ("task",)},
                ),
            ),
        ),
        TemplateGraph(
            (
                TemplateVertex("ue", "UE"),
                TemplateVertex("gnb", "GNB"),
                TemplateVertex(
                    "edge",
                    "EdgeNode",
                    {"load": Expr("load + 1")},
                ),
                TemplateVertex("task", "Task", {"status": "inflight"}),
            ),
            (
                TemplateEdge(
                    "association",
                    "Association",
                    {"ue": ("ue",)},
                    {"gnb": ("gnb",)},
                ),
                TemplateEdge(
                    "path",
                    "Path",
                    {"gnb": ("gnb",)},
                    {"edge": ("edge",)},
                ),
                TemplateEdge(
                    "transit",
                    "Transit",
                    {"source": ("ue",)},
                    {
                        "task": ("task",),
                        "gnb": ("gnb",),
                        "edge": ("edge",),
                    },
                ),
            ),
        ),
        _route_hazard(policy),
        guard=Expr("load < capacity"),
        meta={"policy": policy},
    )


def _completion_rule() -> Rule:
    return Rule(
        "complete-task",
        PatternGraph(
            (
                PatternVertex("ue", "UE"),
                PatternVertex("gnb", "GNB"),
                PatternVertex(
                    "edge",
                    "EdgeNode",
                    {
                        "available": True,
                        "load": Var("load"),
                        "service_rate": Var("service_rate"),
                        "reliability": Var("reliability"),
                        "fidelity": Var("fidelity"),
                        "energy_cost": Var("energy_cost"),
                    },
                ),
                PatternVertex(
                    "task",
                    "Task",
                    {
                        "kind": Var("task_kind"),
                        "utility": Var("utility"),
                        "payload": Var("task_payload"),
                        "deadline": Var("deadline"),
                        "born": Var("born"),
                        "status": "inflight",
                    },
                ),
            ),
            (
                PatternEdge(
                    "path",
                    "Path",
                    {"gnb": ("gnb",)},
                    {"edge": ("edge",)},
                    {"link_quality": Var("link_quality")},
                ),
                PatternEdge(
                    "transit",
                    "Transit",
                    {"source": ("ue",)},
                    {
                        "task": ("task",),
                        "gnb": ("gnb",),
                        "edge": ("edge",),
                    },
                ),
            ),
        ),
        TemplateGraph(
            (
                TemplateVertex("ue", "UE"),
                TemplateVertex("gnb", "GNB"),
                TemplateVertex("edge", "EdgeNode", {"load": Expr("load - 1")}),
            ),
            (
                TemplateEdge(
                    "path",
                    "Path",
                    {"gnb": ("gnb",)},
                    {"edge": ("edge",)},
                ),
            ),
        ),
        Expr(
            "service_rate * reliability * link_quality / "
            "(task_payload * (1.0 + p.congestion_penalty * max(0, load - 1)))"
        ),
        guard=Expr("load > 0"),
        adaptation=(
            StateAssignment("memory.delivered", Expr("z.delivered + 1")),
            StateAssignment(
                "memory.delivered_critical",
                Expr("z.delivered_critical + (1 if task_kind == 'critical' else 0)"),
            ),
            StateAssignment(
                "memory.delivered_background",
                Expr("z.delivered_background + (1 if task_kind == 'background' else 0)"),
            ),
            StateAssignment(
                "memory.timely",
                Expr("z.timely + (1 if (time - born) <= deadline else 0)"),
            ),
            StateAssignment(
                "memory.timely_critical",
                Expr(
                    "z.timely_critical + "
                    "(1 if task_kind == 'critical' and (time - born) <= deadline else 0)"
                ),
            ),
            StateAssignment(
                "memory.timely_background",
                Expr(
                    "z.timely_background + "
                    "(1 if task_kind == 'background' and (time - born) <= deadline else 0)"
                ),
            ),
            StateAssignment(
                "memory.delivered_utility",
                Expr("z.delivered_utility + utility * fidelity * link_quality"),
            ),
            StateAssignment(
                "memory.timely_semantic_utility",
                Expr(
                    "z.timely_semantic_utility + "
                    "(utility * fidelity * link_quality if (time - born) <= deadline else 0.0)"
                ),
            ),
            StateAssignment("memory.energy", Expr("z.energy + task_payload * energy_cost")),
            StateAssignment("memory.bytes_delivered", Expr("z.bytes_delivered + task_payload")),
            StateAssignment("memory.latency_sum", Expr("z.latency_sum + (time - born)")),
        ),
    )


def _reroute_rule() -> Rule:
    return Rule(
        "reroute-failed-edge",
        PatternGraph(
            (
                PatternVertex("ue", "UE"),
                PatternVertex("gnb", "GNB"),
                PatternVertex(
                    "edge",
                    "EdgeNode",
                    {"available": False, "load": Var("load")},
                ),
                PatternVertex(
                    "task",
                    "Task",
                    {"status": "inflight", "reroutes": Var("reroutes")},
                ),
            ),
            (
                PatternEdge(
                    "path",
                    "Path",
                    {"gnb": ("gnb",)},
                    {"edge": ("edge",)},
                ),
                PatternEdge(
                    "transit",
                    "Transit",
                    {"source": ("ue",)},
                    {
                        "task": ("task",),
                        "gnb": ("gnb",),
                        "edge": ("edge",),
                    },
                ),
            ),
        ),
        TemplateGraph(
            (
                TemplateVertex("ue", "UE"),
                TemplateVertex("gnb", "GNB"),
                TemplateVertex("edge", "EdgeNode", {"load": Expr("load - 1")}),
                TemplateVertex(
                    "task",
                    "Task",
                    {"status": "queued", "reroutes": Expr("reroutes + 1")},
                ),
            ),
            (
                TemplateEdge(
                    "path",
                    "Path",
                    {"gnb": ("gnb",)},
                    {"edge": ("edge",)},
                ),
                TemplateEdge(
                    "queue",
                    "Queued",
                    {"source": ("ue",)},
                    {"task": ("task",)},
                ),
            ),
        ),
        Expr("p.reroute_rate"),
        guard=Expr("load > 0"),
        adaptation=(
            StateAssignment("memory.reroutes", Expr("z.reroutes + 1")),
        ),
    )


def _handover_rule() -> Rule:
    return Rule(
        "handover",
        PatternGraph(
            (
                PatternVertex(
                    "ue",
                    "UE",
                    {"mobility_rate": Var("mobility_rate")},
                ),
                PatternVertex("old", "GNB"),
                PatternVertex("new", "GNB"),
            ),
            (
                PatternEdge(
                    "association",
                    "Association",
                    {"ue": ("ue",)},
                    {"gnb": ("old",)},
                ),
                PatternEdge(
                    "neighbor",
                    "Neighbor",
                    {"from_gnb": ("old",)},
                    {"to_gnb": ("new",)},
                ),
            ),
        ),
        TemplateGraph(
            (
                TemplateVertex("ue", "UE"),
                TemplateVertex("old", "GNB"),
                TemplateVertex("new", "GNB"),
            ),
            (
                TemplateEdge(
                    "neighbor",
                    "Neighbor",
                    {"from_gnb": ("old",)},
                    {"to_gnb": ("new",)},
                ),
                TemplateEdge(
                    "new_association",
                    "Association",
                    {"ue": ("ue",)},
                    {"gnb": ("new",)},
                ),
            ),
        ),
        Expr("mobility_rate"),
        adaptation=(
            StateAssignment("memory.handovers", Expr("z.handovers + 1")),
        ),
    )


def build_model(policy: str, cfg: ExperimentConfig) -> tuple[Model, str]:
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {POLICIES}")
    schema = build_schema()
    graph = Hypergraph(schema, namespace=0x6A60)

    gnb_a = graph.add_vertex("GNB", {"name": "gNB-A"})
    gnb_b = graph.add_vertex("GNB", {"name": "gNB-B"})

    fast = graph.add_vertex(
        "EdgeNode",
        {
            "name": "MEC-fast",
            "available": True,
            "load": 0,
            "capacity": 6,
            "service_rate": 8.0,
            "reliability": 0.94,
            "fidelity": 0.92,
            "energy_cost": 1.0,
        },
    )
    robust = graph.add_vertex(
        "EdgeNode",
        {
            "name": "MEC-robust",
            "available": True,
            "load": 0,
            "capacity": 3,
            "service_rate": 4.2,
            "reliability": 0.997,
            "fidelity": 0.99,
            "energy_cost": 1.18,
        },
    )

    # Mobility topology. Each gNB has one alternate neighbor so handover matches
    # are unambiguous and rewiring remains a genuine graph rewrite.
    graph.add_edge("Neighbor", {"from_gnb": (gnb_a.entity_id,)}, {"to_gnb": (gnb_b.entity_id,)})
    graph.add_edge("Neighbor", {"from_gnb": (gnb_b.entity_id,)}, {"to_gnb": (gnb_a.entity_id,)})

    # RAN-to-MEC path qualities differ by association, giving mobility a real
    # effect on future transition hazards without embedding a PHY simulator.
    path_specs = [
        (gnb_a, fast, "A-fast", 1.00),
        (gnb_a, robust, "A-robust", 0.90),
        (gnb_b, fast, "B-fast", 0.84),
        (gnb_b, robust, "B-robust", 1.00),
    ]
    for gnb, edge, name, quality in path_specs:
        graph.add_edge(
            "Path",
            {"gnb": (gnb.entity_id,)},
            {"edge": (edge.entity_id,)},
            {"link_quality": quality, "name": name},
        )

    for index in range(cfg.n_ues):
        ue = graph.add_vertex(
            "UE",
            {
                "name": f"robot-{index}",
                "critical_rate": cfg.critical_rate_per_ue,
                "background_rate": cfg.background_rate_per_ue,
                "mobility_rate": cfg.mobility_rate_per_ue,
            },
        )
        initial = gnb_a if index % 2 == 0 else gnb_b
        graph.add_edge(
            "Association",
            {"ue": (ue.entity_id,)},
            {"gnb": (initial.entity_id,)},
        )

    boundary = BoundaryState(
        {
            "fast-edge-control": BoundaryHandle(
                "fast-edge-control",
                BoundaryDirection.INPUT,
                "EdgeNode",
                binding=fast.entity_id,
                payload_schema={"available": AttributeSpec(ValueKind.BOOL, required=True)},
                input_mode=InputMode.MERGE_BOUND_VERTEX_ATTRIBUTES,
            ),
            "robust-edge-control": BoundaryHandle(
                "robust-edge-control",
                BoundaryDirection.INPUT,
                "EdgeNode",
                binding=robust.entity_id,
                payload_schema={"available": AttributeSpec(ValueKind.BOOL, required=True)},
                input_mode=InputMode.MERGE_BOUND_VERTEX_ATTRIBUTES,
            ),
        }
    )

    rules = (
        _generation_rule("critical"),
        _generation_rule("background"),
        _routing_rule(policy),
        _completion_rule(),
        _reroute_rule(),
        _handover_rule(),
    )

    params = {
        "arrival_scale": 1.0,
        "critical_payload": cfg.critical_payload,
        "background_payload": cfg.background_payload,
        "critical_utility": cfg.critical_utility,
        "background_utility": cfg.background_utility,
        "critical_deadline": cfg.critical_deadline,
        "background_deadline": cfg.background_deadline,
        "route_rate": cfg.route_rate,
        "reroute_rate": cfg.reroute_rate,
        "congestion_penalty": cfg.congestion_penalty,
        # Routing policy weights. The physical model is unchanged across arms;
        # only the score assigned to enabled routing occurrences differs.
        "choice_beta": 0.80,
        "service_scale": 8.0,
        "speed_weight": 1.25,
        "link_weight": 0.45,
        "load_weight": 1.20,
        "energy_weight": 0.18,
        "qos_reliability_weight": 1.15,
        "qos_fidelity_weight": 0.80,
        "semantic_weight": 2.20,
    }
    memory = {
        "generated": 0,
        "generated_critical": 0,
        "generated_background": 0,
        "generated_utility": 0.0,
        "delivered": 0,
        "delivered_critical": 0,
        "delivered_background": 0,
        "timely": 0,
        "timely_critical": 0,
        "timely_background": 0,
        "delivered_utility": 0.0,
        "timely_semantic_utility": 0.0,
        "energy": 0.0,
        "bytes_delivered": 0.0,
        "latency_sum": 0.0,
        "reroutes": 0,
        "handovers": 0,
    }

    return (
        Model(
            graph,
            boundary,
            rules,
            parameters=params,
            memory=memory,
            model_id=f"6g-semantic-control-{policy}",
            version="1.0.0",
        ),
        str(fast.entity_id),
    )


def _count_edge_type(runtime: Runtime, edge_type: str) -> int:
    return len(runtime.graph.edges_by_type[edge_type])


def run_one(policy: str, replicate: int, root_seed: int, cfg: ExperimentConfig) -> RunMetrics:
    model, _ = build_model(policy, cfg)
    seed = derive_seed(root_seed, f"6g:{replicate}")
    runtime = Runtime(
        model,
        root_seed=seed,
        config=RuntimeConfig(
            scheduler=SchedulerKind.NEXT_REACTION,
            matcher_backend="incremental",
            incremental_verify=False,
            max_events=200_000,
        ),
    )

    runtime.inject(
        ExternalEvent(
            cfg.fast_outage_start,
            "physical-twin",
            1,
            f"fast-down-{replicate}",
            "fast-edge-control",
            {"available": False},
        )
    )
    runtime.inject(
        ExternalEvent(
            cfg.fast_outage_end,
            "physical-twin",
            2,
            f"fast-up-{replicate}",
            "fast-edge-control",
            {"available": True},
        )
    )
    runtime.schedule_adaptation(
        ScheduledAdaptation(
            cfg.arrivals_stop,
            1,
            "stop-arrivals",
            (StateAssignment("parameters.arrival_scale", 0.0),),
        )
    )

    max_queued = _count_edge_type(runtime, "Queued")
    max_inflight = _count_edge_type(runtime, "Transit")
    while runtime.time < cfg.horizon:
        next_time = runtime.peek_next_event_time()
        if next_time is None or next_time > cfg.horizon:
            runtime.run_until_time(cfg.horizon)
            break
        runtime.step()
        max_queued = max(max_queued, _count_edge_type(runtime, "Queued"))
        max_inflight = max(max_inflight, _count_edge_type(runtime, "Transit"))

    z = runtime.memory
    delivered = int(z["delivered"])
    generated = int(z["generated"])
    gen_crit = int(z["generated_critical"])
    gen_bg = int(z["generated_background"])
    timely = int(z["timely"])
    timely_crit = int(z["timely_critical"])
    timely_bg = int(z["timely_background"])
    gen_utility = float(z["generated_utility"])
    timely_utility = float(z["timely_semantic_utility"])
    energy = float(z["energy"])

    return RunMetrics(
        policy=policy,
        replicate=replicate,
        seed=seed,
        events=runtime.event_index,
        final_time=runtime.time,
        state_hash=runtime.state_hash,
        generated=generated,
        generated_critical=gen_crit,
        generated_background=gen_bg,
        delivered=delivered,
        delivered_critical=int(z["delivered_critical"]),
        delivered_background=int(z["delivered_background"]),
        timely=timely,
        timely_critical=timely_crit,
        timely_background=timely_bg,
        generated_utility=gen_utility,
        delivered_utility=float(z["delivered_utility"]),
        timely_semantic_utility=timely_utility,
        energy=energy,
        bytes_delivered=float(z["bytes_delivered"]),
        reroutes=int(z["reroutes"]),
        handovers=int(z["handovers"]),
        mean_latency=(float(z["latency_sum"]) / delivered) if delivered else math.nan,
        max_queued=max_queued,
        max_inflight=max_inflight,
        final_queued=_count_edge_type(runtime, "Queued"),
        final_inflight=_count_edge_type(runtime, "Transit"),
        critical_success_rate=(timely_crit / gen_crit) if gen_crit else math.nan,
        background_success_rate=(timely_bg / gen_bg) if gen_bg else math.nan,
        timely_task_rate=(timely / generated) if generated else math.nan,
        goal_utility_ratio=(timely_utility / gen_utility) if gen_utility else math.nan,
        semantic_efficiency=(timely_utility / energy) if energy > 0 else math.nan,
    )


def summarize(rows: list[RunMetrics]) -> dict[str, dict[str, dict[str, float]]]:
    metrics = [
        "critical_success_rate",
        "background_success_rate",
        "timely_task_rate",
        "goal_utility_ratio",
        "semantic_efficiency",
        "mean_latency",
        "reroutes",
        "max_queued",
        "final_queued",
        "energy",
    ]
    out: dict[str, dict[str, dict[str, float]]] = {}
    for policy in POLICIES:
        subset = [row for row in rows if row.policy == policy]
        out[policy] = {}
        for metric in metrics:
            values = [float(getattr(row, metric)) for row in subset]
            ordered = sorted(values)
            n = len(values)
            q = lambda p: ordered[min(n - 1, max(0, int(round(p * (n - 1)))))]
            out[policy][metric] = {
                "n": float(n),
                "mean": statistics.fmean(values),
                "stdev": statistics.stdev(values) if n > 1 else 0.0,
                "q05": q(0.05),
                "median": q(0.50),
                "q95": q(0.95),
            }
    return out


def bootstrap_differences(
    rows: list[RunMetrics],
    *,
    metric: str,
    treatment: str = "semantic",
    baseline: str = "throughput",
    bootstrap_seed: int = 20260812,
    samples: int = 10_000,
) -> dict[str, float]:
    # Seed-matched paired bootstrap. This uses replicate IDs as paired scenario
    # blocks; it is not claimed to be a strict common-random-number construction
    # because different policies consume stochastic streams differently after
    # their trajectories diverge.
    import random

    by_policy = {
        policy: {row.replicate: row for row in rows if row.policy == policy}
        for policy in POLICIES
    }
    ids = sorted(set(by_policy[treatment]) & set(by_policy[baseline]))
    diffs = [
        float(getattr(by_policy[treatment][i], metric))
        - float(getattr(by_policy[baseline][i], metric))
        for i in ids
    ]
    rng = random.Random(bootstrap_seed)
    boot = []
    n = len(diffs)
    for _ in range(samples):
        boot.append(statistics.fmean(diffs[rng.randrange(n)] for _ in range(n)))
    boot.sort()
    return {
        "n_pairs": float(n),
        "mean_difference": statistics.fmean(diffs),
        "ci95_low": boot[int(0.025 * (samples - 1))],
        "ci95_high": boot[int(0.975 * (samples - 1))],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replicates", type=int, default=300)
    parser.add_argument("--replicate-start", type=int, default=0)
    parser.add_argument("--root-seed", type=int, default=0x6A602026)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiment_output" / "6g_semantic_twin")
    args = parser.parse_args()

    cfg = ExperimentConfig()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    jobs = [(policy, replicate, args.root_seed, cfg) for policy in POLICIES for replicate in range(args.replicate_start, args.replicate_start + args.replicates)]
    if args.workers <= 1:
        rows = [run_one(*job) for job in jobs]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(run_one, *job) for job in jobs]
            rows = [future.result() for future in futures]
        rows.sort(key=lambda row: (POLICIES.index(row.policy), row.replicate))

    csv_path = args.output_dir / "replicates.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    summary = summarize(rows)
    comparisons = {
        metric: bootstrap_differences(rows, metric=metric)
        for metric in (
            "critical_success_rate",
            "goal_utility_ratio",
            "semantic_efficiency",
            "mean_latency",
            "reroutes",
            "max_queued",
        )
    }

    payload: dict[str, Any] = {
        "experiment": "OSAHR 6G Experiment 01 - goal-aware semantic control twin",
        "replicates_per_policy": args.replicates,
        "root_seed": args.root_seed,
        "config": asdict(cfg),
        "summary": summary,
        "semantic_minus_throughput_paired_bootstrap": comparisons,
    }
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"\nWrote {csv_path}")
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
