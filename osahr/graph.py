"""Mutable, validated directed hypergraph store with explicit incidences."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from .canonical import stable_hash
from .errors import ValidationError
from .ids import EntityId, IdAllocator
from .schema import HyperedgeType, PortSpec, Schema


class Side(str, Enum):
    TAIL = "tail"
    HEAD = "head"


@dataclass(frozen=True, slots=True, order=True)
class Incidence:
    edge_id: EntityId
    side: Side
    role: str
    ordinal: int
    vertex_id: EntityId


@dataclass(slots=True)
class Vertex:
    entity_id: EntityId
    type_id: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Hyperedge:
    entity_id: EntityId
    type_id: str
    tail: tuple[Incidence, ...]
    head: tuple[Incidence, ...]
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def incidences(self) -> tuple[Incidence, ...]:
        return self.tail + self.head


@dataclass(slots=True)
class GraphDelta:
    created_vertices: dict[EntityId, Vertex] = field(default_factory=dict)
    deleted_vertices: dict[EntityId, Vertex] = field(default_factory=dict)
    updated_vertices_before: dict[EntityId, dict[str, Any]] = field(default_factory=dict)
    updated_vertices_after: dict[EntityId, dict[str, Any]] = field(default_factory=dict)

    created_edges: dict[EntityId, Hyperedge] = field(default_factory=dict)
    deleted_edges: dict[EntityId, Hyperedge] = field(default_factory=dict)
    updated_edges_before: dict[EntityId, dict[str, Any]] = field(default_factory=dict)
    updated_edges_after: dict[EntityId, dict[str, Any]] = field(default_factory=dict)

    def touched_entities(self) -> set[EntityId]:
        return (
            set(self.created_vertices)
            | set(self.deleted_vertices)
            | set(self.updated_vertices_before)
            | set(self.created_edges)
            | set(self.deleted_edges)
            | set(self.updated_edges_before)
        )

    def is_empty(self) -> bool:
        return not self.touched_entities()


class Hypergraph:
    def __init__(
        self,
        schema: Schema,
        *,
        namespace: int = 1,
        vertices: Iterable[Vertex] = (),
        edges: Iterable[Hyperedge] = (),
    ) -> None:
        self.schema = schema
        self.vertices: dict[EntityId, Vertex] = {}
        self.edges: dict[EntityId, Hyperedge] = {}
        self.vertices_by_type: dict[str, set[EntityId]] = {
            type_id: set() for type_id in schema.vertex_types
        }
        self.edges_by_type: dict[str, set[EntityId]] = {
            type_id: set() for type_id in schema.edge_types
        }
        self.incidences_by_vertex: dict[EntityId, set[Incidence]] = {}
        self.epoch = 0
        self.id_allocator = IdAllocator(namespace)

        for vertex in vertices:
            self.add_vertex(
                vertex.type_id,
                vertex.attributes,
                entity_id=vertex.entity_id,
                increment_epoch=False,
            )
        for edge in edges:
            tail = self._role_mapping(edge.tail)
            head = self._role_mapping(edge.head)
            self.add_edge(
                edge.type_id,
                tail,
                head,
                edge.attributes,
                entity_id=edge.entity_id,
                increment_epoch=False,
            )
        self.validate()
        self.epoch = 0

    @staticmethod
    def _role_mapping(incidences: tuple[Incidence, ...]) -> dict[str, tuple[EntityId, ...]]:
        result: dict[str, list[tuple[int, EntityId]]] = {}
        for incidence in incidences:
            result.setdefault(incidence.role, []).append((incidence.ordinal, incidence.vertex_id))
        return {
            role: tuple(vertex_id for _, vertex_id in sorted(items))
            for role, items in result.items()
        }

    def clone(self) -> "Hypergraph":
        return Hypergraph(
            self.schema,
            namespace=self.id_allocator.namespace,
            vertices=(
                Vertex(v.entity_id, v.type_id, dict(v.attributes)) for v in self.vertices.values()
            ),
            edges=(
                Hyperedge(
                    e.entity_id,
                    e.type_id,
                    tuple(e.tail),
                    tuple(e.head),
                    dict(e.attributes),
                )
                for e in self.edges.values()
            ),
        )._with_runtime_state(self.epoch, self.id_allocator.next_counter)

    def _with_runtime_state(self, epoch: int, next_counter: int) -> "Hypergraph":
        self.epoch = epoch
        self.id_allocator.next_counter = next_counter
        return self

    def add_vertex(
        self,
        type_id: str,
        attributes: dict[str, Any] | None = None,
        *,
        entity_id: EntityId | None = None,
        increment_epoch: bool = True,
    ) -> Vertex:
        entity_id = entity_id or self.id_allocator.allocate()
        if entity_id in self.vertices or entity_id in self.edges:
            raise ValidationError(f"Duplicate entity ID {entity_id}")
        attrs = self.schema.materialize_vertex_attributes(type_id, attributes or {})
        vertex = Vertex(entity_id, type_id, attrs)
        self.vertices[entity_id] = vertex
        self.vertices_by_type[type_id].add(entity_id)
        self.incidences_by_vertex.setdefault(entity_id, set())
        self.id_allocator.reserve_after(entity_id)
        if increment_epoch:
            self.epoch += 1
        return vertex

    def _validate_role_mapping(
        self,
        edge_type: HyperedgeType,
        mapping: dict[str, tuple[EntityId, ...] | list[EntityId]],
        *,
        side: Side,
    ) -> None:
        specs = edge_type.tail_ports if side is Side.TAIL else edge_type.head_ports
        unknown = set(mapping) - specs.keys()
        if unknown:
            raise ValidationError(
                f"Unknown {side.value} roles for edge type {edge_type.type_id}: {sorted(unknown)}"
            )
        for role, spec in specs.items():
            vertices = tuple(mapping.get(role, ()))
            if len(vertices) < spec.minimum:
                raise ValidationError(
                    f"Role {role!r} requires at least {spec.minimum} vertices"
                )
            if spec.maximum is not None and len(vertices) > spec.maximum:
                raise ValidationError(
                    f"Role {role!r} permits at most {spec.maximum} vertices"
                )
            if not spec.repeated_vertices and len(vertices) != len(set(vertices)):
                raise ValidationError(f"Role {role!r} forbids repeated vertices")
            for vertex_id in vertices:
                if vertex_id not in self.vertices:
                    raise ValidationError(f"Unknown incident vertex {vertex_id}")
                actual_type = self.vertices[vertex_id].type_id
                if not self.schema.is_vertex_compatible(
                    actual_type,
                    spec.accepted_vertex_type,
                    allow_subtypes=spec.allow_subtypes,
                ):
                    raise ValidationError(
                        f"Vertex {vertex_id} of type {actual_type!r} is incompatible with "
                        f"{edge_type.type_id}.{role}:{spec.accepted_vertex_type}"
                    )

    def add_edge(
        self,
        type_id: str,
        tail: dict[str, tuple[EntityId, ...] | list[EntityId]],
        head: dict[str, tuple[EntityId, ...] | list[EntityId]],
        attributes: dict[str, Any] | None = None,
        *,
        entity_id: EntityId | None = None,
        increment_epoch: bool = True,
    ) -> Hyperedge:
        entity_id = entity_id or self.id_allocator.allocate()
        if entity_id in self.vertices or entity_id in self.edges:
            raise ValidationError(f"Duplicate entity ID {entity_id}")
        try:
            definition = self.schema.edge_types[type_id]
        except KeyError as exc:
            raise ValidationError(f"Unknown edge type {type_id!r}") from exc
        normalized_tail = {role: tuple(items) for role, items in tail.items()}
        normalized_head = {role: tuple(items) for role, items in head.items()}
        self._validate_role_mapping(definition, normalized_tail, side=Side.TAIL)
        self._validate_role_mapping(definition, normalized_head, side=Side.HEAD)
        attrs = self.schema.materialize_edge_attributes(type_id, attributes or {})

        tail_incidences = tuple(
            Incidence(entity_id, Side.TAIL, role, ordinal, vertex_id)
            for role in sorted(normalized_tail)
            for ordinal, vertex_id in enumerate(normalized_tail[role])
        )
        head_incidences = tuple(
            Incidence(entity_id, Side.HEAD, role, ordinal, vertex_id)
            for role in sorted(normalized_head)
            for ordinal, vertex_id in enumerate(normalized_head[role])
        )
        edge = Hyperedge(entity_id, type_id, tail_incidences, head_incidences, attrs)
        self.edges[entity_id] = edge
        self.edges_by_type[type_id].add(entity_id)
        for incidence in edge.incidences:
            self.incidences_by_vertex[incidence.vertex_id].add(incidence)
        self.id_allocator.reserve_after(entity_id)
        if increment_epoch:
            self.epoch += 1
        return edge

    def remove_edge(self, edge_id: EntityId, *, increment_epoch: bool = True) -> Hyperedge:
        try:
            edge = self.edges.pop(edge_id)
        except KeyError as exc:
            raise ValidationError(f"Unknown edge {edge_id}") from exc
        self.edges_by_type[edge.type_id].remove(edge_id)
        for incidence in edge.incidences:
            self.incidences_by_vertex[incidence.vertex_id].remove(incidence)
        if increment_epoch:
            self.epoch += 1
        return edge

    def remove_vertex(
        self,
        vertex_id: EntityId,
        *,
        require_isolated: bool = True,
        increment_epoch: bool = True,
    ) -> Vertex:
        try:
            vertex = self.vertices[vertex_id]
        except KeyError as exc:
            raise ValidationError(f"Unknown vertex {vertex_id}") from exc
        incident = self.incidences_by_vertex.get(vertex_id, set())
        if incident and require_isolated:
            raise ValidationError(f"Cannot delete incident vertex {vertex_id}")
        if incident:
            for edge_id in sorted({item.edge_id for item in incident}):
                self.remove_edge(edge_id, increment_epoch=False)
        del self.vertices[vertex_id]
        self.vertices_by_type[vertex.type_id].remove(vertex_id)
        del self.incidences_by_vertex[vertex_id]
        if increment_epoch:
            self.epoch += 1
        return vertex

    def set_vertex_attributes(
        self,
        vertex_id: EntityId,
        updates: dict[str, Any],
        *,
        replace: bool = False,
        increment_epoch: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        vertex = self.vertices[vertex_id]
        definition = self.schema.vertex_types[vertex.type_id]
        for name in updates:
            if name in definition.attributes and not definition.attributes[name].mutable:
                if name in vertex.attributes and vertex.attributes[name] != updates[name]:
                    raise ValidationError(f"Attribute {name!r} is immutable")
        before = dict(vertex.attributes)
        candidate = dict(updates) if replace else {**vertex.attributes, **updates}
        vertex.attributes = self.schema.materialize_vertex_attributes(vertex.type_id, candidate)
        if increment_epoch:
            self.epoch += 1
        return before, dict(vertex.attributes)

    def set_edge_attributes(
        self,
        edge_id: EntityId,
        updates: dict[str, Any],
        *,
        replace: bool = False,
        increment_epoch: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        edge = self.edges[edge_id]
        definition = self.schema.edge_types[edge.type_id]
        for name in updates:
            if name in definition.attributes and not definition.attributes[name].mutable:
                if name in edge.attributes and edge.attributes[name] != updates[name]:
                    raise ValidationError(f"Attribute {name!r} is immutable")
        before = dict(edge.attributes)
        candidate = dict(updates) if replace else {**edge.attributes, **updates}
        edge.attributes = self.schema.materialize_edge_attributes(edge.type_id, candidate)
        if increment_epoch:
            self.epoch += 1
        return before, dict(edge.attributes)

    def incident_edges(self, vertex_id: EntityId) -> set[EntityId]:
        return {incidence.edge_id for incidence in self.incidences_by_vertex[vertex_id]}

    def validate(self) -> None:
        seen = set(self.vertices) & set(self.edges)
        if seen:
            raise ValidationError(f"IDs used by both vertices and edges: {seen}")
        for vertex_id, vertex in self.vertices.items():
            if vertex_id != vertex.entity_id:
                raise ValidationError("Vertex map key does not match entity ID")
            self.schema.materialize_vertex_attributes(vertex.type_id, vertex.attributes)
        rebuilt: dict[EntityId, set[Incidence]] = {vertex_id: set() for vertex_id in self.vertices}
        for edge_id, edge in self.edges.items():
            if edge_id != edge.entity_id:
                raise ValidationError("Edge map key does not match entity ID")
            definition = self.schema.edge_types.get(edge.type_id)
            if definition is None:
                raise ValidationError(f"Unknown edge type {edge.type_id}")
            self.schema.materialize_edge_attributes(edge.type_id, edge.attributes)
            self._validate_role_mapping(
                definition, self._role_mapping(edge.tail), side=Side.TAIL
            )
            self._validate_role_mapping(
                definition, self._role_mapping(edge.head), side=Side.HEAD
            )
            for incidence in edge.incidences:
                if incidence.edge_id != edge_id:
                    raise ValidationError("Incidence edge ID mismatch")
                rebuilt[incidence.vertex_id].add(incidence)
        if rebuilt != self.incidences_by_vertex:
            raise ValidationError("Incidence index is inconsistent")

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema_hash": self.schema.hash,
            "vertices": [
                {
                    "id": str(vertex.entity_id),
                    "type": vertex.type_id,
                    "attributes": vertex.attributes,
                }
                for vertex in sorted(self.vertices.values(), key=lambda item: item.entity_id)
            ],
            "edges": [
                {
                    "id": str(edge.entity_id),
                    "type": edge.type_id,
                    "tail": [
                        {
                            "role": incidence.role,
                            "ordinal": incidence.ordinal,
                            "vertex": str(incidence.vertex_id),
                        }
                        for incidence in sorted(edge.tail)
                    ],
                    "head": [
                        {
                            "role": incidence.role,
                            "ordinal": incidence.ordinal,
                            "vertex": str(incidence.vertex_id),
                        }
                        for incidence in sorted(edge.head)
                    ],
                    "attributes": edge.attributes,
                }
                for edge in sorted(self.edges.values(), key=lambda item: item.entity_id)
            ],
        }

    @property
    def state_hash(self) -> str:
        return stable_hash(self.to_canonical())

    def apply_delta(self, delta: GraphDelta) -> None:
        """Apply a previously committed delta, used by deterministic replay."""
        for edge_id in sorted(delta.deleted_edges):
            self.remove_edge(edge_id, increment_epoch=False)
        for vertex_id in sorted(delta.deleted_vertices):
            self.remove_vertex(vertex_id, increment_epoch=False)
        for vertex_id, vertex in sorted(delta.created_vertices.items()):
            self.add_vertex(
                vertex.type_id,
                dict(vertex.attributes),
                entity_id=vertex_id,
                increment_epoch=False,
            )
        for edge_id, edge in sorted(delta.created_edges.items()):
            self.add_edge(
                edge.type_id,
                self._role_mapping(edge.tail),
                self._role_mapping(edge.head),
                dict(edge.attributes),
                entity_id=edge_id,
                increment_epoch=False,
            )
        for vertex_id, attrs in sorted(delta.updated_vertices_after.items()):
            self.set_vertex_attributes(
                vertex_id, dict(attrs), replace=True, increment_epoch=False
            )
        for edge_id, attrs in sorted(delta.updated_edges_after.items()):
            self.set_edge_attributes(edge_id, dict(attrs), replace=True, increment_epoch=False)
        self.validate()
        self.epoch += 1
