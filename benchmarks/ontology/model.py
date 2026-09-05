"""Strict local RDF projection and a small, explicit OSAHR model compiler."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, URIRef

from osahr import (
    AttributeSpec, BoundaryState, Expr, HyperedgeType, Hypergraph, Model,
    PatternEdge, PatternGraph, PatternVertex, PortSpec, Rule, Schema,
    TemplateEdge, TemplateGraph, TemplateVertex, ValueKind, Var, VertexType,
)

EX = Namespace("urn:syberlabs:benchmark:")
FIXTURE = Path(__file__).with_name("routes.ttl")


@dataclass(frozen=True)
class Route:
    uri: str
    source: str
    target: str
    up: bool
    failure: float
    repair: float


@dataclass(frozen=True)
class Snapshot:
    sites: tuple[str, ...]
    routes: tuple[Route, ...]

    @property
    def initial(self) -> tuple[bool, ...]:
        return tuple(route.up for route in self.routes)


def load_snapshot(path: Path = FIXTURE) -> Snapshot:
    # Read approved local bytes only. Never dereference ontology URIs or accept
    # arbitrary parser formats/remote JSON-LD contexts in this probe.
    graph = Graph().parse(data=path.read_text(encoding="utf-8"), format="turtle")
    sites = set(graph.subjects(RDF.type, EX.Site))
    routes = set(graph.subjects(RDF.type, EX.Route))
    if not sites or not routes or sites & routes:
        raise ValueError("Need disjoint, nonempty Site and Route sets")
    known = sites | routes
    if any(not isinstance(node, URIRef) for node in known):
        raise ValueError("Entities require URI identities; blank nodes are unsupported")
    properties = {EX.source, EX.target, EX.up, EX.failureRate, EX.repairRate}
    for subject, predicate, obj in graph:
        if subject not in known:
            raise ValueError("Unsupported subject")
        if predicate == RDF.type:
            if obj not in {EX.Site, EX.Route}:
                raise ValueError("Unsupported type")
        elif subject not in routes or predicate not in properties:
            raise ValueError("Unsupported property; projection must not silently drop data")

    def one(subject: URIRef, predicate: URIRef):
        values = list(graph.objects(subject, predicate))
        if len(values) != 1:
            raise ValueError(f"{subject} requires exactly one {predicate}")
        return values[0]

    projected = []
    for uri in sorted(routes, key=str):
        source, target = one(uri, EX.source), one(uri, EX.target)
        if source not in sites or target not in sites or source == target:
            raise ValueError("Endpoints must be distinct, declared Sites")
        up = one(uri, EX.up)
        if not isinstance(up, Literal) or type(up.toPython()) is not bool:
            raise ValueError("up must be a typed boolean")
        rates = []
        for prop in (EX.failureRate, EX.repairRate):
            value = one(uri, prop)
            if not isinstance(value, Literal) or isinstance(value.toPython(), (str, bool)):
                raise ValueError("Rates must be numeric literals")
            try:
                rate = float(value.toPython())
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Rates must be numeric literals") from exc
            if not math.isfinite(rate) or rate < 0:
                raise ValueError("Rates must be finite and nonnegative")
            rates.append(rate)
        projected.append(Route(str(uri), str(source), str(target), up.toPython(), *rates))
    return Snapshot(tuple(sorted(map(str, sites))), tuple(projected))


def replicate(snapshot: Snapshot, copies: int) -> Snapshot:
    """Disjoint copies scale size without silently changing the stochastic law."""
    if copies < 1:
        raise ValueError("copies must be positive")
    sites, routes = [], []
    for index in range(copies):
        names = {uri: f"{uri}:copy{index}" for uri in snapshot.sites}
        sites.extend(names.values())
        routes.extend(replace(r, uri=f"{r.uri}:copy{index}", source=names[r.source],
                              target=names[r.target]) for r in snapshot.routes)
    return Snapshot(tuple(sorted(sites)), tuple(sorted(routes, key=lambda r: r.uri)))


def compile_model(snapshot: Snapshot, state: tuple[bool, ...] | None = None) -> Model:
    state = snapshot.initial if state is None else state
    if len(state) != len(snapshot.routes) or any(type(x) is not bool for x in state):
        raise ValueError("State must contain one boolean per route")
    string = AttributeSpec(ValueKind.STRING, required=True, indexed=True)
    rate = AttributeSpec(ValueKind.FLOAT, required=True, minimum=0)
    schema = Schema([
        VertexType("Site", {"uri": string}),
        VertexType("Route", {"uri": string, "source": string, "target": string,
                             "up": AttributeSpec(ValueKind.BOOL, required=True),
                             "failure": rate, "repair": rate}),
    ], [HyperedgeType("Available", {"route": PortSpec("route", "Route"),
                                   "source": PortSpec("source", "Site")},
                                  {"target": PortSpec("target", "Site")})],
        schema_id="ontology-route-control-v1")
    graph = Hypergraph(schema)
    sites = {uri: graph.add_vertex("Site", {"uri": uri}).entity_id for uri in snapshot.sites}
    for route, up in zip(snapshot.routes, state):
        vertex = graph.add_vertex("Route", {
            "uri": route.uri, "source": route.source, "target": route.target,
            "up": up, "failure": route.failure, "repair": route.repair,
        })
        if up:
            graph.add_edge("Available", {"route": (vertex.entity_id,),
                                         "source": (sites[route.source],)},
                           {"target": (sites[route.target],)})
    tail, head = {"route": ("r",), "source": ("s",)}, {"target": ("t",)}
    rules = []
    for action, before, after, hazard in (("fail", True, False, "failure"),
                                          ("repair", False, True, "repair")):
        vertices = (
            PatternVertex("r", "Route", {"up": before, "source": Var("src"),
                                         "target": Var("dst"), hazard: Var("rate")}),
            PatternVertex("s", "Site", {"uri": Var("src")}),
            PatternVertex("t", "Site", {"uri": Var("dst")}),
        )
        left = PatternGraph(vertices, (PatternEdge("a", "Available", tail, head),) if before else ())
        right = TemplateGraph((TemplateVertex("r", "Route", {"up": after}),
                               TemplateVertex("s", "Site"), TemplateVertex("t", "Site")),
                              (TemplateEdge("a", "Available", tail, head),) if after else ())
        rules.append(Rule(action, left, right, Expr("rate")))
    return Model(graph, BoundaryState(), tuple(rules), model_id="ontology-route-control-v1")


def project_state(graph: Hypergraph, snapshot: Snapshot) -> tuple[bool, ...]:
    """Verify URI identity, endpoints and availability; do not just count edges."""
    sites = {v.attributes["uri"]: v.entity_id for v in graph.vertices.values() if v.type_id == "Site"}
    routes = {v.attributes["uri"]: v for v in graph.vertices.values() if v.type_id == "Route"}
    if (set(sites) != set(snapshot.sites) or set(routes) != {r.uri for r in snapshot.routes}
            or len(graph.vertices) != len(sites) + len(routes)):
        raise ValueError("Entity identities changed")
    actual = []
    for edge in graph.edges.values():
        if edge.type_id != "Available":
            raise ValueError("Unexpected relation")
        tail = {item.role: item.vertex_id for item in edge.tail}
        head = {item.role: item.vertex_id for item in edge.head}
        actual.append((tail["route"], tail["source"], head["target"]))
    expected = []
    for route in snapshot.routes:
        vertex = routes[route.uri]
        attrs = vertex.attributes
        if any(attrs[key] != getattr(route, key) for key in ("source", "target", "failure", "repair")):
            raise ValueError("Static properties changed")
        if attrs["up"]:
            expected.append((vertex.entity_id, sites[route.source], sites[route.target]))
    if sorted(actual) != sorted(expected):
        raise ValueError("Availability graph disagrees with route state or endpoints")
    return tuple(routes[r.uri].attributes["up"] for r in snapshot.routes)
