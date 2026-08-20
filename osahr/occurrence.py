"""Dependency-indexed stochastic occurrence maintenance.

The occurrence index sits between matching and stochastic scheduling. It stores
only *applicable* DPO occurrences, evaluates hazards under the current augmented
state, and maintains a two-level weighted index (rule -> match) for O(log R) +
O(log M_r) exact selection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .errors import HazardBoundError, HazardError, ResourceLimitError
from .graph import GraphDelta, Hypergraph
from .incremental import IncrementalMatcher, RuleDependencySignature, delta_types
from .matcher import Match, Matcher, build_expression_context
from .pattern import Rule
from .rewrite import RewriteEngine
from .weighted import WeightedIndex
from .boundary import BoundaryState


@dataclass(frozen=True, slots=True)
class OccurrenceKey:
    rule_id: str
    match_id: str


@dataclass(frozen=True, slots=True)
class Occurrence:
    key: OccurrenceKey
    rule: Rule
    match: Match
    hazard: float


@dataclass(frozen=True, slots=True)
class OccurrenceDelta:
    added: frozenset[OccurrenceKey] = frozenset()
    removed: frozenset[OccurrenceKey] = frozenset()
    changed: frozenset[OccurrenceKey] = frozenset()

    @property
    def touched(self) -> frozenset[OccurrenceKey]:
        return self.added | self.removed | self.changed


class OccurrenceIndex:
    def __init__(
        self,
        *,
        matcher_backend: str = "incremental",
        max_matches_per_rule: int = 5_000_000,
        max_total_activity: float = 1e300,
        invalid_hazard_policy: str = "raise",
    ) -> None:
        if matcher_backend not in {"incremental", "reference"}:
            raise ValueError("matcher_backend must be incremental or reference")
        self.reference = Matcher()
        self.incremental = IncrementalMatcher(self.reference)
        self.matcher_backend = matcher_backend
        self.rewrite_engine = RewriteEngine()
        self.max_matches_per_rule = max_matches_per_rule
        self.max_total_activity = max_total_activity
        self.invalid_hazard_policy = invalid_hazard_policy
        self.occurrences: dict[OccurrenceKey, Occurrence] = {}
        self.rule_match_weights: dict[str, WeightedIndex[str]] = {}
        self.rule_weights: WeightedIndex[str] = WeightedIndex()
        self.graph_epoch: int = -1
        self._initialized = False

    def clear(self) -> None:
        self.incremental.clear()
        self.occurrences.clear()
        self.rule_match_weights.clear()
        self.rule_weights.clear()
        self.graph_epoch = -1
        self._initialized = False

    def invalidate_rule(self, rule_id: str) -> None:
        self.incremental.invalidate_rule_definition(rule_id)
        for key in [key for key in self.occurrences if key.rule_id == rule_id]:
            del self.occurrences[key]
        self.rule_match_weights.pop(rule_id, None)
        self.rule_weights.remove(rule_id)

    @staticmethod
    def _context(
        graph: Hypergraph,
        rule: Rule,
        match: Match,
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        combined = {"meta": rule.meta}
        if extra:
            combined.update(extra)
        return build_expression_context(
            graph,
            match,
            parameters=parameters,
            memory=memory,
            time=time,
            extra=combined,
        )

    def _hazard(
        self,
        graph: Hypergraph,
        rule: Rule,
        match: Match,
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
    ) -> float | None:
        context = self._context(
            graph,
            rule,
            match,
            parameters=parameters,
            memory=memory,
            time=time,
        )
        try:
            value = float(rule.hazard.evaluate(context))
        except Exception as exc:
            if self.invalid_hazard_policy == "disable_occurrence":
                return None
            raise HazardError(
                f"Hazard evaluation failed for {rule.rule_id}/{match.match_id}"
            ) from exc
        if not math.isfinite(value) or value < 0.0:
            if self.invalid_hazard_policy == "disable_occurrence":
                return None
            raise HazardError(
                f"Invalid hazard {value!r} for {rule.rule_id}/{match.match_id}"
            )
        return value

    def hazard_at(
        self,
        occurrence: Occurrence,
        *,
        graph: Hypergraph,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
    ) -> float:
        value = self._hazard(
            graph,
            occurrence.rule,
            occurrence.match,
            parameters=parameters,
            memory=memory,
            time=time,
        )
        return 0.0 if value is None else value

    def bound_at(
        self,
        occurrence: Occurrence,
        *,
        graph: Hypergraph,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
        horizon: float,
    ) -> float:
        rule = occurrence.rule
        if rule.hazard_upper_bound is None:
            # Time-independent rules need no separate contract.
            return self.hazard_at(
                occurrence,
                graph=graph,
                parameters=parameters,
                memory=memory,
                time=time,
            )
        context = self._context(
            graph,
            rule,
            occurrence.match,
            parameters=parameters,
            memory=memory,
            time=time,
            extra={"horizon": horizon},
        )
        try:
            bound = float(rule.hazard_upper_bound.evaluate(context))
        except Exception as exc:
            raise HazardBoundError(
                f"Hazard bound evaluation failed for {rule.rule_id}/{occurrence.match.match_id}"
            ) from exc
        if not math.isfinite(bound) or bound < 0.0:
            raise HazardBoundError(
                f"Invalid hazard upper bound {bound!r} for {rule.rule_id}/{occurrence.match.match_id}"
            )
        actual = self.hazard_at(
            occurrence,
            graph=graph,
            parameters=parameters,
            memory=memory,
            time=time,
        )
        tolerance = 1e-12 * max(1.0, abs(bound), abs(actual))
        if actual > bound + tolerance:
            raise HazardBoundError(
                f"Declared bound {bound!r} is below current hazard {actual!r} for "
                f"{rule.rule_id}/{occurrence.match.match_id}"
            )
        return bound

    def integrated_hazard(
        self,
        occurrence: Occurrence,
        *,
        graph: Hypergraph,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        start_time: float,
        end_time: float,
    ) -> float | None:
        """Return the exact occurrence hazard integral over a frozen state.

        ``None`` means that event generation remains exact (e.g. by thinning)
        but the model did not declare enough analytic information to attach an
        exact likelihood survival term to the trajectory.
        """
        if end_time < start_time:
            raise HazardError("Hazard integration interval cannot run backwards")
        if end_time == start_time:
            return 0.0
        rule = occurrence.rule
        if rule.hazard_integral is None:
            if "time" in rule.hazard.names:
                return None
            return self.hazard_at(
                occurrence,
                graph=graph,
                parameters=parameters,
                memory=memory,
                time=start_time,
            ) * (end_time - start_time)

        context = self._context(
            graph,
            rule,
            occurrence.match,
            parameters=parameters,
            memory=memory,
            time=start_time,
            extra={"horizon": end_time},
        )
        try:
            value = float(rule.hazard_integral.evaluate(context))
        except Exception as exc:
            raise HazardError(
                f"Hazard integral evaluation failed for {rule.rule_id}/{occurrence.match.match_id}"
            ) from exc
        if not math.isfinite(value) or value < 0.0:
            raise HazardError(
                f"Invalid hazard integral {value!r} for {rule.rule_id}/{occurrence.match.match_id}"
            )
        return value

    def _matches_for_rule(
        self,
        graph: Hypergraph,
        rule: Rule,
        *,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
        delta: GraphDelta | None,
        state_changed: bool,
        force: bool = False,
    ) -> list[Match]:
        if self.matcher_backend == "reference":
            return self.reference.find_rule_matches(
                graph,
                rule,
                parameters=parameters,
                memory=memory,
                time=time,
            )
        return self.incremental.find_rule_matches(
            graph,
            rule,
            parameters=parameters,
            memory=memory,
            time=time,
            delta=delta,
            state_changed=state_changed,
            force=force,
        )

    def _rule_relevant_to_delta(
        self, graph: Hypergraph, rule: Rule, delta: GraphDelta
    ) -> bool:
        signature = self.incremental.signatures.get(rule.rule_id)
        if signature is None:
            signature = RuleDependencySignature.compile(rule)
            self.incremental.signatures[rule.rule_id] = signature
        vertex_types, edge_types = delta_types(graph, delta)
        return signature.relevant_to_types(graph.schema, vertex_types, edge_types)

    def _evaluate_occurrence(
        self,
        *,
        graph: Hypergraph,
        boundary: BoundaryState,
        rule: Rule,
        match: Match,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
    ) -> Occurrence | None:
        if not self.rewrite_engine.is_applicable(
            graph=graph, boundary=boundary, rule=rule, match=match
        ):
            return None
        hazard = self._hazard(
            graph,
            rule,
            match,
            parameters=parameters,
            memory=memory,
            time=time,
        )
        if hazard is None:
            return None
        key = OccurrenceKey(rule.rule_id, match.match_id)
        return Occurrence(key, rule, match, hazard)

    def refresh(
        self,
        *,
        graph: Hypergraph,
        boundary: BoundaryState,
        rules: dict[str, Rule],
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
        delta: GraphDelta | None = None,
        state_changed: bool = False,
        force: bool = False,
    ) -> OccurrenceDelta:
        """Synchronize enabled stochastic channels with the augmented state.

        In incremental mode, an ordinary local graph delta only revisits match
        IDs reported by :class:`IncrementalMatcher` as added, removed, or
        revalidated. Untouched occurrences retain both their cached hazard and
        (for modified-next-reaction scheduling) their stochastic internal clock.

        Parameter/memory changes, boundary changes represented by ``force``,
        first initialization, and reference-matcher mode intentionally use the
        exhaustive path.
        """

        old = dict(self.occurrences)
        new = dict(old)
        full_refresh = (
            force
            or not self._initialized
            or state_changed
            or delta is None
            or self.matcher_backend == "reference"
        )

        # Remove rule definitions that no longer exist.
        removed_rule_ids = {key.rule_id for key in old} - set(rules)
        for rule_id in sorted(removed_rule_ids):
            for key in [key for key in new if key.rule_id == rule_id]:
                del new[key]
            self.incremental.invalidate_rule_definition(rule_id)

        if full_refresh:
            rule_ids = sorted(rules)
        else:
            assert delta is not None
            rule_ids = [
                rule_id
                for rule_id, rule in sorted(rules.items())
                if self._rule_relevant_to_delta(graph, rule, delta)
            ]

        if full_refresh:
            # All stochastic eligibility/hazards may have changed. Recompute each
            # rule exactly. ``force`` also refreshes incremental match caches so a
            # changed dynamic rule definition cannot reuse a stale relation.
            new = {
                key: value
                for key, value in new.items()
                if key.rule_id not in set(rule_ids)
            }
            for rule_id in rule_ids:
                rule = rules[rule_id]
                matches = self._matches_for_rule(
                    graph,
                    rule,
                    parameters=parameters,
                    memory=memory,
                    time=time,
                    delta=delta,
                    state_changed=state_changed,
                    force=force or not self._initialized,
                )
                if len(matches) > self.max_matches_per_rule:
                    raise ResourceLimitError(
                        f"Rule {rule.rule_id!r} exceeded max_matches_per_rule"
                    )
                for match in matches:
                    occurrence = self._evaluate_occurrence(
                        graph=graph,
                        boundary=boundary,
                        rule=rule,
                        match=match,
                        parameters=parameters,
                        memory=memory,
                        time=time,
                    )
                    if occurrence is not None:
                        new[occurrence.key] = occurrence
        else:
            # Exact local maintenance: only match IDs whose local relation or DPO
            # context changed are reconsidered.
            for rule_id in rule_ids:
                rule = rules[rule_id]
                cache = self.incremental.update_rule(
                    graph,
                    rule,
                    parameters=parameters,
                    memory=memory,
                    time=time,
                    delta=delta,
                    state_changed=False,
                )
                if len(cache.matches) > self.max_matches_per_rule:
                    raise ResourceLimitError(
                        f"Rule {rule.rule_id!r} exceeded max_matches_per_rule"
                    )
                match_delta = self.incremental.last_deltas[rule_id]
                for match_id in match_delta.removed:
                    new.pop(OccurrenceKey(rule_id, match_id), None)
                for match_id in sorted(match_delta.added | match_delta.revalidated):
                    key = OccurrenceKey(rule_id, match_id)
                    match = cache.matches.get(match_id)
                    if match is None:
                        new.pop(key, None)
                        continue
                    occurrence = self._evaluate_occurrence(
                        graph=graph,
                        boundary=boundary,
                        rule=rule,
                        match=match,
                        parameters=parameters,
                        memory=memory,
                        time=time,
                    )
                    if occurrence is None:
                        new.pop(key, None)
                    else:
                        new[key] = occurrence

        old_keys = set(old)
        new_keys = set(new)
        added = new_keys - old_keys
        removed = old_keys - new_keys
        changed = {
            key
            for key in old_keys & new_keys
            if old[key].hazard != new[key].hazard
            or old[key].rule.hash != new[key].rule.hash
            or old[key].match != new[key].match
        }
        occurrence_delta = OccurrenceDelta(
            frozenset(added), frozenset(removed), frozenset(changed)
        )

        was_initialized = self._initialized
        self.occurrences = new
        self.graph_epoch = graph.epoch
        self._initialized = True
        if full_refresh or not was_initialized:
            self._rebuild_weights()
        else:
            self._apply_weight_delta(occurrence_delta)
        return occurrence_delta

    def _apply_weight_delta(self, delta: OccurrenceDelta) -> None:
        touched_rules: set[str] = set()
        for key in sorted(delta.removed, key=lambda item: (item.rule_id, item.match_id)):
            index = self.rule_match_weights.get(key.rule_id)
            if index is not None:
                index.remove(key.match_id)
                touched_rules.add(key.rule_id)
        for key in sorted(delta.added | delta.changed, key=lambda item: (item.rule_id, item.match_id)):
            occurrence = self.occurrences[key]
            index = self.rule_match_weights.setdefault(key.rule_id, WeightedIndex())
            index.set(key.match_id, occurrence.hazard)
            touched_rules.add(key.rule_id)
        for rule_id in sorted(touched_rules):
            index = self.rule_match_weights.get(rule_id)
            if index is None or len(index) == 0:
                self.rule_match_weights.pop(rule_id, None)
                self.rule_weights.remove(rule_id)
                continue
            if index.total > 0.0:
                self.rule_weights.set(rule_id, index.total)
            else:
                self.rule_weights.remove(rule_id)
        if not math.isfinite(self.total_activity) or self.total_activity > self.max_total_activity:
            raise ResourceLimitError(
                f"Total activity {self.total_activity!r} exceeds configured limit"
            )

    def _rebuild_weights(self) -> None:
        self.rule_match_weights = {}
        by_rule: dict[str, list[Occurrence]] = {}
        for occurrence in self.occurrences.values():
            by_rule.setdefault(occurrence.rule.rule_id, []).append(occurrence)
        self.rule_weights = WeightedIndex()
        for rule_id in sorted(by_rule):
            index: WeightedIndex[str] = WeightedIndex()
            for occurrence in sorted(by_rule[rule_id], key=lambda item: item.match.match_id):
                index.set(occurrence.match.match_id, occurrence.hazard)
            self.rule_match_weights[rule_id] = index
            if index.total > 0.0:
                self.rule_weights.set(rule_id, index.total)
        if not math.isfinite(self.total_activity) or self.total_activity > self.max_total_activity:
            raise ResourceLimitError(
                f"Total activity {self.total_activity!r} exceeds configured limit"
            )

    @property
    def total_activity(self) -> float:
        return self.rule_weights.total

    def all(self) -> tuple[Occurrence, ...]:
        return tuple(self.occurrences[key] for key in sorted(self.occurrences, key=lambda k: (k.rule_id, k.match_id)))

    def select(self, unit_rule: float, unit_match: float) -> Occurrence:
        selected_rule = self.rule_weights.select(unit_rule).key
        selected_match = self.rule_match_weights[selected_rule].select(unit_match).key
        return self.occurrences[OccurrenceKey(selected_rule, selected_match)]

    def hazards_at(
        self,
        *,
        graph: Hypergraph,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        time: float,
    ) -> dict[OccurrenceKey, float]:
        return {
            key: self.hazard_at(
                occurrence,
                graph=graph,
                parameters=parameters,
                memory=memory,
                time=time,
            )
            for key, occurrence in self.occurrences.items()
        }
