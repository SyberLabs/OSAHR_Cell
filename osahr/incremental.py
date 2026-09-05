"""Exact incremental maintenance for typed hypergraph rule matches.

The exhaustive :class:`~osahr.matcher.Matcher` remains the semantic oracle.
This layer performs localized incremental-view maintenance only when completeness
is provable. Graph conditions (PAC/NAC) conservatively trigger full refreshes on
relevant edits because a remote edit can change an extension without touching
the base match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .canonical import canonical_equal
from .graph import GraphDelta, Hypergraph
from .ids import EntityId
from .indexed_matcher import IndexedMatcher
from .matcher import Match, Matcher
from .pattern import Rule


@dataclass(frozen=True, slots=True)
class RuleDependencySignature:
    rule_id: str
    vertex_types: frozenset[str]
    vertex_requirements: tuple[tuple[str, bool], ...]
    edge_types: frozenset[str]
    has_graph_conditions: bool
    reads_parameters: bool
    reads_memory: bool

    def relevant_to_types(
        self, schema: Any, vertex_types: set[str], edge_types: set[str]
    ) -> bool:
        if self.edge_types & edge_types:
            return True
        return any(
            schema.is_vertex_compatible(actual, expected, allow_subtypes=allow_subtypes)
            for actual in vertex_types
            for expected, allow_subtypes in self.vertex_requirements
        )

    @classmethod
    def compile(cls, rule: Rule) -> "RuleDependencySignature":
        expressions = [rule.hazard]
        if rule.guard is not None:
            expressions.append(rule.guard)
        expressions.extend(
            condition.guard for condition in rule.conditions if condition.guard is not None
        )
        names = set().union(*(expr.names for expr in expressions)) if expressions else set()
        vertex_requirements = {
            (item.type_id, item.allow_subtypes) for item in rule.left.vertices
        }
        edge_types = {item.type_id for item in rule.left.edges}
        for condition in rule.conditions:
            vertex_requirements.update(
                (item.type_id, item.allow_subtypes)
                for item in condition.pattern.vertices
            )
            edge_types.update(item.type_id for item in condition.pattern.edges)
        return cls(
            rule_id=rule.rule_id,
            vertex_types=frozenset(item[0] for item in vertex_requirements),
            vertex_requirements=tuple(sorted(vertex_requirements)),
            edge_types=frozenset(edge_types),
            has_graph_conditions=bool(rule.conditions),
            reads_parameters=bool({"p", "parameters"} & names),
            reads_memory=bool({"z", "memory"} & names),
        )


@dataclass(frozen=True, slots=True)
class MatchDelta:
    """Change set for one rule's match relation.

    ``revalidated`` contains match IDs that existed before and after but whose
    local structural/attribute context changed, so DPO applicability, guard
    results, or hazards must be recomputed. Unlisted matches are provably
    unaffected and may keep their stochastic clocks.
    """

    added: frozenset[str] = frozenset()
    removed: frozenset[str] = frozenset()
    revalidated: frozenset[str] = frozenset()

    @property
    def touched(self) -> frozenset[str]:
        return self.added | self.removed | self.revalidated


@dataclass(slots=True)
class RuleMatchCache:
    rule_id: str
    graph_epoch: int = -1
    matches: dict[str, Match] = field(default_factory=dict)
    entity_to_matches: dict[EntityId, set[str]] = field(default_factory=dict)

    def rebuild_reverse_index(self) -> None:
        reverse: dict[EntityId, set[str]] = {}
        for match_id, match in self.matches.items():
            for entity_id in (*match.vertex_map.values(), *match.edge_map.values()):
                reverse.setdefault(entity_id, set()).add(match_id)
        self.entity_to_matches = reverse

    def remove_match(self, match_id: str) -> Match | None:
        match = self.matches.pop(match_id, None)
        if match is None:
            return None
        for entity_id in (*match.vertex_map.values(), *match.edge_map.values()):
            bucket = self.entity_to_matches.get(entity_id)
            if bucket is None:
                continue
            bucket.discard(match_id)
            if not bucket:
                self.entity_to_matches.pop(entity_id, None)
        return match

    def set_match(self, match: Match) -> None:
        if match.match_id in self.matches:
            self.remove_match(match.match_id)
        self.matches[match.match_id] = match
        for entity_id in (*match.vertex_map.values(), *match.edge_map.values()):
            self.entity_to_matches.setdefault(entity_id, set()).add(match.match_id)


def delta_neighborhood(delta: GraphDelta) -> set[EntityId]:
    """Entities whose local matching or DPO context may have changed."""
    affected = set(delta.touched_entities())
    for edge in (*delta.created_edges.values(), *delta.deleted_edges.values()):
        affected.update(item.vertex_id for item in edge.incidences)
    return affected


def delta_types(graph: Hypergraph, delta: GraphDelta) -> tuple[set[str], set[str]]:
    vertex_types = {
        vertex.type_id
        for vertex in (*delta.created_vertices.values(), *delta.deleted_vertices.values())
    }
    edge_types = {
        edge.type_id for edge in (*delta.created_edges.values(), *delta.deleted_edges.values())
    }
    for entity_id in delta.updated_vertices_before:
        if entity_id in graph.vertices:
            vertex_types.add(graph.vertices[entity_id].type_id)
    for entity_id in delta.updated_edges_before:
        if entity_id in graph.edges:
            edge_types.add(graph.edges[entity_id].type_id)
    for edge in (*delta.created_edges.values(), *delta.deleted_edges.values()):
        for incidence in edge.incidences:
            if incidence.vertex_id in graph.vertices:
                vertex_types.add(graph.vertices[incidence.vertex_id].type_id)
            elif incidence.vertex_id in delta.deleted_vertices:
                vertex_types.add(delta.deleted_vertices[incidence.vertex_id].type_id)
    return vertex_types, edge_types


class IncrementalMatcher:
    """Exact local match cache with reference fallbacks."""

    def __init__(self, reference: Matcher | None = None) -> None:
        self.reference = reference or Matcher()
        self.indexed = IndexedMatcher()
        self.signatures: dict[str, RuleDependencySignature] = {}
        self.caches: dict[str, RuleMatchCache] = {}
        self.last_deltas: dict[str, MatchDelta] = {}
        self.full_recomputations = 0
        self.localized_recomputations = 0

    def _signature(self, rule: Rule) -> RuleDependencySignature:
        current = self.signatures.get(rule.rule_id)
        if current is None:
            current = RuleDependencySignature.compile(rule)
            self.signatures[rule.rule_id] = current
        return current

    def invalidate_rule_definition(self, rule_id: str) -> None:
        self.signatures.pop(rule_id, None)
        self.caches.pop(rule_id, None)
        self.last_deltas.pop(rule_id, None)

    def clear(self) -> None:
        self.signatures.clear()
        self.caches.clear()
        self.last_deltas.clear()

    def _full(
        self,
        graph: Hypergraph,
        rule: Rule,
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
    ) -> RuleMatchCache:
        old = self.caches.get(rule.rule_id)
        old_ids = set() if old is None else set(old.matches)
        matches = self.indexed.find_rule_matches(
            graph, rule, parameters=parameters, memory=memory, time=time
        )
        cache = old or RuleMatchCache(rule.rule_id)
        cache.matches = {match.match_id: match for match in matches}
        cache.graph_epoch = graph.epoch
        cache.rebuild_reverse_index()
        new_ids = set(cache.matches)
        self.caches[rule.rule_id] = cache
        self.last_deltas[rule.rule_id] = MatchDelta(
            frozenset(new_ids - old_ids),
            frozenset(old_ids - new_ids),
            frozenset(old_ids & new_ids),
        )
        self.full_recomputations += 1
        return cache

    def _filter_candidates(
        self,
        graph: Hypergraph,
        rule: Rule,
        candidates: Iterable[Match],
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
    ) -> list[Match]:
        return [
            match
            for match in candidates
            if self.reference._rule_match_holds(
                graph,
                rule,
                match,
                parameters=parameters,
                memory=memory,
                time=time,
            )
        ]

    def _localized_candidates(
        self,
        graph: Hypergraph,
        rule: Rule,
        anchors: set[EntityId],
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
    ) -> dict[str, Match]:
        found: dict[str, Match] = {}
        left_vertices = rule.left.vertex_map
        left_edges = rule.left.edge_map
        for entity_id in sorted(anchors):
            if entity_id in graph.vertices:
                vertex = graph.vertices[entity_id]
                for key, spec in left_vertices.items():
                    if not graph.schema.is_vertex_compatible(
                        vertex.type_id, spec.type_id, allow_subtypes=spec.allow_subtypes
                    ):
                        continue
                    candidates = self.indexed.find_pattern_matches(
                        graph,
                        rule.left,
                        rule_id=rule.rule_id,
                        prebound_vertices={key: entity_id},
                    )
                    for match in self._filter_candidates(
                        graph,
                        rule,
                        candidates,
                        parameters=parameters,
                        memory=memory,
                        time=time,
                    ):
                        found[match.match_id] = match
            if entity_id in graph.edges:
                edge = graph.edges[entity_id]
                for key, spec in left_edges.items():
                    if edge.type_id != spec.type_id:
                        continue
                    candidates = self.indexed.find_pattern_matches(
                        graph,
                        rule.left,
                        rule_id=rule.rule_id,
                        prebound_edges={key: entity_id},
                    )
                    for match in self._filter_candidates(
                        graph,
                        rule,
                        candidates,
                        parameters=parameters,
                        memory=memory,
                        time=time,
                    ):
                        found[match.match_id] = match
        return found

    def update_rule(
        self,
        graph: Hypergraph,
        rule: Rule,
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
        delta: GraphDelta | None = None,
        state_changed: bool = False,
        force: bool = False,
    ) -> RuleMatchCache:
        if not rule.enabled:
            old = self.caches.get(rule.rule_id)
            removed = frozenset(() if old is None else old.matches.keys())
            cache = RuleMatchCache(rule.rule_id, graph.epoch)
            self.caches[rule.rule_id] = cache
            self.last_deltas[rule.rule_id] = MatchDelta(removed=removed)
            return cache

        cache = self.caches.get(rule.rule_id)
        signature = self._signature(rule)
        if force:
            return self._full(
                graph, rule, parameters=parameters, memory=memory, time=time
            )
        if cache is None or cache.graph_epoch < 0:
            return self._full(
                graph, rule, parameters=parameters, memory=memory, time=time
            )

        if state_changed or delta is None:
            if cache.graph_epoch != graph.epoch or state_changed:
                return self._full(
                    graph, rule, parameters=parameters, memory=memory, time=time
                )
            self.last_deltas[rule.rule_id] = MatchDelta()
            return cache

        if cache.graph_epoch == graph.epoch:
            self.last_deltas[rule.rule_id] = MatchDelta()
            return cache

        changed_vertex_types, changed_edge_types = delta_types(graph, delta)
        relevant = signature.relevant_to_types(
            graph.schema, changed_vertex_types, changed_edge_types
        )
        if signature.has_graph_conditions and relevant:
            return self._full(
                graph, rule, parameters=parameters, memory=memory, time=time
            )
        if not relevant:
            # The relation is unchanged. Individual Match objects retain the epoch
            # at which their bindings were last checked; runtime selection stamps a
            # fresh epoch only for the chosen occurrence.
            cache.graph_epoch = graph.epoch
            self.last_deltas[rule.rule_id] = MatchDelta()
            return cache

        affected = delta_neighborhood(delta)
        invalid_ids: set[str] = set()
        for entity_id in affected:
            invalid_ids.update(cache.entity_to_matches.get(entity_id, ()))
        for match_id in invalid_ids:
            cache.remove_match(match_id)

        local = self._localized_candidates(
            graph,
            rule,
            {
                entity_id
                for entity_id in affected
                if entity_id in graph.vertices or entity_id in graph.edges
            },
            parameters=parameters,
            memory=memory,
            time=time,
        )
        local_ids = set(local)
        # Only local IDs are needed to classify this delta. Do not copy the
        # entire cached relation on every sparse graph edit.
        retained_ids = {match_id for match_id in local_ids if match_id in cache.matches}
        old_local_ids = retained_ids | (local_ids & invalid_ids)
        for match in local.values():
            cache.set_match(match)

        cache.graph_epoch = graph.epoch
        self.last_deltas[rule.rule_id] = MatchDelta(
            added=frozenset(local_ids - old_local_ids),
            removed=frozenset(invalid_ids - local_ids),
            revalidated=frozenset(old_local_ids),
        )
        self.localized_recomputations += 1
        return cache

    def find_rule_matches(
        self,
        graph: Hypergraph,
        rule: Rule,
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
        delta: GraphDelta | None = None,
        state_changed: bool = False,
        force: bool = False,
    ) -> list[Match]:
        cache = self.update_rule(
            graph,
            rule,
            parameters=parameters,
            memory=memory,
            time=time,
            delta=delta,
            state_changed=state_changed,
            force=force,
        )
        return [cache.matches[key] for key in sorted(cache.matches)]

    def assert_equivalent(
        self,
        graph: Hypergraph,
        rule: Rule,
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
    ) -> None:
        expected = self.reference.find_rule_matches(
            graph, rule, parameters=parameters, memory=memory, time=time
        )
        cache = self.caches.get(rule.rule_id)
        actual_ids = [] if cache is None else sorted(cache.matches)
        expected_ids = sorted(item.match_id for item in expected)
        if actual_ids != expected_ids:
            raise AssertionError(
                f"Incremental matcher diverged for rule {rule.rule_id!r}: "
                f"actual={len(actual_ids)} expected={len(expected_ids)}"
            )
        for match in expected:
            if not canonical_equal(cache.matches[match.match_id].bindings, match.bindings):
                raise AssertionError(
                    f"Incremental bindings diverged for rule {rule.rule_id!r}, "
                    f"match {match.match_id!r}"
                )
