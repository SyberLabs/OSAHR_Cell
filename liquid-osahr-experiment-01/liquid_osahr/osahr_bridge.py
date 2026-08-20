"""Bridge learned point-process hazards into an exact OSAHR 6G control twin.

The bridge uses an open-loop exogenous-covariate intensity schedule. At each
irregular telemetry timestamp, a liquid/baseline model supplies piecewise-
constant service, down, and recovery intensities. External OSAHR boundary
updates atomically replace those intensities. Between telemetry updates,
OSAHR's next-reaction scheduler samples the declared CTMC exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import math
import sys
import numpy as np

VENDOR = Path(__file__).resolve().parents[1] / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from osahr import (  # type: ignore
    AttributeSpec, BoundaryDirection, BoundaryHandle, BoundaryState,
    Expr, ExternalEvent, HyperedgeType, Hypergraph, InputMode, Model,
    PatternEdge, PatternGraph, PatternVertex, PortSpec, Rule, Runtime,
    RuntimeConfig, ScheduledAdaptation, SchedulerKind, Schema, StateAssignment,
    TemplateEdge, TemplateGraph, TemplateVertex, ValueKind, Var, VertexType,
)
from osahr.rng import derive_seed  # type: ignore


POLICIES = ("throughput", "semantic")


@dataclass(frozen=True)
class TwinConfig:
    horizon: float = 30.0
    arrivals_stop: float = 25.0
    n_ues: int = 4
    critical_rate_per_ue: float = 0.20
    background_rate_per_ue: float = 0.42
    mobility_rate_per_ue: float = 0.055
    route_rate: float = 18.0
    reroute_rate: float = 28.0
    congestion_penalty: float = 0.58
    critical_payload: float = 1.0
    background_payload: float = 2.8
    critical_utility: float = 1.0
    background_utility: float = 0.18
    critical_deadline: float = 1.5
    background_deadline: float = 6.0


@dataclass
class TwinMetrics:
    hazard_model: str
    regime: str
    policy: str
    scenario: int
    replicate: int
    seed: int
    events: int
    generated: int
    delivered: int
    timely_critical: int
    generated_critical: int
    goal_utility_ratio: float
    critical_success_rate: float
    mean_latency: float
    energy: float
    outages: int
    recoveries: int
    reroutes: int
    handovers: int
    final_queued: int
    final_inflight: int
    state_hash: str


def _f(required=True, minimum=None, maximum=None):
    return AttributeSpec(ValueKind.FLOAT, required=required, minimum=minimum, maximum=maximum)

def _i(required=True, minimum=None, maximum=None):
    return AttributeSpec(ValueKind.INT, required=required, minimum=minimum, maximum=maximum)


def build_schema() -> Schema:
    return Schema(
        [
            VertexType("UE", {
                "name": AttributeSpec(ValueKind.STRING),
                "critical_rate": _f(minimum=0.0),
                "background_rate": _f(minimum=0.0),
                "mobility_rate": _f(minimum=0.0),
            }),
            VertexType("GNB", {"name": AttributeSpec(ValueKind.STRING)}),
            VertexType("EdgeNode", {
                "name": AttributeSpec(ValueKind.STRING),
                "available": AttributeSpec(ValueKind.BOOL),
                "load": _i(minimum=0),
                "capacity": _i(minimum=1),
                "service_rate": _f(minimum=0.0),
                "down_hazard": _f(minimum=0.0),
                "up_hazard": _f(minimum=0.0),
                "reliability": _f(minimum=0.0, maximum=1.0),
                "fidelity": _f(minimum=0.0, maximum=1.0),
                "energy_cost": _f(minimum=0.0),
            }),
            VertexType("Task", {
                "kind": AttributeSpec(ValueKind.STRING, choices=frozenset({"critical", "background"})),
                "utility": _f(minimum=0.0),
                "payload_size": _f(minimum=0.0),
                "deadline": _f(minimum=0.0),
                "born": _f(minimum=0.0),
                "status": AttributeSpec(ValueKind.STRING, choices=frozenset({"queued", "inflight"})),
                "reroutes": _i(minimum=0),
            }),
        ],
        [
            HyperedgeType("Association", {"ue": PortSpec("ue", "UE")}, {"gnb": PortSpec("gnb", "GNB")}),
            HyperedgeType("Neighbor", {"from_gnb": PortSpec("from_gnb", "GNB")}, {"to_gnb": PortSpec("to_gnb", "GNB")}),
            HyperedgeType("Path", {"gnb": PortSpec("gnb", "GNB")}, {"edge": PortSpec("edge", "EdgeNode")}, {
                "link_quality": _f(minimum=0.0, maximum=1.0),
                "name": AttributeSpec(ValueKind.STRING),
            }),
            HyperedgeType("Queued", {"source": PortSpec("source", "UE")}, {"task": PortSpec("task", "Task")}),
            HyperedgeType("Transit", {"source": PortSpec("source", "UE")}, {
                "task": PortSpec("task", "Task"), "gnb": PortSpec("gnb", "GNB"), "edge": PortSpec("edge", "EdgeNode")
            }),
        ],
        schema_id="liquid-osahr-6g-twin", version="1.0.0",
    )


def _generation_rule(kind: str) -> Rule:
    if kind == "critical":
        rate_var, payload, utility, deadline = "critical_rate", "p.critical_payload", "p.critical_utility", "p.critical_deadline"
    else:
        rate_var, payload, utility, deadline = "background_rate", "p.background_payload", "p.background_utility", "p.background_deadline"
    return Rule(
        f"generate-{kind}",
        PatternGraph((PatternVertex("ue", "UE", {rate_var: Var("arrival_rate")}),)),
        TemplateGraph(
            (
                TemplateVertex("ue", "UE"),
                TemplateVertex("task", "Task", {
                    "kind": kind, "utility": Expr(utility), "payload_size": Expr(payload),
                    "deadline": Expr(deadline), "born": Expr("time"), "status": "queued", "reroutes": 0,
                }),
            ),
            (TemplateEdge("queue", "Queued", {"source": ("ue",)}, {"task": ("task",)}),),
        ),
        Expr("p.arrival_scale * arrival_rate"),
        adaptation=(
            StateAssignment("memory.generated", Expr("z.generated + 1")),
            StateAssignment("memory.generated_critical", Expr("z.generated_critical + (1 if meta.kind == 'critical' else 0)")),
            StateAssignment("memory.generated_utility", Expr(f"z.generated_utility + {utility}")),
        ),
        meta={"kind": kind},
    )


def _route_hazard(policy: str) -> Expr:
    base = (
        "p.route_rate * exp(p.choice_beta * ("
        "p.speed_weight * (service_rate / p.service_scale) + p.link_weight * link_quality "
        "- p.load_weight * (load / capacity) - p.energy_weight * energy_cost "
        "+ p.reliability_weight * reliability + p.fidelity_weight * fidelity"
    )
    if policy == "throughput":
        return Expr(base + "))")
    if policy == "semantic":
        return Expr(base + " + p.semantic_weight * (utility / deadline) * reliability * fidelity))")
    raise ValueError(policy)


def _routing_rule(policy: str) -> Rule:
    return Rule(
        "route-task",
        PatternGraph(
            (
                PatternVertex("ue", "UE"), PatternVertex("gnb", "GNB"),
                PatternVertex("edge", "EdgeNode", {
                    "available": True, "load": Var("load"), "capacity": Var("capacity"),
                    "service_rate": Var("service_rate"), "reliability": Var("reliability"),
                    "fidelity": Var("fidelity"), "energy_cost": Var("energy_cost"),
                }),
                PatternVertex("task", "Task", {
                    "utility": Var("utility"), "payload_size": Var("task_payload"),
                    "deadline": Var("deadline"), "status": "queued",
                }),
            ),
            (
                PatternEdge("association", "Association", {"ue": ("ue",)}, {"gnb": ("gnb",)}),
                PatternEdge("path", "Path", {"gnb": ("gnb",)}, {"edge": ("edge",)}, {"link_quality": Var("link_quality")}),
                PatternEdge("queue", "Queued", {"source": ("ue",)}, {"task": ("task",)}),
            ),
        ),
        TemplateGraph(
            (
                TemplateVertex("ue", "UE"), TemplateVertex("gnb", "GNB"),
                TemplateVertex("edge", "EdgeNode", {"load": Expr("load + 1")}),
                TemplateVertex("task", "Task", {"status": "inflight"}),
            ),
            (
                TemplateEdge("association", "Association", {"ue": ("ue",)}, {"gnb": ("gnb",)}),
                TemplateEdge("path", "Path", {"gnb": ("gnb",)}, {"edge": ("edge",)}),
                TemplateEdge("transit", "Transit", {"source": ("ue",)}, {"task": ("task",), "gnb": ("gnb",), "edge": ("edge",)}),
            ),
        ),
        _route_hazard(policy), guard=Expr("load < capacity"), meta={"policy": policy},
    )


def _completion_rule() -> Rule:
    return Rule(
        "complete-task",
        PatternGraph(
            (
                PatternVertex("ue", "UE"), PatternVertex("gnb", "GNB"),
                PatternVertex("edge", "EdgeNode", {
                    "available": True, "load": Var("load"), "service_rate": Var("service_rate"),
                    "reliability": Var("reliability"), "fidelity": Var("fidelity"), "energy_cost": Var("energy_cost"),
                }),
                PatternVertex("task", "Task", {
                    "kind": Var("task_kind"), "utility": Var("utility"), "payload_size": Var("task_payload"),
                    "deadline": Var("deadline"), "born": Var("born"), "status": "inflight",
                }),
            ),
            (
                PatternEdge("path", "Path", {"gnb": ("gnb",)}, {"edge": ("edge",)}, {"link_quality": Var("link_quality")}),
                PatternEdge("transit", "Transit", {"source": ("ue",)}, {"task": ("task",), "gnb": ("gnb",), "edge": ("edge",)}),
            ),
        ),
        TemplateGraph(
            (TemplateVertex("ue", "UE"), TemplateVertex("gnb", "GNB"), TemplateVertex("edge", "EdgeNode", {"load": Expr("load - 1")}),),
            (TemplateEdge("path", "Path", {"gnb": ("gnb",)}, {"edge": ("edge",)}),),
        ),
        Expr("service_rate * reliability * link_quality / (task_payload * (1.0 + p.congestion_penalty * max(0, load - 1)))"),
        guard=Expr("load > 0"),
        adaptation=(
            StateAssignment("memory.delivered", Expr("z.delivered + 1")),
            StateAssignment("memory.timely_critical", Expr("z.timely_critical + (1 if task_kind == 'critical' and (time - born) <= deadline else 0)")),
            StateAssignment("memory.timely_semantic_utility", Expr("z.timely_semantic_utility + (utility * fidelity * link_quality if (time - born) <= deadline else 0.0)")),
            StateAssignment("memory.energy", Expr("z.energy + task_payload * energy_cost")),
            StateAssignment("memory.latency_sum", Expr("z.latency_sum + (time - born)")),
        ),
    )


def _reroute_rule() -> Rule:
    return Rule(
        "reroute-failed-edge",
        PatternGraph(
            (
                PatternVertex("ue", "UE"), PatternVertex("gnb", "GNB"),
                PatternVertex("edge", "EdgeNode", {"available": False, "load": Var("load")}),
                PatternVertex("task", "Task", {"status": "inflight", "reroutes": Var("reroutes")}),
            ),
            (
                PatternEdge("path", "Path", {"gnb": ("gnb",)}, {"edge": ("edge",)}),
                PatternEdge("transit", "Transit", {"source": ("ue",)}, {"task": ("task",), "gnb": ("gnb",), "edge": ("edge",)}),
            ),
        ),
        TemplateGraph(
            (
                TemplateVertex("ue", "UE"), TemplateVertex("gnb", "GNB"),
                TemplateVertex("edge", "EdgeNode", {"load": Expr("load - 1")}),
                TemplateVertex("task", "Task", {"status": "queued", "reroutes": Expr("reroutes + 1")}),
            ),
            (
                TemplateEdge("path", "Path", {"gnb": ("gnb",)}, {"edge": ("edge",)}),
                TemplateEdge("queue", "Queued", {"source": ("ue",)}, {"task": ("task",)}),
            ),
        ),
        Expr("p.reroute_rate"), guard=Expr("load > 0"),
        adaptation=(StateAssignment("memory.reroutes", Expr("z.reroutes + 1")),),
    )


def _handover_rule() -> Rule:
    return Rule(
        "handover",
        PatternGraph(
            (PatternVertex("ue", "UE", {"mobility_rate": Var("mobility_rate")}), PatternVertex("old", "GNB"), PatternVertex("new", "GNB")),
            (PatternEdge("association", "Association", {"ue": ("ue",)}, {"gnb": ("old",)}), PatternEdge("neighbor", "Neighbor", {"from_gnb": ("old",)}, {"to_gnb": ("new",)})),
        ),
        TemplateGraph(
            (TemplateVertex("ue", "UE"), TemplateVertex("old", "GNB"), TemplateVertex("new", "GNB")),
            (PatternEdge if False else TemplateEdge("neighbor", "Neighbor", {"from_gnb": ("old",)}, {"to_gnb": ("new",)}), TemplateEdge("new_association", "Association", {"ue": ("ue",)}, {"gnb": ("new",)})),
        ),
        Expr("mobility_rate"), adaptation=(StateAssignment("memory.handovers", Expr("z.handovers + 1")),),
    )


def _edge_failure_rule() -> Rule:
    return Rule(
        "edge-failure",
        PatternGraph((PatternVertex("edge", "EdgeNode", {"available": True, "down_hazard": Var("down_hazard")}),)),
        TemplateGraph((TemplateVertex("edge", "EdgeNode", {"available": False}),)),
        Expr("down_hazard"),
        adaptation=(StateAssignment("memory.outages", Expr("z.outages + 1")),),
    )


def _edge_recovery_rule() -> Rule:
    return Rule(
        "edge-recovery",
        PatternGraph((PatternVertex("edge", "EdgeNode", {"available": False, "up_hazard": Var("up_hazard")}),)),
        TemplateGraph((TemplateVertex("edge", "EdgeNode", {"available": True}),)),
        Expr("up_hazard"),
        adaptation=(StateAssignment("memory.recoveries", Expr("z.recoveries + 1")),),
    )


def build_model(policy: str, cfg: TwinConfig, fast0: np.ndarray, robust0: np.ndarray) -> Model:
    schema = build_schema()
    graph = Hypergraph(schema, namespace=0x1A11)
    ga = graph.add_vertex("GNB", {"name": "gNB-A"})
    gb = graph.add_vertex("GNB", {"name": "gNB-B"})
    fast = graph.add_vertex("EdgeNode", {
        "name": "MEC-fast", "available": True, "load": 0, "capacity": 6,
        "service_rate": float(fast0[0]), "down_hazard": float(fast0[1]), "up_hazard": float(fast0[2]),
        "reliability": 0.945, "fidelity": 0.925, "energy_cost": 1.00,
    })
    robust = graph.add_vertex("EdgeNode", {
        "name": "MEC-robust", "available": True, "load": 0, "capacity": 3,
        "service_rate": float(robust0[0]), "down_hazard": float(robust0[1]), "up_hazard": float(robust0[2]),
        "reliability": 0.997, "fidelity": 0.990, "energy_cost": 1.18,
    })
    graph.add_edge("Neighbor", {"from_gnb": (ga.entity_id,)}, {"to_gnb": (gb.entity_id,)})
    graph.add_edge("Neighbor", {"from_gnb": (gb.entity_id,)}, {"to_gnb": (ga.entity_id,)})
    for gnb, edge, name, q in [(ga, fast, "A-fast", 1.0), (ga, robust, "A-robust", .90), (gb, fast, "B-fast", .84), (gb, robust, "B-robust", 1.0)]:
        graph.add_edge("Path", {"gnb": (gnb.entity_id,)}, {"edge": (edge.entity_id,)}, {"link_quality": q, "name": name})
    for i in range(cfg.n_ues):
        ue = graph.add_vertex("UE", {"name": f"robot-{i}", "critical_rate": cfg.critical_rate_per_ue, "background_rate": cfg.background_rate_per_ue, "mobility_rate": cfg.mobility_rate_per_ue})
        g = ga if i % 2 == 0 else gb
        graph.add_edge("Association", {"ue": (ue.entity_id,)}, {"gnb": (g.entity_id,)})

    payload_schema = {
        "service_rate": _f(minimum=0.0), "down_hazard": _f(minimum=0.0), "up_hazard": _f(minimum=0.0)
    }
    boundary = BoundaryState({
        "fast-hazards": BoundaryHandle("fast-hazards", BoundaryDirection.INPUT, "EdgeNode", binding=fast.entity_id, payload_schema=payload_schema, input_mode=InputMode.MERGE_BOUND_VERTEX_ATTRIBUTES),
        "robust-hazards": BoundaryHandle("robust-hazards", BoundaryDirection.INPUT, "EdgeNode", binding=robust.entity_id, payload_schema=payload_schema, input_mode=InputMode.MERGE_BOUND_VERTEX_ATTRIBUTES),
    })
    params = {
        "arrival_scale": 1.0,
        "critical_payload": cfg.critical_payload, "background_payload": cfg.background_payload,
        "critical_utility": cfg.critical_utility, "background_utility": cfg.background_utility,
        "critical_deadline": cfg.critical_deadline, "background_deadline": cfg.background_deadline,
        "route_rate": cfg.route_rate, "reroute_rate": cfg.reroute_rate, "congestion_penalty": cfg.congestion_penalty,
        "choice_beta": 0.80, "service_scale": 7.0, "speed_weight": 1.25, "link_weight": .45,
        "load_weight": 1.20, "energy_weight": .18, "reliability_weight": .85, "fidelity_weight": .65,
        "semantic_weight": 2.20,
    }
    memory = {"generated":0,"generated_critical":0,"generated_utility":0.0,"delivered":0,"timely_critical":0,"timely_semantic_utility":0.0,"energy":0.0,"latency_sum":0.0,"outages":0,"recoveries":0,"reroutes":0,"handovers":0}
    rules = (_generation_rule("critical"), _generation_rule("background"), _routing_rule(policy), _completion_rule(), _reroute_rule(), _handover_rule(), _edge_failure_rule(), _edge_recovery_rule())
    return Model(graph, boundary, rules, parameters=params, memory=memory, model_id=f"liquid-6g-{policy}", version="1.0.0")


def _schedule_updates(runtime: Runtime, times: np.ndarray, rates: np.ndarray, handle: str, source: str, offset: int) -> None:
    horizon = runtime.config.max_simulation_time
    for i in range(1, len(times)):
        t = float(times[i])
        if not math.isfinite(t) or t > horizon:
            continue
        r = np.clip(rates[i], 0.0, 50.0)
        runtime.inject(ExternalEvent(t, source, offset+i, f"{source}-{i}", handle, {"service_rate": float(r[0]), "down_hazard": float(r[1]), "up_hazard": float(r[2])}))


def run_twin(
    *, hazard_model: str, regime: str, policy: str, scenario: int, replicate: int,
    fast_times: np.ndarray, fast_rates: np.ndarray, robust_times: np.ndarray, robust_rates: np.ndarray,
    root_seed: int, cfg: TwinConfig | None = None, verify_incremental: bool = False, seed_context: str | None = None,
) -> TwinMetrics:
    cfg = cfg or TwinConfig()
    model = build_model(policy, cfg, fast_rates[0], robust_rates[0])
    seed_key = seed_context if seed_context is not None else regime
    seed = derive_seed(root_seed, f"liquid6g:{seed_key}:{scenario}:{replicate}")  # common-random-number coupling across model/policy arms
    runtime = Runtime(model, root_seed=seed, config=RuntimeConfig(
        scheduler=SchedulerKind.NEXT_REACTION, matcher_backend="incremental", incremental_verify=verify_incremental,
        max_events=150_000, max_simulation_time=cfg.horizon,
    ))
    _schedule_updates(runtime, fast_times, fast_rates, "fast-hazards", f"fast-{scenario}", 1000)
    _schedule_updates(runtime, robust_times, robust_rates, "robust-hazards", f"robust-{scenario}", 5000)
    runtime.schedule_adaptation(ScheduledAdaptation(cfg.arrivals_stop, 1, "stop-arrivals", (StateAssignment("parameters.arrival_scale", 0.0),)))
    runtime.run_until_time(cfg.horizon)
    z = runtime.memory
    gen = int(z["generated"]); gen_crit = int(z["generated_critical"]); delivered = int(z["delivered"])
    return TwinMetrics(
        hazard_model=hazard_model, regime=regime, policy=policy, scenario=scenario, replicate=replicate,
        seed=seed, events=runtime.event_index, generated=gen, delivered=delivered,
        timely_critical=int(z["timely_critical"]), generated_critical=gen_crit,
        goal_utility_ratio=float(z["timely_semantic_utility"])/max(float(z["generated_utility"]),1e-12),
        critical_success_rate=float(z["timely_critical"])/max(gen_crit,1),
        mean_latency=float(z["latency_sum"])/max(delivered,1), energy=float(z["energy"]),
        outages=int(z["outages"]), recoveries=int(z["recoveries"]), reroutes=int(z["reroutes"]), handovers=int(z["handovers"]),
        final_queued=len(runtime.graph.edges_by_type["Queued"]), final_inflight=len(runtime.graph.edges_by_type["Transit"]), state_hash=runtime.state_hash,
    )
