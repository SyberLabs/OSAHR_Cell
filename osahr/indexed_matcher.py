"""Incidence-constrained search for the same embeddings as the reference matcher.

Candidate projections are necessary conditions only. Complete assignments still
pass the reference incidence and attribute predicates; no symmetry is quotiented.
"""

from __future__ import annotations

from typing import Any

from .graph import Hypergraph, Side
from .ids import EntityId
from .matcher import Match, Matcher, _canonical_matches, _edge_matches, _match_attributes, _resolve_prebindings
from .pattern import PatternGraph


class IndexedMatcher(Matcher):
    """Use existing type/incidence indices without maintaining another cache."""

    def find_pattern_matches(
        self,
        graph: Hypergraph,
        pattern: PatternGraph,
        *,
        rule_id: str = "<pattern>",
        prebound_vertices: dict[str, EntityId] | None = None,
        prebound_edges: dict[str, EntityId] | None = None,
        initial_bindings: dict[str, Any] | None = None,
    ) -> list[Match]:
        resolved = _resolve_prebindings(graph, pattern, prebound_vertices, prebound_edges)
        if resolved is None:
            return []
        prebound_vertices, prebound_edges = resolved
        vertex_specs, edge_specs = pattern.vertex_map, pattern.edge_map

        # Each occurrence of a symbolic vertex records its exact incidence role.
        positions = {
            key: tuple(
                (side, role, ordinal, vertex_key)
                for side, mapping in ((Side.TAIL, spec.tail), (Side.HEAD, spec.head))
                for role, keys in mapping.items()
                for ordinal, vertex_key in enumerate(keys)
            )
            for key, spec in edge_specs.items()
        }
        adjacent = {
            key: tuple(edge_key for edge_key, items in positions.items()
                       if any(item[3] == key for item in items))
            for key in vertex_specs
        }
        vertex_map: dict[str, EntityId] = {}
        edge_map: dict[str, EntityId] = {}
        used_vertices: set[EntityId] = set()
        used_edges: set[EntityId] = set()
        matches: list[Match] = []

        def ordered(edge_key: str, side: Side, role: str) -> bool:
            definition = graph.schema.edge_types[edge_specs[edge_key].type_id]
            ports = definition.tail_ports if side is Side.TAIL else definition.head_ports
            return ports[role].ordered

        def edge_candidates(key: str) -> set[EntityId]:
            if key in prebound_edges:
                return {prebound_edges[key]}
            # Every valid image edge is incident to every already bound endpoint.
            # Start at the smallest existing bucket, avoiding a global edge scan.
            buckets = [
                graph.incidences_by_vertex.get(vertex_map[vertex_key], set())
                for _, _, _, vertex_key in positions[key] if vertex_key in vertex_map
            ]
            if not buckets:
                return graph.edges_by_type.get(edge_specs[key].type_id, set())
            return {
                item.edge_id for item in min(buckets, key=len)
                if graph.edges[item.edge_id].type_id == edge_specs[key].type_id
            }

        def vertex_candidates(key: str) -> list[EntityId]:
            if key in prebound_vertices:
                return [prebound_vertices[key]]
            domain: set[EntityId] | None = None
            for edge_key in adjacent[key]:
                if edge_key not in prebound_edges and not any(
                    vertex_key in vertex_map for _, _, _, vertex_key in positions[edge_key]
                ):
                    continue
                # Projection can overestimate the relation (e.g. multiplicities),
                # but must never exclude an endpoint of a valid complete match.
                for side, role, ordinal, vertex_key in positions[edge_key]:
                    if vertex_key != key:
                        continue
                    projected = {
                        item.vertex_id
                        for entity_id in edge_candidates(edge_key)
                        for item in graph.edges[entity_id].incidences
                        if item.side is side and item.role == role
                        and (not ordered(edge_key, side, role) or item.ordinal == ordinal)
                    }
                    domain = projected if domain is None else domain & projected
                    if not domain:
                        return []
            spec = vertex_specs[key]
            if domain is None:
                domain = {
                    entity_id
                    for type_id, entities in graph.vertices_by_type.items()
                    if graph.schema.is_vertex_compatible(
                        type_id, spec.type_id, allow_subtypes=spec.allow_subtypes
                    )
                    for entity_id in entities
                }
            return sorted(domain - used_vertices)

        def assign_edges(bindings: dict[str, Any]) -> None:
            if len(edge_map) == len(edge_specs):
                matches.append(Match.create(
                    rule_id=rule_id, vertex_map=vertex_map, edge_map=edge_map,
                    bindings=bindings, graph_epoch=graph.epoch,
                ))
                return
            key = min(
                (key for key in edge_specs if key not in edge_map),
                key=lambda key: (key not in prebound_edges,
                                 len(graph.edges_by_type.get(edge_specs[key].type_id, ())), key),
            )
            spec = edge_specs[key]
            for entity_id in sorted(edge_candidates(key) - used_edges):
                edge = graph.edges[entity_id]
                if not _edge_matches(graph, spec, edge, vertex_map):
                    continue
                next_bindings = _match_attributes(spec.attributes, edge.attributes, bindings)
                if next_bindings is None:
                    continue
                edge_map[key] = entity_id
                used_edges.add(entity_id)
                assign_edges(next_bindings)
                used_edges.remove(entity_id)
                del edge_map[key]

        def assign_vertices(bindings: dict[str, Any]) -> None:
            if len(vertex_map) == len(vertex_specs):
                assign_edges(bindings)
                return
            # Expand from existing anchors before starting a disconnected part.
            key = min(
                (key for key in vertex_specs if key not in vertex_map),
                key=lambda key: (
                    key not in prebound_vertices,
                    -sum(edge_key in prebound_edges or any(
                        item[3] in vertex_map for item in positions[edge_key]
                    ) for edge_key in adjacent[key]),
                    key,
                ),
            )
            spec = vertex_specs[key]
            for entity_id in vertex_candidates(key):
                if entity_id in used_vertices:
                    continue
                vertex = graph.vertices[entity_id]
                if not graph.schema.is_vertex_compatible(
                    vertex.type_id, spec.type_id, allow_subtypes=spec.allow_subtypes
                ):
                    continue
                next_bindings = _match_attributes(spec.attributes, vertex.attributes, bindings)
                if next_bindings is None:
                    continue
                vertex_map[key] = entity_id
                used_vertices.add(entity_id)
                # Reject a closed incidence constraint before adding more vertices.
                if all(
                    any(_edge_matches(graph, edge_specs[edge_key], graph.edges[edge_id], vertex_map)
                        for edge_id in edge_candidates(edge_key))
                    for edge_key in adjacent[key]
                    if all(item[3] in vertex_map for item in positions[edge_key])
                ):
                    assign_vertices(next_bindings)
                used_vertices.remove(entity_id)
                del vertex_map[key]

        assign_vertices(dict(initial_bindings or {}))
        return _canonical_matches(matches)
