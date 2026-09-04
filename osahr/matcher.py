"""Correctness-first injective matcher for typed directed hypergraph patterns."""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Iterable

from .canonical import canonical_equal, stable_hash
from .errors import MatchError
from .expr import Expr
from .graph import Hyperedge, Hypergraph, Incidence, Side
from .ids import EntityId
from .pattern import (
    ANY,
    AnyValue,
    ConditionPolarity,
    GraphCondition,
    PatternEdge,
    PatternGraph,
    PatternTerm,
    Rule,
    Var,
)


@dataclass(frozen=True, slots=True)
class Match:
    rule_id: str
    vertex_map: dict[str, EntityId]
    edge_map: dict[str, EntityId]
    bindings: dict[str, Any]
    graph_epoch: int
    match_id: str

    @classmethod
    def create(
        cls,
        *,
        rule_id: str,
        vertex_map: dict[str, EntityId],
        edge_map: dict[str, EntityId],
        bindings: dict[str, Any],
        graph_epoch: int,
    ) -> "Match":
        identity = {
            "rule_id": rule_id,
            "vertices": {key: str(value) for key, value in sorted(vertex_map.items())},
            "edges": {key: str(value) for key, value in sorted(edge_map.items())},
        }
        return cls(
            rule_id=rule_id,
            vertex_map=dict(vertex_map),
            edge_map=dict(edge_map),
            bindings=copy.deepcopy(bindings),
            graph_epoch=graph_epoch,
            match_id=stable_hash(identity),
        )


def _match_attributes(
    expected: dict[str, PatternTerm],
    actual: dict[str, Any],
    bindings: dict[str, Any],
) -> dict[str, Any] | None:
    result = dict(bindings)
    for name, term in expected.items():
        if name not in actual:
            return None
        value = actual[name]
        if isinstance(term, AnyValue):
            continue
        if isinstance(term, Var):
            if term.name in result:
                try:
                    if not canonical_equal(result[term.name], value):
                        return None
                except (TypeError, ValueError):
                    return None
            result[term.name] = value
        elif not canonical_equal(term, value):
            return None
    return result


def _role_map(incidences: Iterable[Incidence]) -> dict[str, tuple[EntityId, ...]]:
    grouped: dict[str, list[tuple[int, EntityId]]] = {}
    for item in incidences:
        grouped.setdefault(item.role, []).append((item.ordinal, item.vertex_id))
    return {
        role: tuple(vertex_id for _, vertex_id in sorted(values))
        for role, values in grouped.items()
    }


def _side_matches(
    graph: Hypergraph,
    edge: Hyperedge,
    pattern_mapping: dict[str, tuple[str, ...]],
    vertex_map: dict[str, EntityId],
    *,
    side: Side,
) -> bool:
    actual = _role_map(edge.tail if side is Side.TAIL else edge.head)
    if set(actual) != set(pattern_mapping):
        return False
    definition = graph.schema.edge_types[edge.type_id]
    port_specs = definition.tail_ports if side is Side.TAIL else definition.head_ports
    for role, pattern_keys in pattern_mapping.items():
        expected = tuple(vertex_map[key] for key in pattern_keys)
        actual_vertices = actual[role]
        if port_specs[role].ordered:
            if actual_vertices != expected:
                return False
        elif Counter(actual_vertices) != Counter(expected):
            return False
    return True


def _edge_matches(
    graph: Hypergraph,
    pattern: PatternEdge,
    edge: Hyperedge,
    vertex_map: dict[str, EntityId],
) -> bool:
    return (
        edge.type_id == pattern.type_id
        and _side_matches(graph, edge, pattern.tail, vertex_map, side=Side.TAIL)
        and _side_matches(graph, edge, pattern.head, vertex_map, side=Side.HEAD)
    )


def build_expression_context(
    graph: Hypergraph,
    match: Match,
    *,
    parameters: dict[str, Any],
    memory: dict[str, Any],
    time: float,
    delta_time: float = 0.0,
    payload: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = dict(match.bindings)
    context.update(
        {
            "p": parameters,
            "parameters": parameters,
            "z": memory,
            "memory": memory,
            "time": time,
            "delta_time": delta_time,
            "payload": payload or {},
            "v": {
                key: graph.vertices[entity_id].attributes
                for key, entity_id in match.vertex_map.items()
                if entity_id in graph.vertices
            },
            "e": {
                key: graph.edges[entity_id].attributes
                for key, entity_id in match.edge_map.items()
                if entity_id in graph.edges
            },
            "ids": {
                **{key: entity_id for key, entity_id in match.vertex_map.items()},
                **{key: entity_id for key, entity_id in match.edge_map.items()},
            },
        }
    )
    if extra:
        context.update(extra)
    return context


class Matcher:
    """Reference matcher.

    The matcher is deliberately simple and exhaustive. Its output is canonicalized
    by match ID, making it suitable as the oracle for future incremental engines.
    """

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
        prebound_vertices = dict(prebound_vertices or {})
        prebound_edges = dict(prebound_edges or {})
        initial_bindings = dict(initial_bindings or {})
        vertex_specs = pattern.vertex_map
        edge_specs = pattern.edge_map

        if not set(prebound_vertices) <= set(vertex_specs):
            raise MatchError("Prebound vertex key is not present in pattern")
        if not set(prebound_edges) <= set(edge_specs):
            raise MatchError("Prebound edge key is not present in pattern")

        for key, entity_id in prebound_vertices.items():
            if entity_id not in graph.vertices:
                return []
            spec = vertex_specs[key]
            actual = graph.vertices[entity_id]
            if not graph.schema.is_vertex_compatible(
                actual.type_id, spec.type_id, allow_subtypes=spec.allow_subtypes
            ):
                return []
        for key, entity_id in prebound_edges.items():
            if entity_id not in graph.edges or graph.edges[entity_id].type_id != edge_specs[key].type_id:
                return []

        candidates: dict[str, tuple[EntityId, ...]] = {}
        for key, spec in vertex_specs.items():
            if key in prebound_vertices:
                candidates[key] = (prebound_vertices[key],)
            else:
                compatible = [
                    entity_id
                    for entity_id, vertex in graph.vertices.items()
                    if graph.schema.is_vertex_compatible(
                        vertex.type_id, spec.type_id, allow_subtypes=spec.allow_subtypes
                    )
                ]
                candidates[key] = tuple(sorted(compatible))

        order = sorted(
            vertex_specs,
            key=lambda key: (0 if key in prebound_vertices else 1, len(candidates[key]), key),
        )
        matches: list[Match] = []

        def assign_vertices(
            index: int,
            vertex_map: dict[str, EntityId],
            used: set[EntityId],
            bindings: dict[str, Any],
        ) -> None:
            if index == len(order):
                assign_edges(0, vertex_map, {}, set(), bindings)
                return
            key = order[index]
            spec = vertex_specs[key]
            for entity_id in candidates[key]:
                if entity_id in used:
                    continue
                vertex = graph.vertices[entity_id]
                next_bindings = _match_attributes(spec.attributes, vertex.attributes, bindings)
                if next_bindings is None:
                    continue
                vertex_map[key] = entity_id
                used.add(entity_id)
                assign_vertices(index + 1, vertex_map, used, next_bindings)
                used.remove(entity_id)
                del vertex_map[key]

        edge_order = sorted(
            edge_specs,
            key=lambda key: (
                0 if key in prebound_edges else 1,
                len(graph.edges_by_type.get(edge_specs[key].type_id, ())),
                key,
            ),
        )

        def assign_edges(
            index: int,
            vertex_map: dict[str, EntityId],
            edge_map: dict[str, EntityId],
            used: set[EntityId],
            bindings: dict[str, Any],
        ) -> None:
            if index == len(edge_order):
                matches.append(
                    Match.create(
                        rule_id=rule_id,
                        vertex_map=vertex_map,
                        edge_map=edge_map,
                        bindings=bindings,
                        graph_epoch=graph.epoch,
                    )
                )
                return
            key = edge_order[index]
            spec = edge_specs[key]
            edge_candidates = (
                (prebound_edges[key],)
                if key in prebound_edges
                else tuple(sorted(graph.edges_by_type.get(spec.type_id, ())))
            )
            for entity_id in edge_candidates:
                if entity_id in used:
                    continue
                edge = graph.edges[entity_id]
                if not _edge_matches(graph, spec, edge, vertex_map):
                    continue
                next_bindings = _match_attributes(spec.attributes, edge.attributes, bindings)
                if next_bindings is None:
                    continue
                edge_map[key] = entity_id
                used.add(entity_id)
                assign_edges(index + 1, vertex_map, edge_map, used, next_bindings)
                used.remove(entity_id)
                del edge_map[key]

        assign_vertices(0, {}, set(), initial_bindings)
        unique = {match.match_id: match for match in matches}
        return [unique[key] for key in sorted(unique)]

    def condition_holds(
        self,
        graph: Hypergraph,
        condition: GraphCondition,
        base_match: Match,
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
        extra_context: dict[str, Any] | None = None,
    ) -> bool:
        prebound_vertices = {
            condition_key: base_match.vertex_map[left_key]
            for condition_key, left_key in condition.shared_vertices.items()
        }
        prebound_edges = {
            condition_key: base_match.edge_map[left_key]
            for condition_key, left_key in condition.shared_edges.items()
        }
        extensions = self.find_pattern_matches(
            graph,
            condition.pattern,
            rule_id=f"{base_match.rule_id}:condition",
            prebound_vertices=prebound_vertices,
            prebound_edges=prebound_edges,
            initial_bindings=base_match.bindings,
        )
        if condition.guard is not None:
            extensions = [
                match
                for match in extensions
                if bool(
                    condition.guard.evaluate(
                        build_expression_context(
                            graph,
                            match,
                            parameters=parameters,
                            memory=memory,
                            time=time,
                            extra=extra_context,
                        )
                    )
                )
            ]
        exists = bool(extensions)
        return exists if condition.polarity is ConditionPolarity.POSITIVE else not exists

    def _rule_match_holds(
        self,
        graph: Hypergraph,
        rule: Rule,
        match: Match,
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
    ) -> bool:
        context = build_expression_context(
            graph,
            match,
            parameters=parameters,
            memory=memory,
            time=time,
            extra={"meta": rule.meta},
        )
        if rule.guard is not None and not bool(rule.guard.evaluate(context)):
            return False
        return all(
            self.condition_holds(
                graph,
                condition,
                match,
                parameters=parameters,
                memory=memory,
                time=time,
                extra_context={"meta": rule.meta},
            )
            for condition in rule.conditions
        )

    def authoritative_rule_match(
        self,
        graph: Hypergraph,
        rule: Rule,
        match: Match,
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
    ) -> Match | None:
        """Re-derive a supplied match against the authoritative graph and rule."""
        if (
            not isinstance(match.vertex_map, Mapping)
            or not isinstance(match.edge_map, Mapping)
            or not isinstance(match.bindings, Mapping)
            or not rule.enabled
            or match.rule_id != rule.rule_id
            or match.graph_epoch != graph.epoch
            or set(match.vertex_map) != set(rule.left.vertex_map)
            or set(match.edge_map) != set(rule.left.edge_map)
            or any(
                not isinstance(entity_id, EntityId)
                for entity_id in match.vertex_map.values()
            )
            or any(
                not isinstance(entity_id, EntityId)
                for entity_id in match.edge_map.values()
            )
        ):
            return None
        try:
            candidates = self.find_pattern_matches(
                graph,
                rule.left,
                rule_id=rule.rule_id,
                prebound_vertices=match.vertex_map,
                prebound_edges=match.edge_map,
            )
        except (KeyError, MatchError, TypeError, ValueError):
            return None
        if len(candidates) != 1:
            return None
        authoritative = candidates[0]
        if (
            authoritative.vertex_map != match.vertex_map
            or authoritative.edge_map != match.edge_map
            or authoritative.match_id != match.match_id
            or set(authoritative.bindings) != set(match.bindings)
        ):
            return None
        try:
            if not canonical_equal(authoritative.bindings, match.bindings):
                return None
        except (TypeError, ValueError):
            return None
        if not self._rule_match_holds(
            graph,
            rule,
            authoritative,
            parameters=parameters,
            memory=memory,
            time=time,
        ):
            return None
        return authoritative

    def find_rule_matches(
        self,
        graph: Hypergraph,
        rule: Rule,
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
    ) -> list[Match]:
        if not rule.enabled:
            return []
        matches = self.find_pattern_matches(graph, rule.left, rule_id=rule.rule_id)
        return [
            match
            for match in matches
            if self._rule_match_holds(
                graph,
                rule,
                match,
                parameters=parameters,
                memory=memory,
                time=time,
            )
        ]
