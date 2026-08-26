"""Structural composition of compatible open hypergraph models."""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable

from .boundary import BoundaryDirection, BoundaryHandle, BoundaryState
from .errors import ValidationError
from .graph import Hypergraph
from .ids import EntityId
from .pattern import BoundaryEffect, OutputSpec
from .model import Model


@dataclass(frozen=True, slots=True)
class Wire:
    left_component: str
    left_handle: str
    right_component: str
    right_handle: str


@dataclass(slots=True)
class CompositionResult:
    model: Model
    vertex_maps: dict[str, dict[EntityId, EntityId]]
    edge_maps: dict[str, dict[EntityId, EntityId]]
    handle_maps: dict[str, dict[str, str]]
    rule_maps: dict[str, dict[str, str]]


class _UnionFind:
    def __init__(self, items: Iterable[tuple[str, EntityId]]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: tuple[str, EntityId]) -> tuple[str, EntityId]:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: tuple[str, EntityId], right: tuple[str, EntityId]) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[max(root_left, root_right)] = min(root_left, root_right)


def _merge_flat_state(
    destination: dict[str, Any],
    source: dict[str, Any],
    *,
    label: str,
) -> None:
    for key, value in source.items():
        if key in destination and destination[key] != value:
            raise ValidationError(
                f"Conflicting {label} key {key!r}; use disjoint names or equal initial values"
            )
        destination[key] = copy.deepcopy(value)


def compose_structural(
    components: dict[str, Model],
    wires: Iterable[Wire],
    *,
    composite_model_id: str = "composite",
    namespace: int = 0xC05A,
    merge_vertex_attributes: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
    retain_wired_handles: bool = False,
) -> CompositionResult:
    if not components:
        raise ValidationError("At least one component is required")
    if len(components) != len(set(components)):
        raise ValidationError("Duplicate component name")
    schema_hashes = {model.graph.schema.hash for model in components.values()}
    if len(schema_hashes) != 1:
        raise ValidationError("Structural composition currently requires identical schemas")
    schema = next(iter(components.values())).graph.schema

    all_vertices = [
        (component_name, vertex_id)
        for component_name, model in components.items()
        for vertex_id in model.graph.vertices
    ]
    union_find = _UnionFind(all_vertices)
    consumed_handles: set[tuple[str, str]] = set()

    wire_list = list(wires)
    for wire in wire_list:
        try:
            left = components[wire.left_component].boundary.handles[wire.left_handle]
            right = components[wire.right_component].boundary.handles[wire.right_handle]
        except KeyError as exc:
            raise ValidationError(f"Unknown component or boundary in wire {wire}") from exc
        if left.binding is None or right.binding is None:
            raise ValidationError("Cannot structurally wire an unbound boundary")
        directions = {left.direction, right.direction}
        if directions == {BoundaryDirection.INPUT} or directions == {BoundaryDirection.OUTPUT}:
            raise ValidationError("A wire must connect compatible input/output directions")
        left_vertex = components[wire.left_component].graph.vertices[left.binding]
        right_vertex = components[wire.right_component].graph.vertices[right.binding]
        if not (
            schema.is_vertex_compatible(left_vertex.type_id, right_vertex.type_id)
            or schema.is_vertex_compatible(right_vertex.type_id, left_vertex.type_id)
        ):
            raise ValidationError(
                f"Cannot identify incompatible interface types {left_vertex.type_id!r} and "
                f"{right_vertex.type_id!r}"
            )
        union_find.union(
            (wire.left_component, left.binding),
            (wire.right_component, right.binding),
        )
        consumed_handles.add((wire.left_component, wire.left_handle))
        consumed_handles.add((wire.right_component, wire.right_handle))

    groups: dict[tuple[str, EntityId], list[tuple[str, EntityId]]] = {}
    for item in all_vertices:
        groups.setdefault(union_find.find(item), []).append(item)

    graph = Hypergraph(schema, namespace=namespace)
    vertex_maps: dict[str, dict[EntityId, EntityId]] = {
        name: {} for name in components
    }

    for root in sorted(groups):
        members = sorted(groups[root])
        source_vertices = [components[name].graph.vertices[vertex_id] for name, vertex_id in members]
        chosen_type = source_vertices[0].type_id
        for vertex in source_vertices[1:]:
            if schema.is_vertex_compatible(vertex.type_id, chosen_type):
                chosen_type = vertex.type_id
            elif not schema.is_vertex_compatible(chosen_type, vertex.type_id):
                raise ValidationError("Wired vertex group has incompatible types")
        attrs_list = [vertex.attributes for vertex in source_vertices]
        if merge_vertex_attributes is not None:
            attrs = merge_vertex_attributes([copy.deepcopy(item) for item in attrs_list])
        else:
            attrs: dict[str, Any] = {}
            for source in attrs_list:
                for key, value in source.items():
                    if key in attrs and attrs[key] != value:
                        raise ValidationError(
                            f"Conflicting attributes while identifying wired vertices: {key!r}"
                        )
                    attrs[key] = copy.deepcopy(value)
        created = graph.add_vertex(chosen_type, attrs, increment_epoch=False)
        for component_name, old_id in members:
            vertex_maps[component_name][old_id] = created.entity_id

    edge_maps: dict[str, dict[EntityId, EntityId]] = {
        name: {} for name in components
    }
    for component_name in sorted(components):
        source_graph = components[component_name].graph
        for edge in sorted(source_graph.edges.values(), key=lambda item: item.entity_id):
            tail_old = source_graph._role_mapping(edge.tail)
            head_old = source_graph._role_mapping(edge.head)
            tail = {
                role: tuple(vertex_maps[component_name][vertex_id] for vertex_id in ids)
                for role, ids in tail_old.items()
            }
            head = {
                role: tuple(vertex_maps[component_name][vertex_id] for vertex_id in ids)
                for role, ids in head_old.items()
            }
            created = graph.add_edge(
                edge.type_id,
                tail,
                head,
                copy.deepcopy(edge.attributes),
                increment_epoch=False,
            )
            edge_maps[component_name][edge.entity_id] = created.entity_id
    graph.validate()
    graph.epoch = 0

    boundary = BoundaryState()
    handle_maps: dict[str, dict[str, str]] = {name: {} for name in components}
    for component_name in sorted(components):
        for handle_id, handle in sorted(components[component_name].boundary.handles.items()):
            if (component_name, handle_id) in consumed_handles and not retain_wired_handles:
                continue
            new_handle_id = f"{component_name}::{handle_id}"
            handle_maps[component_name][handle_id] = new_handle_id
            boundary.add(
                BoundaryHandle(
                    handle_id=new_handle_id,
                    direction=handle.direction,
                    interface_type=handle.interface_type,
                    binding=None
                    if handle.binding is None
                    else vertex_maps[component_name][handle.binding],
                    nullable=handle.nullable,
                    payload_schema=copy.deepcopy(handle.payload_schema),
                    allow_payload_extensions=handle.allow_payload_extensions,
                    input_mode=handle.input_mode,
                    metadata={"component": component_name, **copy.deepcopy(handle.metadata)},
                )
            )

    rules = []
    rule_maps: dict[str, dict[str, str]] = {name: {} for name in components}
    for component_name in sorted(components):
        for rule in components[component_name].rules:
            referenced_handles = {
                effect.handle_id for effect in rule.boundary_effects
            } | {output.handle_id for output in rule.outputs}
            unavailable = {
                handle_id
                for handle_id in referenced_handles
                if (component_name, handle_id) in consumed_handles and not retain_wired_handles
            }
            if unavailable:
                raise ValidationError(
                    f"Rules in component {component_name!r} reference consumed wired handles "
                    f"{sorted(unavailable)!r}; retain the handles or remove those effects"
                )
            new_rule_id = f"{component_name}::{rule.rule_id}"
            rule_maps[component_name][rule.rule_id] = new_rule_id
            remapped_effects = tuple(
                replace(
                    effect,
                    handle_id=handle_maps[component_name].get(
                        effect.handle_id, f"{component_name}::{effect.handle_id}"
                    ),
                )
                for effect in rule.boundary_effects
            )
            remapped_outputs = tuple(
                replace(
                    output,
                    handle_id=handle_maps[component_name].get(
                        output.handle_id, f"{component_name}::{output.handle_id}"
                    ),
                )
                for output in rule.outputs
            )
            rules.append(
                replace(
                    rule,
                    rule_id=new_rule_id,
                    boundary_effects=remapped_effects,
                    outputs=remapped_outputs,
                )
            )

    parameters: dict[str, Any] = {}
    memory: dict[str, Any] = {}
    for component_name in sorted(components):
        _merge_flat_state(parameters, components[component_name].parameters, label="parameter")
        _merge_flat_state(memory, components[component_name].memory, label="memory")

    model = Model(
        graph=graph,
        boundary=boundary,
        rules=tuple(rules),
        parameters=parameters,
        memory=memory,
        model_id=composite_model_id,
    )
    return CompositionResult(model, vertex_maps, edge_maps, handle_maps, rule_maps)
