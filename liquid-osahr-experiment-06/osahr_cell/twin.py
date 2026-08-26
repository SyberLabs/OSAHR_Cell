"""6G-like twin for Experiment 06. Extends the 6G schema; does not edit osahr/schema.py."""
from __future__ import annotations

import sys
from dataclasses import replace
from typing import Any

from osahr import (
    AttributeSpec,
    BoundaryDirection,
    BoundaryHandle,
    BoundaryState,
    Expr,
    ExternalEvent,
    Hypergraph,
    InputMode,
    Model,
    PatternEdge,
    PatternGraph,
    PatternVertex,
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
from osahr.matcher import Matcher
from osahr.rng import derive_seed

from .anlf import AbnormalBehavior, kpm_outage_series
from .junction import compiled_route_guard
from .protocol import (
    BRAIN_LOAD_WEIGHT,
    G6_RELEASE,
    HORIZON,
    JUNCTION_RULE_ID,
    ORACLE_CHOICE_BETA,
    RESIDUAL_LOAD_WEIGHT,
)
from .vault import SemanticVault


def _g6():
    path = str(G6_RELEASE)
    if path not in sys.path:
        sys.path.insert(0, path)
    import semantic_6g_twin_experiment as module

    return module


def experiment_schema() -> Schema:
    """6G schema plus optional Task.concept_id. Kernel schema.py is untouched."""
    base = _g6().build_schema()
    vertices: list[VertexType] = []
    for type_id, vertex in base.vertex_types.items():
        if type_id != "Task":
            vertices.append(vertex)
            continue
        attributes = dict(vertex.attributes)
        attributes["concept_id"] = AttributeSpec(
            ValueKind.STRING, required=False, default=""
        )
        vertices.append(
            VertexType(
                "Task",
                attributes,
                parents=vertex.parents,
                allow_extensions=vertex.allow_extensions,
                invariants=vertex.invariants,
            )
        )
    return Schema(
        vertices,
        list(base.edge_types.values()),
        schema_id="osahr-6g-exp06-vault",
        version="1.0.0",
    )


def route_hazard(
    policy: str,
    *,
    residual_alpha: float = 0.0,
    brain_hold: bool = False,
) -> Expr:
    if brain_hold:
        return Expr(
            "p.route_rate * exp(p.choice_beta * "
            "(- p.brain_load_weight * (load / capacity)))"
        )
    residual = (
        f" - {float(residual_alpha)} * p.residual_load_weight * (load / capacity)"
        if residual_alpha
        else ""
    )
    base = (
        "p.route_rate * exp(p.choice_beta * ("
        "p.speed_weight * (service_rate / p.service_scale) "
        "+ p.link_weight * link_quality "
        "- p.load_weight * (load / capacity) "
        "- p.energy_weight * energy_cost"
        f"{residual}"
    )
    if policy == "throughput":
        return Expr(base + "))")
    if policy in ("qos",):
        return Expr(
            base
            + " + p.qos_reliability_weight * reliability"
            + " + p.qos_fidelity_weight * fidelity))"
        )
    if policy in ("semantic", "scalar_semantic", "vault_gated", "oracle_vault_greedy"):
        return Expr(
            base
            + " + p.qos_reliability_weight * reliability"
            + " + p.qos_fidelity_weight * fidelity"
            + " + p.semantic_weight * (utility / deadline) * reliability * fidelity"
            + "))"
        )
    raise ValueError(policy)


def routing_rule(
    policy: str,
    vault: SemanticVault | None = None,
    *,
    residual_alpha: float = 0.0,
    brain_hold: bool = False,
    enabled: bool = True,
) -> Rule:
    hazard = route_hazard(
        "semantic" if policy in ("vault_gated", "oracle_vault_greedy", "scalar_semantic") else policy,
        residual_alpha=residual_alpha,
        brain_hold=brain_hold,
    )
    guard = compiled_route_guard(vault) if vault is not None else Expr("load < capacity")
    edge_attrs = {
        "available": True,
        "name": Var("edge_name"),
        "load": Var("load"),
        "capacity": Var("capacity"),
        "service_rate": Var("service_rate"),
        "reliability": Var("reliability"),
        "fidelity": Var("fidelity"),
        "energy_cost": Var("energy_cost"),
    }
    return Rule(
        JUNCTION_RULE_ID,
        PatternGraph(
            (
                PatternVertex("ue", "UE"),
                PatternVertex("gnb", "GNB"),
                PatternVertex("edge", "EdgeNode", edge_attrs),
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
                TemplateVertex("edge", "EdgeNode", {"load": Expr("load + 1")}),
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
        hazard,
        guard=guard,
        meta={"policy": policy, "junction": JUNCTION_RULE_ID},
        enabled=enabled,
    )


def _generation_rule(kind: str) -> Rule:
    g6 = _g6()
    rule = g6._generation_rule(kind)
    # Rebuild with concept_id on the new Task vertex.
    task_template = rule.right.vertex_map["task"]
    attributes = dict(task_template.attributes)
    attributes["concept_id"] = kind
    new_task = TemplateVertex("task", "Task", attributes)
    vertices = tuple(
        new_task if vertex.key == "task" else vertex for vertex in rule.right.vertices
    )
    return Rule(
        rule.rule_id,
        rule.left,
        TemplateGraph(vertices, rule.right.edges),
        rule.hazard,
        guard=rule.guard,
        conditions=rule.conditions,
        adaptation=rule.adaptation,
        boundary_effects=rule.boundary_effects,
        outputs=rule.outputs,
        meta=rule.meta,
        version=rule.version,
        enabled=rule.enabled,
    )


def build_experiment_model(
    policy: str,
    cfg: Any,
    vault: SemanticVault | None = None,
    *,
    residual_alpha: float = 0.0,
    brain_hold: bool = False,
    withhold_route: bool = False,
) -> tuple[Model, str]:
    schema = experiment_schema()
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
    graph.add_edge("Neighbor", {"from_gnb": (gnb_a.entity_id,)}, {"to_gnb": (gnb_b.entity_id,)})
    graph.add_edge("Neighbor", {"from_gnb": (gnb_b.entity_id,)}, {"to_gnb": (gnb_a.entity_id,)})
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

    g6 = _g6()
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
            "fast-edge-load": BoundaryHandle(
                "fast-edge-load",
                BoundaryDirection.INPUT,
                "EdgeNode",
                binding=fast.entity_id,
                payload_schema={"load": AttributeSpec(ValueKind.INT, required=True, minimum=0)},
                input_mode=InputMode.MERGE_BOUND_VERTEX_ATTRIBUTES,
            ),
        }
    )
    route = routing_rule(
        policy,
        vault,
        residual_alpha=residual_alpha,
        brain_hold=brain_hold,
        enabled=not withhold_route,
    )
    rules = (
        _generation_rule("critical"),
        _generation_rule("background"),
        route,
        g6._completion_rule(),
        g6._reroute_rule(),
        g6._handover_rule(),
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
        "choice_beta": ORACLE_CHOICE_BETA if policy == "oracle_vault_greedy" else 0.80,
        "service_scale": 8.0,
        "speed_weight": 1.25,
        "link_weight": 0.45,
        "load_weight": 1.20,
        "energy_weight": 0.18,
        "qos_reliability_weight": 1.15,
        "qos_fidelity_weight": 5.0 if policy == "oracle_vault_greedy" else 0.80,
        "semantic_weight": 3.4 if policy == "oracle_vault_greedy" else 2.20,
        "brain_load_weight": BRAIN_LOAD_WEIGHT,
        "residual_load_weight": RESIDUAL_LOAD_WEIGHT,
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
            model_id=f"6g-exp06-{policy}",
            version="1.0.0",
        ),
        str(fast.entity_id),
    )


def build_stub_runtime(
    vault: SemanticVault,
    *,
    critical_queued: bool = True,
    inflight_background: bool = True,
    root_seed: int = 7,
) -> Runtime:
    """Small graph for junction / AnLF / park tests (1 s horizon)."""
    schema = experiment_schema()
    graph = Hypergraph(schema, namespace=0x0606)
    gnb = graph.add_vertex("GNB", {"name": "gNB-A"})
    fast = graph.add_vertex(
        "EdgeNode",
        {
            "name": "MEC-fast",
            "available": True,
            "load": 0,
            "capacity": 4,
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
            "load": 1 if inflight_background else 0,
            "capacity": 3,
            "service_rate": 4.2,
            "reliability": 0.997,
            "fidelity": 0.99,
            "energy_cost": 1.18,
        },
    )
    ue = graph.add_vertex(
        "UE",
        {
            "name": "robot-0",
            "critical_rate": 0.2,
            "background_rate": 0.2,
            "mobility_rate": 0.0,
        },
    )
    graph.add_edge("Association", {"ue": (ue.entity_id,)}, {"gnb": (gnb.entity_id,)})
    graph.add_edge(
        "Path",
        {"gnb": (gnb.entity_id,)},
        {"edge": (fast.entity_id,)},
        {"link_quality": 1.0, "name": "A-fast"},
    )
    graph.add_edge(
        "Path",
        {"gnb": (gnb.entity_id,)},
        {"edge": (robust.entity_id,)},
        {"link_quality": 0.9, "name": "A-robust"},
    )
    if critical_queued:
        task = graph.add_vertex(
            "Task",
            {
                "kind": "critical",
                "concept_id": "critical",
                "utility": 1.0,
                "payload": 1.0,
                "deadline": 1.5,
                "born": 0.0,
                "status": "queued",
                "latency": -1.0,
                "delivered_fidelity": 0.0,
                "path_energy": 0.0,
                "reroutes": 0,
            },
        )
        graph.add_edge("Queued", {"source": (ue.entity_id,)}, {"task": (task.entity_id,)})
    if inflight_background:
        bg = graph.add_vertex(
            "Task",
            {
                "kind": "background",
                "concept_id": "background",
                "utility": 0.18,
                "payload": 3.0,
                "deadline": 6.0,
                "born": 0.0,
                "status": "inflight",
                "latency": -1.0,
                "delivered_fidelity": 0.0,
                "path_energy": 0.0,
                "reroutes": 0,
            },
        )
        graph.add_edge(
            "Transit",
            {"source": (ue.entity_id,)},
            {
                "task": (bg.entity_id,),
                "gnb": (gnb.entity_id,),
                "edge": (robust.entity_id,),
            },
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
            "fast-edge-load": BoundaryHandle(
                "fast-edge-load",
                BoundaryDirection.INPUT,
                "EdgeNode",
                binding=fast.entity_id,
                payload_schema={"load": AttributeSpec(ValueKind.INT, required=True, minimum=0)},
                input_mode=InputMode.MERGE_BOUND_VERTEX_ATTRIBUTES,
            ),
        }
    )
    g6 = _g6()
    model = Model(
        graph,
        boundary,
        (
            _generation_rule("critical"),
            routing_rule("vault_gated", vault),
            g6._completion_rule(),
        ),
        parameters={
            "arrival_scale": 1.0,
            "critical_payload": 1.0,
            "background_payload": 3.0,
            "critical_utility": 1.0,
            "background_utility": 0.18,
            "critical_deadline": 1.5,
            "background_deadline": 6.0,
            "route_rate": 18.0,
            "reroute_rate": 25.0,
            "congestion_penalty": 0.55,
            "choice_beta": 0.8,
            "service_scale": 8.0,
            "speed_weight": 1.25,
            "link_weight": 0.45,
            "load_weight": 1.20,
            "energy_weight": 0.18,
            "qos_reliability_weight": 1.15,
            "qos_fidelity_weight": 0.80,
            "semantic_weight": 2.20,
            "brain_load_weight": BRAIN_LOAD_WEIGHT,
            "residual_load_weight": RESIDUAL_LOAD_WEIGHT,
        },
        memory={
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
        },
        model_id="exp06-stub",
    )
    return Runtime(
        model,
        root_seed=root_seed,
        config=RuntimeConfig(scheduler=SchedulerKind.NEXT_REACTION),
    )


def junction_rule_matches(runtime: Runtime, vault: SemanticVault) -> list:
    matcher = Matcher()
    rule = runtime.rules[JUNCTION_RULE_ID]
    return matcher.find_rule_matches(
        runtime.graph,
        rule,
        parameters=runtime.parameters,
        memory=runtime.memory,
        time=runtime.time,
    )


def inject_anlf_outage(runtime: Runtime, cfg: Any, *, sequence: int = 1) -> None:
    series = kpm_outage_series(
        horizon=cfg.horizon,
        dt=1.0,
        outage_start=cfg.fast_outage_start,
        outage_end=cfg.fast_outage_end,
    )
    detector = AbnormalBehavior()
    last_available = True
    for index, value in enumerate(series):
        payload = detector.infer(series[: index + 1])
        available = bool(payload["available"])
        if available == last_available and index != 0:
            # Still emit the window edges even if CUSUM lags: force at schedule times.
            t = float(index)
            if t == cfg.fast_outage_start:
                available = False
            elif t == cfg.fast_outage_end:
                available = True
            else:
                continue
        t = float(index)
        if available != last_available:
            runtime.inject(
                ExternalEvent(
                    t,
                    "anlf-outage",
                    sequence,
                    f"anlf-outage-{sequence}-{index}",
                    "fast-edge-control",
                    {"available": available},
                )
            )
            sequence += 1
            last_available = available


def _count_edge_type(runtime: Runtime, edge_type: str) -> int:
    return len(runtime.graph.edges_by_type[edge_type])


def metrics_from_runtime(runtime: Runtime, *, policy: str, replicate: int, seed: int, cfg: Any) -> dict[str, Any]:
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
    return {
        "policy": policy,
        "replicate": replicate,
        "seed": seed,
        "events": runtime.event_index,
        "final_time": runtime.time,
        "state_hash": runtime.state_hash,
        "generated": generated,
        "generated_critical": gen_crit,
        "generated_background": gen_bg,
        "delivered": delivered,
        "delivered_critical": int(z["delivered_critical"]),
        "delivered_background": int(z["delivered_background"]),
        "timely": timely,
        "timely_critical": timely_crit,
        "timely_background": timely_bg,
        "generated_utility": gen_utility,
        "delivered_utility": float(z["delivered_utility"]),
        "timely_semantic_utility": timely_utility,
        "energy": energy,
        "bytes_delivered": float(z["bytes_delivered"]),
        "reroutes": int(z["reroutes"]),
        "handovers": int(z["handovers"]),
        "mean_latency": (float(z["latency_sum"]) / delivered) if delivered else 0.0,
        "critical_success_rate": (timely_crit / gen_crit) if gen_crit else 0.0,
        "background_success_rate": (timely_bg / gen_bg) if gen_bg else 0.0,
        "timely_task_rate": (timely / generated) if generated else 0.0,
        "goal_utility_ratio": (timely_utility / gen_utility) if gen_utility else 0.0,
        "semantic_efficiency": (timely_utility / energy) if energy else 0.0,
        "horizon": cfg.horizon,
    }


def run_arm(
    policy: str,
    replicate: int,
    root_seed: int,
    cfg: Any,
    vault: SemanticVault | None = None,
    *,
    residual_alpha: float = 0.0,
    claim_status: str | None = None,
) -> dict[str, Any]:
    withhold = claim_status in ("reject", "outcome_unknown") and policy == "brain_at_hold"
    brain_hold = claim_status == "hold_unresolved" and policy == "brain_at_hold"
    use_vault = vault if policy in ("vault_gated", "brain_at_hold", "oracle_vault_greedy") else None
    hazard_policy = "semantic" if policy == "brain_at_hold" else policy
    model, _ = build_experiment_model(
        hazard_policy,
        cfg,
        use_vault,
        residual_alpha=residual_alpha,
        brain_hold=brain_hold,
        withhold_route=withhold,
    )
    seed = derive_seed(root_seed, f"6g06:{policy}:{replicate}")
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
    inject_anlf_outage(runtime, cfg)
    runtime.schedule_adaptation(
        ScheduledAdaptation(
            cfg.arrivals_stop,
            1,
            "stop-arrivals",
            (StateAssignment("parameters.arrival_scale", 0.0),),
        )
    )
    while runtime.time < cfg.horizon:
        next_time = runtime.peek_next_event_time()
        if next_time is None or next_time > cfg.horizon:
            runtime.run_until_time(cfg.horizon)
            break
        runtime.step()
    row = metrics_from_runtime(runtime, policy=policy, replicate=replicate, seed=seed, cfg=cfg)
    row["claim_status"] = claim_status
    row["residual_alpha"] = residual_alpha
    return row


def default_config(**overrides: Any):
    cfg = _g6().ExperimentConfig(horizon=HORIZON)
    if overrides:
        cfg = replace(cfg, **overrides)
    return cfg
