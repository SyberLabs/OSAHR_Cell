"""Pattern, template, condition, and rule declarations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .canonical import stable_hash
from .errors import PatternError
from .expr import Expr


@dataclass(frozen=True, slots=True)
class Var:
    name: str

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise PatternError(f"Invalid variable name {self.name!r}")


@dataclass(frozen=True, slots=True)
class AnyValue:
    pass


ANY = AnyValue()
PatternTerm = Var | AnyValue | Any
TemplateValue = Expr | Any


@dataclass(frozen=True, slots=True)
class PatternVertex:
    key: str
    type_id: str
    attributes: dict[str, PatternTerm] = field(default_factory=dict)
    allow_subtypes: bool = True


@dataclass(frozen=True, slots=True)
class PatternEdge:
    key: str
    type_id: str
    tail: dict[str, tuple[str, ...]]
    head: dict[str, tuple[str, ...]]
    attributes: dict[str, PatternTerm] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PatternGraph:
    vertices: tuple[PatternVertex, ...]
    edges: tuple[PatternEdge, ...] = ()

    def __post_init__(self) -> None:
        vertex_keys = [vertex.key for vertex in self.vertices]
        edge_keys = [edge.key for edge in self.edges]
        if len(vertex_keys) != len(set(vertex_keys)):
            raise PatternError("Duplicate pattern vertex key")
        if len(edge_keys) != len(set(edge_keys)):
            raise PatternError("Duplicate pattern edge key")
        if set(vertex_keys) & set(edge_keys):
            raise PatternError("Pattern keys must be unique across vertices and edges")
        known = set(vertex_keys)
        for edge in self.edges:
            referenced = {
                vertex_key
                for mapping in (edge.tail, edge.head)
                for values in mapping.values()
                for vertex_key in values
            }
            unknown = referenced - known
            if unknown:
                raise PatternError(f"Edge {edge.key!r} references unknown keys {sorted(unknown)!r}")

    @property
    def vertex_map(self) -> dict[str, PatternVertex]:
        return {item.key: item for item in self.vertices}

    @property
    def edge_map(self) -> dict[str, PatternEdge]:
        return {item.key: item for item in self.edges}


@dataclass(frozen=True, slots=True)
class TemplateVertex:
    key: str
    type_id: str
    attributes: dict[str, TemplateValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TemplateEdge:
    key: str
    type_id: str
    tail: dict[str, tuple[str, ...]]
    head: dict[str, tuple[str, ...]]
    attributes: dict[str, TemplateValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TemplateGraph:
    vertices: tuple[TemplateVertex, ...]
    edges: tuple[TemplateEdge, ...] = ()

    def __post_init__(self) -> None:
        vertex_keys = [vertex.key for vertex in self.vertices]
        edge_keys = [edge.key for edge in self.edges]
        if len(vertex_keys) != len(set(vertex_keys)):
            raise PatternError("Duplicate template vertex key")
        if len(edge_keys) != len(set(edge_keys)):
            raise PatternError("Duplicate template edge key")
        if set(vertex_keys) & set(edge_keys):
            raise PatternError("Template keys must be unique across vertices and edges")
        known = set(vertex_keys)
        for edge in self.edges:
            referenced = {
                vertex_key
                for mapping in (edge.tail, edge.head)
                for values in mapping.values()
                for vertex_key in values
            }
            unknown = referenced - known
            if unknown:
                raise PatternError(f"Template edge {edge.key!r} references unknown keys {sorted(unknown)!r}")

    @property
    def vertex_map(self) -> dict[str, TemplateVertex]:
        return {item.key: item for item in self.vertices}

    @property
    def edge_map(self) -> dict[str, TemplateEdge]:
        return {item.key: item for item in self.edges}


class ConditionPolarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


@dataclass(frozen=True, slots=True)
class GraphCondition:
    pattern: PatternGraph
    polarity: ConditionPolarity
    shared_vertices: dict[str, str] = field(default_factory=dict)
    shared_edges: dict[str, str] = field(default_factory=dict)
    guard: Expr | None = None


@dataclass(frozen=True, slots=True)
class StateAssignment:
    target: str  # "parameters.path" or "memory.path"
    value: Expr | Any

    def __post_init__(self) -> None:
        if not (self.target.startswith("parameters.") or self.target.startswith("memory.")):
            raise PatternError("State assignment target must begin with parameters. or memory.")


class BoundaryEffectKind(str, Enum):
    BIND = "bind"
    REBIND = "rebind"
    UNBIND = "unbind"
    DELETE_HANDLE = "delete_handle"


@dataclass(frozen=True, slots=True)
class BoundaryEffect:
    kind: BoundaryEffectKind
    handle_id: str
    vertex_key: str | None = None


@dataclass(frozen=True, slots=True)
class OutputSpec:
    handle_id: str
    event_type: str
    payload: dict[str, TemplateValue]


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    left: PatternGraph
    right: TemplateGraph
    hazard: Expr
    guard: Expr | None = None
    conditions: tuple[GraphCondition, ...] = ()
    adaptation: tuple[StateAssignment, ...] = ()
    boundary_effects: tuple[BoundaryEffect, ...] = ()
    outputs: tuple[OutputSpec, ...] = ()
    hazard_upper_bound: Expr | None = None
    hazard_integral: Expr | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"
    enabled: bool = True
    hash: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        time_names = {"time", "delta_time", "horizon"}
        illegal_hazard_names = {"delta_time", "horizon"} & self.hazard.names
        if illegal_hazard_names:
            raise PatternError(
                "Hazards may depend on absolute simulation time via `time`, but not "
                f"on scheduling-only names {sorted(illegal_hazard_names)!r}"
            )
        if "time" in self.hazard.names and self.hazard_upper_bound is None:
            raise PatternError(
                "Time-dependent hazards require hazard_upper_bound for exact thinning semantics"
            )
        if self.hazard_integral is not None:
            illegal_integral_names = {"delta_time"} & self.hazard_integral.names
            if illegal_integral_names:
                raise PatternError(
                    "hazard_integral uses `time` as interval start and `horizon` as interval end"
                )
        if self.guard is not None and time_names & self.guard.names:
            raise PatternError(
                "Time-dependent guards are not supported: encode enable/disable changes as scheduled state events"
            )
        for condition in self.conditions:
            if condition.guard is not None and time_names & condition.guard.names:
                raise PatternError(
                    "Time-dependent graph-condition guards are not supported"
                )
        left_vertices = self.left.vertex_map
        right_vertices = self.right.vertex_map
        left_edges = self.left.edge_map
        right_edges = self.right.edge_map

        for key in left_vertices.keys() & right_vertices.keys():
            if left_vertices[key].type_id != right_vertices[key].type_id:
                raise PatternError(f"Preserved vertex {key!r} changes type")
        for key in left_edges.keys() & right_edges.keys():
            left_edge = left_edges[key]
            right_edge = right_edges[key]
            if left_edge.type_id != right_edge.type_id:
                raise PatternError(f"Preserved edge {key!r} changes type")
            if left_edge.tail != right_edge.tail or left_edge.head != right_edge.head:
                raise PatternError(
                    f"Preserved edge {key!r} changes incidence; delete and recreate it instead"
                )
        all_right_keys = set(right_vertices) | set(right_edges)
        for effect in self.boundary_effects:
            if effect.kind in {BoundaryEffectKind.BIND, BoundaryEffectKind.REBIND}:
                if effect.vertex_key not in right_vertices:
                    raise PatternError(
                        f"Boundary effect references missing right-side vertex {effect.vertex_key!r}"
                    )
        object.__setattr__(self, "hash", stable_hash(self.to_canonical()))

    @property
    def preserved_vertex_keys(self) -> frozenset[str]:
        return frozenset(self.left.vertex_map.keys() & self.right.vertex_map.keys())

    @property
    def deleted_vertex_keys(self) -> frozenset[str]:
        return frozenset(self.left.vertex_map.keys() - self.right.vertex_map.keys())

    @property
    def created_vertex_keys(self) -> frozenset[str]:
        return frozenset(self.right.vertex_map.keys() - self.left.vertex_map.keys())

    @property
    def preserved_edge_keys(self) -> frozenset[str]:
        return frozenset(self.left.edge_map.keys() & self.right.edge_map.keys())

    @property
    def deleted_edge_keys(self) -> frozenset[str]:
        return frozenset(self.left.edge_map.keys() - self.right.edge_map.keys())

    @property
    def created_edge_keys(self) -> frozenset[str]:
        return frozenset(self.right.edge_map.keys() - self.left.edge_map.keys())

    def to_canonical(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "version": self.version,
            "left": self.left,
            "right": self.right,
            "hazard": self.hazard.source,
            "guard": None if self.guard is None else self.guard.source,
            "conditions": self.conditions,
            "adaptation": self.adaptation,
            "boundary_effects": self.boundary_effects,
            "outputs": self.outputs,
            "hazard_upper_bound": None if self.hazard_upper_bound is None else self.hazard_upper_bound.source,
            "hazard_integral": None if self.hazard_integral is None else self.hazard_integral.source,
            "meta": self.meta,
            "enabled": self.enabled,
        }
