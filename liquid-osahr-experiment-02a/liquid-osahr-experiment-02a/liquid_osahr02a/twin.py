"""Typed 6G/MEC OSAHR model used by closed-loop Liquid-OSAHR Experiment 02A."""
from __future__ import annotations

from dataclasses import dataclass

from osahr import (  # type: ignore
    AttributeSpec, BoundaryState, Expr, HyperedgeType, Hypergraph, Model,
    PatternEdge, PatternGraph, PatternVertex, PortSpec, Rule, Schema,
    StateAssignment, TemplateEdge, TemplateGraph, TemplateVertex, ValueKind,
    Var, VertexType,
)

from .field import HazardBounds, PersistentIndex, Scenario


POLICIES=("throughput","semantic")


@dataclass(frozen=True)
class TwinConfig:
    horizon: float = 22.0
    n_ues: int = 4
    critical_rate_per_ue: float = 0.17
    background_rate_per_ue: float = 0.34
    route_rate: float = 14.0
    reroute_rate: float = 22.0
    congestion_penalty: float = 0.52
    critical_payload: float = 1.0
    background_payload: float = 2.4
    critical_utility: float = 1.0
    background_utility: float = 0.16
    critical_deadline: float = 1.6
    background_deadline: float = 6.0


def _f(required=True, minimum=None, maximum=None): return AttributeSpec(ValueKind.FLOAT,required=required,minimum=minimum,maximum=maximum)
def _i(required=True, minimum=None, maximum=None): return AttributeSpec(ValueKind.INT,required=required,minimum=minimum,maximum=maximum)


def build_schema()->Schema:
    return Schema(
        [
            VertexType("UE",{
                "name":AttributeSpec(ValueKind.STRING),
                "critical_rate":_f(minimum=0.0),"background_rate":_f(minimum=0.0),
            }),
            VertexType("GNB",{"name":AttributeSpec(ValueKind.STRING)}),
            VertexType("EdgeNode",{
                "name":AttributeSpec(ValueKind.STRING),"available":AttributeSpec(ValueKind.BOOL),
                "load":_i(minimum=0),"capacity":_i(minimum=1),
                "reliability":_f(minimum=0.0,maximum=1.0),"fidelity":_f(minimum=0.0,maximum=1.0),
                "energy_cost":_f(minimum=0.0),"profile":AttributeSpec(ValueKind.STRING,choices=frozenset({"fast","robust"})),
            }),
            VertexType("Task",{
                "kind":AttributeSpec(ValueKind.STRING,choices=frozenset({"critical","background"})),
                "utility":_f(minimum=0.0),"payload_size":_f(minimum=0.0),"deadline":_f(minimum=0.0),"born":_f(minimum=0.0),
                "status":AttributeSpec(ValueKind.STRING,choices=frozenset({"queued","inflight"})),"reroutes":_i(minimum=0),
            }),
        ],
        [
            HyperedgeType("Association",{"ue":PortSpec("ue","UE")},{"gnb":PortSpec("gnb","GNB")}),
            HyperedgeType("Neighbor",{"from_gnb":PortSpec("from_gnb","GNB")},{"to_gnb":PortSpec("to_gnb","GNB")}),
            HyperedgeType("Path",{"gnb":PortSpec("gnb","GNB")},{"edge":PortSpec("edge","EdgeNode")},{"link_quality":_f(minimum=0.0,maximum=1.0),"name":AttributeSpec(ValueKind.STRING)}),
            HyperedgeType("Queued",{"source":PortSpec("source","UE")},{"task":PortSpec("task","Task")}),
            HyperedgeType("Transit",{"source":PortSpec("source","UE")},{"task":PortSpec("task","Task"),"gnb":PortSpec("gnb","GNB"),"edge":PortSpec("edge","EdgeNode")}),
        ],
        schema_id="liquid-osahr-02a-6g",version="1.0.0",
    )


def _generation_rule(kind:str)->Rule:
    if kind=="critical": rate_var,payload,utility,deadline="critical_rate","p.critical_payload","p.critical_utility","p.critical_deadline"
    else: rate_var,payload,utility,deadline="background_rate","p.background_payload","p.background_utility","p.background_deadline"
    return Rule(
        f"generate-{kind}",PatternGraph((PatternVertex("ue","UE",{rate_var:Var("arrival_rate")}),)),
        TemplateGraph(
            (TemplateVertex("ue","UE"),TemplateVertex("task","Task",{"kind":kind,"utility":Expr(utility),"payload_size":Expr(payload),"deadline":Expr(deadline),"born":Expr("time"),"status":"queued","reroutes":0})),
            (TemplateEdge("queue","Queued",{"source":('ue',)},{"task":('task',)}),),
        ),
        Expr("arrival_rate"),
        adaptation=(
            StateAssignment("memory.generated",Expr("z.generated+1")),
            StateAssignment("memory.generated_critical",Expr("z.generated_critical+(1 if meta.kind=='critical' else 0)")),
            StateAssignment("memory.generated_utility",Expr(f"z.generated_utility+{utility}")),
        ),meta={"kind":kind},
    )


def _route_hazard(policy:str)->Expr:
    # Routing is deliberately explicit/mechanistic rather than neural.  This
    # lets Experiment 02A test physical-twin fidelity under interventions.
    base=("p.route_rate*exp(p.choice_beta*(p.link_weight*link_quality-p.load_weight*(load/capacity)-p.energy_weight*energy_cost+p.reliability_weight*reliability+p.fidelity_weight*fidelity")
    if policy=="throughput": return Expr(base+"))")
    return Expr(base+"+p.semantic_weight*(utility/deadline)*reliability*fidelity))")


def _routing_rule(policy:str)->Rule:
    return Rule(
        "route-task",
        PatternGraph(
            (PatternVertex("ue","UE"),PatternVertex("gnb","GNB"),PatternVertex("edge","EdgeNode",{"available":True,"load":Var("load"),"capacity":Var("capacity"),"reliability":Var("reliability"),"fidelity":Var("fidelity"),"energy_cost":Var("energy_cost")}),PatternVertex("task","Task",{"utility":Var("utility"),"deadline":Var("deadline"),"status":"queued"})),
            (PatternEdge("association","Association",{"ue":('ue',)},{"gnb":('gnb',)}),PatternEdge("path","Path",{"gnb":('gnb',)},{"edge":('edge',)},{"link_quality":Var("link_quality")}),PatternEdge("queue","Queued",{"source":('ue',)},{"task":('task',)})),
        ),
        TemplateGraph(
            (TemplateVertex("ue","UE"),TemplateVertex("gnb","GNB"),TemplateVertex("edge","EdgeNode",{"load":Expr("load+1")}),TemplateVertex("task","Task",{"status":"inflight"})),
            (TemplateEdge("association","Association",{"ue":('ue',)},{"gnb":('gnb',)}),TemplateEdge("path","Path",{"gnb":('gnb',)},{"edge":('edge',)}),TemplateEdge("transit","Transit",{"source":('ue',)},{"task":('task',),"gnb":('gnb',),"edge":('edge',)})),
        ),_route_hazard(policy),guard=Expr("load<capacity"),meta={"policy":policy},
    )


def _completion_rule(bounds:HazardBounds)->Rule:
    return Rule(
        "complete-task",
        PatternGraph(
            (PatternVertex("ue","UE"),PatternVertex("gnb","GNB"),PatternVertex("edge","EdgeNode",{"available":True,"load":Var("load"),"reliability":Var("reliability"),"fidelity":Var("fidelity"),"energy_cost":Var("energy_cost")}),PatternVertex("task","Task",{"kind":Var("task_kind"),"utility":Var("utility"),"payload_size":Var("task_payload"),"deadline":Var("deadline"),"born":Var("born"),"status":"inflight"})),
            (PatternEdge("path","Path",{"gnb":('gnb',)},{"edge":('edge',)},{"link_quality":Var("link_quality")}),PatternEdge("transit","Transit",{"source":('ue',)},{"task":('task',),"gnb":('gnb',),"edge":('edge',)})),
        ),
        TemplateGraph((TemplateVertex("ue","UE"),TemplateVertex("gnb","GNB"),TemplateVertex("edge","EdgeNode",{"load":Expr("load-1")})),(TemplateEdge("path","Path",{"gnb":('gnb',)},{"edge":('edge',)}),)),
        Expr("0.0+0.0*time"),guard=Expr("load>0"),hazard_upper_bound=Expr(str(bounds.service)),
        adaptation=(
            StateAssignment("memory.delivered",Expr("z.delivered+1")),
            StateAssignment("memory.timely_critical",Expr("z.timely_critical+(1 if task_kind=='critical' and (time-born)<=deadline else 0)")),
            StateAssignment("memory.timely_semantic_utility",Expr("z.timely_semantic_utility+(utility*fidelity*link_quality if (time-born)<=deadline else 0.0)")),
            StateAssignment("memory.energy",Expr("z.energy+task_payload*energy_cost")),StateAssignment("memory.latency_sum",Expr("z.latency_sum+(time-born)")),
        ),meta={"liquid_head":"service"},
    )


def _reroute_rule()->Rule:
    return Rule(
        "reroute-failed-edge",
        PatternGraph((PatternVertex("ue","UE"),PatternVertex("gnb","GNB"),PatternVertex("edge","EdgeNode",{"available":False,"load":Var("load")}),PatternVertex("task","Task",{"status":"inflight","reroutes":Var("reroutes")})),(PatternEdge("path","Path",{"gnb":('gnb',)},{"edge":('edge',)}),PatternEdge("transit","Transit",{"source":('ue',)},{"task":('task',),"gnb":('gnb',),"edge":('edge',)}))),
        TemplateGraph((TemplateVertex("ue","UE"),TemplateVertex("gnb","GNB"),TemplateVertex("edge","EdgeNode",{"load":Expr("load-1")}),TemplateVertex("task","Task",{"status":"queued","reroutes":Expr("reroutes+1")})),(TemplateEdge("path","Path",{"gnb":('gnb',)},{"edge":('edge',)}),TemplateEdge("queue","Queued",{"source":('ue',)},{"task":('task',)}))),
        Expr("p.reroute_rate"),guard=Expr("load>0"),adaptation=(StateAssignment("memory.reroutes",Expr("z.reroutes+1")),),
    )


def _handover_rule(bounds:HazardBounds)->Rule:
    return Rule(
        "handover",
        PatternGraph((PatternVertex("ue","UE"),PatternVertex("old","GNB"),PatternVertex("new","GNB")),(PatternEdge("association","Association",{"ue":('ue',)},{"gnb":('old',)}),PatternEdge("neighbor","Neighbor",{"from_gnb":('old',)},{"to_gnb":('new',)}))),
        TemplateGraph((TemplateVertex("ue","UE"),TemplateVertex("old","GNB"),TemplateVertex("new","GNB")),(TemplateEdge("neighbor","Neighbor",{"from_gnb":('old',)},{"to_gnb":('new',)}),TemplateEdge("new_association","Association",{"ue":('ue',)},{"gnb":('new',)}))),
        Expr("0.0+0.0*time"),hazard_upper_bound=Expr(str(bounds.handover)),adaptation=(StateAssignment("memory.handovers",Expr("z.handovers+1")),),meta={"liquid_head":"handover"},
    )


def _failure_rule(bounds:HazardBounds)->Rule:
    return Rule("edge-failure",PatternGraph((PatternVertex("edge","EdgeNode",{"available":True}),)),TemplateGraph((TemplateVertex("edge","EdgeNode",{"available":False}),)),Expr("0.0+0.0*time"),hazard_upper_bound=Expr(str(bounds.failure)),adaptation=(StateAssignment("memory.outages",Expr("z.outages+1")),),meta={"liquid_head":"failure"})

def _recovery_rule(bounds:HazardBounds)->Rule:
    return Rule("edge-recovery",PatternGraph((PatternVertex("edge","EdgeNode",{"available":False}),)),TemplateGraph((TemplateVertex("edge","EdgeNode",{"available":True}),)),Expr("0.0+0.0*time"),hazard_upper_bound=Expr(str(bounds.recovery)),adaptation=(StateAssignment("memory.recoveries",Expr("z.recoveries+1")),),meta={"liquid_head":"recovery"})


def build_model(policy:str,scenario:Scenario,cfg:TwinConfig|None=None,bounds:HazardBounds|None=None)->tuple[Model,PersistentIndex]:
    if policy not in POLICIES: raise ValueError(policy)
    cfg=cfg or TwinConfig(); bounds=bounds or HazardBounds(); schema=build_schema(); graph=Hypergraph(schema,namespace=0x2A02)
    ga=graph.add_vertex("GNB",{"name":"gNB-A"}); gb=graph.add_vertex("GNB",{"name":"gNB-B"})
    fast=graph.add_vertex("EdgeNode",{"name":"MEC-fast","available":True,"load":0,"capacity":5,"reliability":0.946,"fidelity":0.928,"energy_cost":1.00,"profile":"fast"})
    robust=graph.add_vertex("EdgeNode",{"name":"MEC-robust","available":True,"load":0,"capacity":3,"reliability":0.997,"fidelity":0.992,"energy_cost":1.18,"profile":"robust"})
    graph.add_edge("Neighbor",{"from_gnb":(ga.entity_id,)},{"to_gnb":(gb.entity_id,)})
    graph.add_edge("Neighbor",{"from_gnb":(gb.entity_id,)},{"to_gnb":(ga.entity_id,)})
    for g,e,name,q in [(ga,fast,"A-fast",1.0),(ga,robust,"A-robust",.90),(gb,fast,"B-fast",.84),(gb,robust,"B-robust",1.0)]: graph.add_edge("Path",{"gnb":(g.entity_id,)},{"edge":(e.entity_id,)},{"link_quality":q,"name":name})
    for i in range(cfg.n_ues):
        ue=graph.add_vertex("UE",{"name":f"robot-{i}","critical_rate":cfg.critical_rate_per_ue*scenario.demand,"background_rate":cfg.background_rate_per_ue*scenario.demand})
        g=ga if i%2==0 else gb; graph.add_edge("Association",{"ue":(ue.entity_id,)},{"gnb":(g.entity_id,)})
    index=PersistentIndex.from_graph(graph)
    params={
        "critical_payload":cfg.critical_payload,"background_payload":cfg.background_payload,"critical_utility":cfg.critical_utility,"background_utility":cfg.background_utility,"critical_deadline":cfg.critical_deadline,"background_deadline":cfg.background_deadline,
        "route_rate":cfg.route_rate,"reroute_rate":cfg.reroute_rate,"congestion_penalty":cfg.congestion_penalty,
        "choice_beta":0.72,"link_weight":.55,"load_weight":1.20,"energy_weight":.16,"reliability_weight":.70,"fidelity_weight":.55,"semantic_weight":2.15,
        "max_service":bounds.service,"max_failure":bounds.failure,"max_recovery":bounds.recovery,"max_handover":bounds.handover,
    }
    memory={"generated":0,"generated_critical":0,"generated_utility":0.0,"delivered":0,"timely_critical":0,"timely_semantic_utility":0.0,"energy":0.0,"latency_sum":0.0,"outages":0,"recoveries":0,"reroutes":0,"handovers":0}
    rules=(_generation_rule("critical"),_generation_rule("background"),_routing_rule(policy),_completion_rule(bounds),_reroute_rule(),_handover_rule(bounds),_failure_rule(bounds),_recovery_rule(bounds))
    model=Model(graph,BoundaryState({}),rules,parameters=params,memory=memory,model_id=f"liquid-osahr-02a-{policy}",version="1.0.0")
    return model,index
