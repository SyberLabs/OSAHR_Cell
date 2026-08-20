"""Authoritative runtime for open stochastic adaptive hypergraph rewriting.

The runtime supports three exact stochastic regimes:

* ``direct_ssa`` for piecewise-constant hazards,
* ``next_reaction`` for sparse dependency-local piecewise-constant hazards,
* ``thinning`` for time-inhomogeneous hazards with declared finite-window bounds.

All state-changing events are serialized. Pattern matching may be maintained
incrementally, but the exhaustive matcher remains available as an oracle.
"""

from __future__ import annotations

import copy
import heapq
import math
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable

from .adaptive import AdaptiveParameter, AdaptiveRegistry
from .boundary import (
    BoundaryDelta,
    BoundaryDirection,
    BoundaryState,
    ExternalEvent,
    InputMode,
    OutputEvent,
)
from .canonical import stable_hash
from .errors import (
    HazardBoundError,
    ReplayError,
    ResourceLimitError,
    SchedulerError,
    ValidationError,
)
from .events import EventKind, EventRecord, StepResult, StepStatus
from .expr import evaluate_value, set_path
from .graph import GraphDelta, Hypergraph
from .matcher import Match, Matcher
from .meta import MetaRuleAction, MetaRuleEvent, RuleTemplate
from .observables import Observable
from .occurrence import Occurrence, OccurrenceDelta, OccurrenceIndex, OccurrenceKey
from .pattern import Rule, StateAssignment
from .rewrite import RewriteEngine, RewriteResult
from .rng import RandomDraw, RandomStreams
from .schedulers import (
    NextReactionScheduler,
    NextReactionSnapshot,
    SchedulerKind,
    ThinningAudit,
)


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    max_events: int = 10_000_000
    max_vertices: int = 1_000_000
    max_edges: int = 1_000_000
    max_incidences: int = 10_000_000
    max_matches_per_rule: int = 5_000_000
    max_total_activity: float = 1e300
    max_simulation_time: float = math.inf
    max_events_per_time_window: int = 100_000
    explosion_window: float = 1e-12
    invalid_hazard_policy: str = "raise"  # raise | disable_occurrence

    scheduler: SchedulerKind | str = SchedulerKind.DIRECT_SSA
    matcher_backend: str = "incremental"  # incremental | reference
    incremental_verify: bool = False

    thinning_window: float = 1.0
    max_thinning_windows_per_plan: int = 100_000

    def __post_init__(self) -> None:
        if self.invalid_hazard_policy not in {"raise", "disable_occurrence"}:
            raise ValueError("invalid_hazard_policy must be raise or disable_occurrence")
        if self.max_events <= 0:
            raise ValueError("max_events must be positive")
        if self.matcher_backend not in {"incremental", "reference"}:
            raise ValueError("matcher_backend must be incremental or reference")
        try:
            SchedulerKind(self.scheduler)
        except ValueError as exc:
            raise ValueError(f"Unknown scheduler {self.scheduler!r}") from exc
        if not math.isfinite(self.thinning_window) or self.thinning_window <= 0.0:
            raise ValueError("thinning_window must be finite and positive")
        if self.max_thinning_windows_per_plan <= 0:
            raise ValueError("max_thinning_windows_per_plan must be positive")

    @property
    def scheduler_kind(self) -> SchedulerKind:
        return SchedulerKind(self.scheduler)


@dataclass(frozen=True, slots=True, order=True)
class ScheduledAdaptation:
    simulation_time: float
    source_sequence: int
    update_id: str = field(compare=False)
    assignments: tuple[StateAssignment, ...] = field(compare=False)


@dataclass(frozen=True, slots=True)
class EnabledOccurrence:
    rule: Rule
    match: Match
    hazard: float


@dataclass(slots=True)
class PendingInternalEvent:
    absolute_time: float
    occurrence: EnabledOccurrence
    draws: list[RandomDraw]
    planned_at_time: float
    planned_state_hash: str
    total_activity: float
    scheduler_kind: SchedulerKind = SchedulerKind.DIRECT_SSA
    survival_integral_exact: bool = True
    survival_integral: float | None = None


@dataclass(slots=True)
class RuntimeSnapshot:
    graph: Hypergraph
    boundary: BoundaryState
    rules: dict[str, Rule]
    parameters: dict[str, Any]
    memory: dict[str, Any]
    time: float
    last_event_time: float
    event_index: int
    root_seed: int
    rng_states: dict[str, tuple[int, int, int, int]]
    external_queue: list[ExternalEvent]
    adaptation_queue: list[ScheduledAdaptation]
    meta_queue: list[MetaRuleEvent]
    pending_internal: PendingInternalEvent | None
    output_events: list[OutputEvent]
    run_id: str
    scheduler_kind: SchedulerKind
    next_reaction_snapshot: NextReactionSnapshot | None = None
    next_reaction_initialized: bool = False
    thinning_audit: ThinningAudit = field(default_factory=ThinningAudit)


@dataclass(slots=True)
class Model:
    graph: Hypergraph
    boundary: BoundaryState
    rules: tuple[Rule, ...]
    parameters: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    model_id: str = "model"
    version: str = "1.0.0"
    adaptive_parameters: tuple[AdaptiveParameter, ...] = ()
    rule_templates: tuple[RuleTemplate, ...] = ()
    hash: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValidationError("Duplicate rule IDs")
        template_ids = [template.template_id for template in self.rule_templates]
        if len(template_ids) != len(set(template_ids)):
            raise ValidationError("Duplicate rule template IDs")
        self.boundary.validate(set(self.graph.vertices))
        for handle in self.boundary.handles.values():
            if handle.binding is not None:
                vertex_type = self.graph.vertices[handle.binding].type_id
                if not self.graph.schema.is_vertex_compatible(vertex_type, handle.interface_type):
                    raise ValidationError(
                        f"Boundary {handle.handle_id!r} expects {handle.interface_type}, "
                        f"got {vertex_type}"
                    )
        AdaptiveRegistry(self.adaptive_parameters).validate(self.parameters)
        object.__setattr__(self, "hash", stable_hash(self.to_canonical()))

    def to_canonical(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "schema_hash": self.graph.schema.hash,
            "graph": self.graph.to_canonical(),
            "boundary": self.boundary.to_canonical(),
            "rules": [rule.hash for rule in sorted(self.rules, key=lambda item: item.rule_id)],
            "parameters": self.parameters,
            "memory": self.memory,
            "adaptive_parameters": self.adaptive_parameters,
            "rule_templates": [
                {
                    "template_id": template.template_id,
                    "version": template.version,
                    "prototype_hash": template.prototype.hash,
                    "parameters": template.parameters,
                    "max_instances": template.max_instances,
                }
                for template in sorted(self.rule_templates, key=lambda item: item.template_id)
            ],
        }


class Runtime:
    RUNTIME_VERSION = "osahr-python-0.2.0"

    def __init__(
        self,
        model: Model,
        *,
        root_seed: int,
        config: RuntimeConfig | None = None,
    ) -> None:
        self.model_hash = model.hash
        self.graph = model.graph.clone()
        self.boundary = model.boundary.clone()
        self.rules = {rule.rule_id: rule for rule in model.rules}
        self.rule_templates = {template.template_id: template for template in model.rule_templates}
        self.parameters = copy.deepcopy(model.parameters)
        self.memory = copy.deepcopy(model.memory)
        self.adaptive_registry = AdaptiveRegistry(model.adaptive_parameters)
        self.adaptive_registry.validate(self.parameters)

        self.time = 0.0
        self.last_event_time = 0.0
        self.event_index = 0
        self.root_seed = root_seed
        self.config = config or RuntimeConfig()
        self.scheduler_kind = self.config.scheduler_kind
        self._validate_scheduler_contract()

        self.rewrite_engine = RewriteEngine()
        self.occurrence_index = OccurrenceIndex(
            matcher_backend=self.config.matcher_backend,
            max_matches_per_rule=self.config.max_matches_per_rule,
            max_total_activity=self.config.max_total_activity,
            invalid_hazard_policy=self.config.invalid_hazard_policy,
        )
        # Preserve the public correctness-first matcher handle.
        self.matcher: Matcher = self.occurrence_index.reference
        self.random = RandomStreams(root_seed)

        self.external_queue: list[ExternalEvent] = []
        self.adaptation_queue: list[ScheduledAdaptation] = []
        self.meta_queue: list[MetaRuleEvent] = []
        self.pending_internal: PendingInternalEvent | None = None

        self.next_reaction = NextReactionScheduler()
        self._next_reaction_initialized = False
        self.thinning_audit = ThinningAudit()

        self.event_log: list[EventRecord] = []
        self.output_events: list[OutputEvent] = []
        self.observables: dict[str, Observable] = {}
        self._recent_event_times: deque[float] = deque()
        self._indexed_augmented_hash: str | None = None

        self.run_id = stable_hash(
            {
                "model_hash": self.model_hash,
                "initial_graph": self.graph.state_hash,
                "root_seed": root_seed,
                "runtime": self.RUNTIME_VERSION,
                "scheduler": self.scheduler_kind.value,
                "matcher": self.config.matcher_backend,
            }
        )
        self._validate_limits()

    # ------------------------------------------------------------------
    # State identity and contracts
    # ------------------------------------------------------------------

    def _validate_scheduler_contract(self) -> None:
        time_names = {"time", "delta_time", "horizon"}
        time_dependent = [
            rule.rule_id for rule in self.rules.values() if time_names & rule.hazard.names
        ]
        if time_dependent and self.scheduler_kind is not SchedulerKind.THINNING:
            raise ValidationError(
                f"Scheduler {self.scheduler_kind.value} does not support continuously "
                f"time-varying hazards; use thinning for rules {time_dependent!r}"
            )

    def _rule_state_canonical(self) -> list[tuple[str, str]]:
        return [(rule_id, self.rules[rule_id].hash) for rule_id in sorted(self.rules)]

    def _state_hash_at(self, time_value: float) -> str:
        return stable_hash(
            {
                "graph": self.graph.to_canonical(),
                "boundary": self.boundary.to_canonical(),
                "rules": self._rule_state_canonical(),
                "parameters": self.parameters,
                "memory": self.memory,
                "time": time_value,
                "event_index": self.event_index,
            }
        )

    @property
    def state_hash(self) -> str:
        return self._state_hash_at(self.time)

    def _augmented_index_hash(self) -> str:
        return stable_hash(
            {
                "graph_epoch": self.graph.epoch,
                "boundary": self.boundary.to_canonical(),
                "rules": self._rule_state_canonical(),
                "parameters": self.parameters,
                "memory": self.memory,
            }
        )

    # ------------------------------------------------------------------
    # Public observation and exogenous scheduling
    # ------------------------------------------------------------------

    def register_observable(self, observable: Observable) -> None:
        if observable.observable_id in self.observables:
            raise ValidationError(f"Duplicate observable {observable.observable_id!r}")
        self.observables[observable.observable_id] = observable

    def observe(self, observable_id: str) -> Any:
        return self.observables[observable_id].evaluate(
            self.graph, self.parameters, self.memory
        )

    def inject(self, event: ExternalEvent) -> None:
        if event.simulation_time < self.time:
            raise ValidationError("Cannot inject an event in the simulation past")
        if event.handle_id not in self.boundary.handles:
            raise ValidationError(f"Unknown boundary handle {event.handle_id!r}")
        heapq.heappush(self.external_queue, event)

    def schedule_adaptation(self, update: ScheduledAdaptation) -> None:
        if update.simulation_time < self.time:
            raise ValidationError("Cannot schedule adaptation in the simulation past")
        heapq.heappush(self.adaptation_queue, update)

    def schedule_meta(self, event: MetaRuleEvent) -> None:
        if event.simulation_time < self.time:
            raise ValidationError("Cannot schedule meta-rule update in the simulation past")
        heapq.heappush(self.meta_queue, event)

    # ------------------------------------------------------------------
    # Limits and occurrence maintenance
    # ------------------------------------------------------------------

    def _validate_limits(self) -> None:
        incidence_count = sum(len(edge.incidences) for edge in self.graph.edges.values())
        if len(self.graph.vertices) > self.config.max_vertices:
            raise ResourceLimitError("Vertex limit exceeded")
        if len(self.graph.edges) > self.config.max_edges:
            raise ResourceLimitError("Edge limit exceeded")
        if incidence_count > self.config.max_incidences:
            raise ResourceLimitError("Incidence limit exceeded")
        if self.event_index > self.config.max_events:
            raise ResourceLimitError("Event limit exceeded")
        if self.time > self.config.max_simulation_time:
            raise ResourceLimitError("Simulation-time limit exceeded")

    def _record_event_time(self) -> None:
        self._recent_event_times.append(self.time)
        threshold = self.time - self.config.explosion_window
        while self._recent_event_times and self._recent_event_times[0] < threshold:
            self._recent_event_times.popleft()
        if len(self._recent_event_times) > self.config.max_events_per_time_window:
            raise ResourceLimitError("Potential stochastic explosion detected")

    def _verify_incremental(self) -> None:
        if not self.config.incremental_verify or self.config.matcher_backend != "incremental":
            return
        for rule in sorted(self.rules.values(), key=lambda item: item.rule_id):
            self.occurrence_index.incremental.assert_equivalent(
                self.graph,
                rule,
                parameters=self.parameters,
                memory=self.memory,
                time=self.time,
            )

    def _refresh_occurrences(
        self,
        *,
        delta: GraphDelta | None = None,
        state_changed: bool = False,
        force: bool = False,
    ) -> OccurrenceDelta:
        result = self.occurrence_index.refresh(
            graph=self.graph,
            boundary=self.boundary,
            rules=self.rules,
            parameters=self.parameters,
            memory=self.memory,
            time=self.time,
            delta=delta,
            state_changed=state_changed,
            force=force,
        )
        self._indexed_augmented_hash = self._augmented_index_hash()
        self._verify_incremental()
        return result

    def _ensure_occurrences(self) -> None:
        signature = self._augmented_index_hash()
        if self._indexed_augmented_hash != signature:
            self._refresh_occurrences(force=True)

    def _fresh_match(self, match: Match) -> Match:
        """Stamp an unchanged cached structural match for the current graph epoch.

        Match identity is defined by the rule/entity mapping, not the epoch. The
        incremental cache deliberately leaves untouched matches unstamped so a
        local edit does not mutate every cached occurrence. Atomic rewrite
        validation, however, requires the selected occurrence to attest to the
        current epoch.
        """
        if match.graph_epoch == self.graph.epoch:
            return match
        return Match.create(
            rule_id=match.rule_id,
            vertex_map=match.vertex_map,
            edge_map=match.edge_map,
            bindings=match.bindings,
            graph_epoch=self.graph.epoch,
        )

    def enabled_occurrences(self) -> list[EnabledOccurrence]:
        self._ensure_occurrences()
        if self.scheduler_kind is SchedulerKind.THINNING:
            hazards = self.occurrence_index.hazards_at(
                graph=self.graph,
                parameters=self.parameters,
                memory=self.memory,
                time=self.time,
            )
            items = [
                EnabledOccurrence(
                    self.occurrence_index.occurrences[key].rule,
                    self._fresh_match(self.occurrence_index.occurrences[key].match),
                    hazard,
                )
                for key, hazard in hazards.items()
                if hazard > 0.0
            ]
        else:
            items = [
                EnabledOccurrence(item.rule, self._fresh_match(item.match), item.hazard)
                for item in self.occurrence_index.all()
                if item.hazard > 0.0
            ]
        return sorted(items, key=lambda item: (item.rule.rule_id, item.match.match_id))

    def total_activity(self) -> float:
        self._ensure_occurrences()
        if self.scheduler_kind is SchedulerKind.THINNING:
            return math.fsum(
                self.occurrence_index.hazards_at(
                    graph=self.graph,
                    parameters=self.parameters,
                    memory=self.memory,
                    time=self.time,
                ).values()
            )
        return self.occurrence_index.total_activity

    # ------------------------------------------------------------------
    # Deterministic event ordering
    # ------------------------------------------------------------------

    def _next_deterministic_kind(self) -> tuple[str, Any] | None:
        candidates: list[tuple[float, int, Any, str, Any]] = []
        if self.external_queue:
            event = self.external_queue[0]
            candidates.append(
                (
                    event.simulation_time,
                    0,
                    (event.source_namespace, event.source_sequence),
                    "external",
                    event,
                )
            )
        if self.adaptation_queue:
            update = self.adaptation_queue[0]
            candidates.append(
                (update.simulation_time, 1, update.source_sequence, "adaptation", update)
            )
        if self.meta_queue:
            event = self.meta_queue[0]
            candidates.append(
                (event.simulation_time, 2, event.source_sequence, "meta", event)
            )
        if not candidates:
            return None
        _, _, _, kind, item = min(candidates)
        return kind, item

    @staticmethod
    def _discard(draws: list[RandomDraw]) -> list[RandomDraw]:
        return [
            RandomDraw(draw.domain, draw.purpose, draw.raw_uint64, draw.uniform, True)
            for draw in draws
        ]

    # ------------------------------------------------------------------
    # Direct SSA
    # ------------------------------------------------------------------

    def _plan_direct(self) -> PendingInternalEvent | None:
        if self.pending_internal is not None:
            return self.pending_internal
        self._ensure_occurrences()
        total = self.occurrence_index.total_activity
        if total == 0.0:
            return None
        if not math.isfinite(total) or total > self.config.max_total_activity:
            raise ResourceLimitError(f"Total activity {total!r} exceeds configured limit")
        waiting = self.random.draw("waiting_time", "direct_ssa_wait")
        select_rule = self.random.draw("event_selection", "direct_ssa_rule")
        select_match = self.random.draw("event_selection", "direct_ssa_match")
        delta_time = -math.log(waiting.uniform) / total
        chosen = self.occurrence_index.select(select_rule.uniform, select_match.uniform)
        self.pending_internal = PendingInternalEvent(
            absolute_time=self.time + delta_time,
            occurrence=EnabledOccurrence(
                chosen.rule, self._fresh_match(chosen.match), chosen.hazard
            ),
            draws=[waiting, select_rule, select_match],
            planned_at_time=self.time,
            planned_state_hash=self.state_hash,
            total_activity=total,
            scheduler_kind=SchedulerKind.DIRECT_SSA,
            survival_integral_exact=True,
        )
        return self.pending_internal

    # ------------------------------------------------------------------
    # Modified next-reaction
    # ------------------------------------------------------------------

    def _ensure_next_reaction(self) -> None:
        self._ensure_occurrences()
        if not self._next_reaction_initialized:
            self.next_reaction.initialize(
                self.occurrence_index.occurrences,
                now=self.time,
                random=self.random,
            )
            self._next_reaction_initialized = True

    def _plan_next_reaction(self) -> PendingInternalEvent | None:
        self._ensure_next_reaction()
        proposal = self.next_reaction.peek()
        if proposal is None:
            return None
        absolute_time, key = proposal
        occurrence = self.occurrence_index.occurrences.get(key)
        if occurrence is None:
            raise SchedulerError(f"Next-reaction scheduler references missing occurrence {key}")
        return PendingInternalEvent(
            absolute_time=absolute_time,
            occurrence=EnabledOccurrence(
                occurrence.rule, self._fresh_match(occurrence.match), occurrence.hazard
            ),
            draws=[],
            planned_at_time=self.time,
            planned_state_hash=self.state_hash,
            total_activity=self.occurrence_index.total_activity,
            scheduler_kind=SchedulerKind.NEXT_REACTION,
            survival_integral_exact=True,
        )

    # ------------------------------------------------------------------
    # Time-inhomogeneous thinning
    # ------------------------------------------------------------------

    def _thinning_select(
        self, hazards: dict[OccurrenceKey, float], draw: RandomDraw
    ) -> Occurrence:
        positive = [
            (key, value)
            for key, value in sorted(
                hazards.items(), key=lambda pair: (pair[0].rule_id, pair[0].match_id)
            )
            if value > 0.0
        ]
        total = math.fsum(value for _, value in positive)
        if total <= 0.0:
            raise SchedulerError("Cannot select thinning event from zero activity")
        threshold = min(draw.uniform * total, math.nextafter(total, 0.0))
        cumulative = 0.0
        chosen_key = positive[-1][0]
        for key, value in positive:
            cumulative += value
            if threshold < cumulative:
                chosen_key = key
                break
        base = self.occurrence_index.occurrences[chosen_key]
        return Occurrence(chosen_key, base.rule, base.match, hazards[chosen_key])

    def _thinning_survival_between(
        self, start_time: float, end_time: float
    ) -> float | None:
        if end_time <= start_time:
            return 0.0
        exact_total = 0.0
        for occurrence in self.occurrence_index.occurrences.values():
            value = self.occurrence_index.integrated_hazard(
                occurrence,
                graph=self.graph,
                parameters=self.parameters,
                memory=self.memory,
                start_time=start_time,
                end_time=end_time,
            )
            if value is None:
                return None
            exact_total += value
        return exact_total

    def _accumulate_thinning_survival(self, start_time: float, end_time: float) -> None:
        self.thinning_audit.add_survival(
            self._thinning_survival_between(start_time, end_time)
        )

    def _plan_thinning(self, *, search_limit: float | None = None) -> PendingInternalEvent | None:
        if self.pending_internal is not None:
            return self.pending_internal
        self._ensure_occurrences()
        if not self.occurrence_index.occurrences:
            return None

        for _ in range(self.config.max_thinning_windows_per_plan):
            cursor = self.thinning_audit.cursor(self.time)
            deterministic = self._next_deterministic_kind()
            deterministic_time = (
                deterministic[1].simulation_time if deterministic is not None else math.inf
            )
            window_end = min(
                cursor + self.config.thinning_window,
                deterministic_time,
                search_limit if search_limit is not None else math.inf,
                self.config.max_simulation_time,
            )
            if window_end < cursor:
                raise SchedulerError("Thinning window moved backwards")
            if window_end == cursor:
                return None

            bounds: dict[OccurrenceKey, float] = {}
            for key, occurrence in self.occurrence_index.occurrences.items():
                bounds[key] = self.occurrence_index.bound_at(
                    occurrence,
                    graph=self.graph,
                    parameters=self.parameters,
                    memory=self.memory,
                    time=cursor,
                    horizon=window_end,
                )
            bound_total = math.fsum(bounds.values())
            if not math.isfinite(bound_total) or bound_total > self.config.max_total_activity:
                raise ResourceLimitError(
                    f"Thinning bound activity {bound_total!r} exceeds configured limit"
                )

            if bound_total <= 0.0:
                self._accumulate_thinning_survival(cursor, window_end)
                self.thinning_audit.advance_cursor(window_end)
                self.thinning_audit.windows_crossed += 1
                if window_end == deterministic_time or (
                    search_limit is not None and window_end == search_limit
                ):
                    return None
                continue

            wait = self.random.draw("thinning_wait", "dominating_process_wait")
            candidate_time = cursor - math.log(wait.uniform) / bound_total
            if candidate_time >= window_end:
                self.thinning_audit.draws.append(
                    RandomDraw(wait.domain, wait.purpose, wait.raw_uint64, wait.uniform, True)
                )
                self._accumulate_thinning_survival(cursor, window_end)
                self.thinning_audit.advance_cursor(window_end)
                self.thinning_audit.windows_crossed += 1
                if window_end == deterministic_time or (
                    search_limit is not None and window_end == search_limit
                ):
                    return None
                continue

            self._accumulate_thinning_survival(cursor, candidate_time)
            self.thinning_audit.advance_cursor(candidate_time)
            hazards = self.occurrence_index.hazards_at(
                graph=self.graph,
                parameters=self.parameters,
                memory=self.memory,
                time=candidate_time,
            )
            for key, actual in hazards.items():
                bound = bounds[key]
                tolerance = 1e-12 * max(1.0, abs(actual), abs(bound))
                if actual > bound + tolerance:
                    raise HazardBoundError(
                        f"Thinning bound contract violated at t={candidate_time}: "
                        f"{key} actual={actual!r} bound={bound!r}"
                    )
            actual_total = math.fsum(hazards.values())
            accept = self.random.draw("thinning_accept", "candidate_acceptance")
            self.thinning_audit.draws.extend([wait, accept])
            if actual_total <= 0.0 or accept.uniform * bound_total >= actual_total:
                self.thinning_audit.rejected_candidates += 1
                continue

            selection = self.random.draw("thinning_selection", "accepted_occurrence")
            self.thinning_audit.draws.append(selection)
            chosen = self._thinning_select(hazards, selection)
            survival_integral = self.thinning_audit.drain_survival()
            self.pending_internal = PendingInternalEvent(
                absolute_time=candidate_time,
                occurrence=EnabledOccurrence(
                    chosen.rule, self._fresh_match(chosen.match), chosen.hazard
                ),
                draws=self.thinning_audit.drain(),
                planned_at_time=self.last_event_time,
                planned_state_hash=self._state_hash_at(self.last_event_time),
                total_activity=actual_total,
                scheduler_kind=SchedulerKind.THINNING,
                survival_integral_exact=survival_integral is not None,
                survival_integral=survival_integral,
            )
            return self.pending_internal

        raise ResourceLimitError("Maximum thinning windows per plan exceeded")

    def _plan_internal(self, *, search_limit: float | None = None) -> PendingInternalEvent | None:
        if self.scheduler_kind is SchedulerKind.DIRECT_SSA:
            return self._plan_direct()
        if self.scheduler_kind is SchedulerKind.NEXT_REACTION:
            return self._plan_next_reaction()
        return self._plan_thinning(search_limit=search_limit)

    # ------------------------------------------------------------------
    # Core stepping
    # ------------------------------------------------------------------

    def peek_next_event_time(self) -> float | None:
        pending = self._plan_internal()
        times: list[float] = []
        if pending is not None:
            times.append(pending.absolute_time)
        deterministic = self._next_deterministic_kind()
        if deterministic is not None:
            times.append(deterministic[1].simulation_time)
        return min(times) if times else None

    def _exact_survival(self, activity: float, event_time: float) -> float:
        return activity * (event_time - self.last_event_time)

    def _preempt_draws_and_survival(
        self,
        pending: PendingInternalEvent | None,
        deterministic_time: float,
    ) -> tuple[list[RandomDraw], float | None]:
        if self.scheduler_kind is SchedulerKind.DIRECT_SSA:
            draws = self._discard(pending.draws) if pending is not None else []
            activity = pending.total_activity if pending is not None else self.total_activity()
            return draws, self._exact_survival(activity, deterministic_time)
        if self.scheduler_kind is SchedulerKind.NEXT_REACTION:
            self._ensure_next_reaction()
            draws = self.next_reaction.drain_audit_draws()
            return draws, self._exact_survival(
                self.occurrence_index.total_activity, deterministic_time
            )
        # Thinning event generation is exact from dominating bounds. If a
        # previously planned candidate is preempted by a newly inserted
        # deterministic event, its speculative draws are discarded and the
        # survival term is recomputed only to the preemption time.
        if pending is not None:
            draws = self._discard(pending.draws)
            survival = self._thinning_survival_between(
                self.last_event_time, deterministic_time
            )
            self.thinning_audit.reset_after_commit(self.time)
            return draws, survival
        return self.thinning_audit.drain(), self.thinning_audit.drain_survival()

    def step(self) -> StepResult:
        self._validate_limits()
        pending = self._plan_internal()
        deterministic = self._next_deterministic_kind()

        if pending is None and deterministic is None:
            return StepResult(StepStatus.ABSORBED, reason="No enabled or scheduled events")

        if deterministic is not None:
            kind, item = deterministic
            deterministic_time = item.simulation_time
            if pending is None or deterministic_time <= pending.absolute_time:
                draws, survival = self._preempt_draws_and_survival(
                    pending, deterministic_time
                )
                self.pending_internal = None
                if kind == "external":
                    heapq.heappop(self.external_queue)
                    record = self._process_external(item, draws, survival)
                    return StepResult(StepStatus.PROCESSED_EXTERNAL, event=record)
                if kind == "adaptation":
                    heapq.heappop(self.adaptation_queue)
                    record = self._process_scheduled_adaptation(item, draws, survival)
                    return StepResult(StepStatus.FIRED, event=record)
                heapq.heappop(self.meta_queue)
                record = self._process_meta(item, draws, survival)
                return StepResult(StepStatus.FIRED, event=record)

        assert pending is not None
        if self.scheduler_kind is SchedulerKind.NEXT_REACTION:
            key = OccurrenceKey(
                pending.occurrence.rule.rule_id, pending.occurrence.match.match_id
            )
            self.next_reaction.consume(key, pending.absolute_time)
        self.pending_internal = None
        record = self._fire_internal(pending)
        return StepResult(StepStatus.FIRED, event=record)

    def run_events(self, count: int) -> list[EventRecord]:
        if count < 0:
            raise ValueError("count cannot be negative")
        records: list[EventRecord] = []
        for _ in range(count):
            result = self.step()
            if result.event is not None:
                records.append(result.event)
            if result.status is StepStatus.ABSORBED:
                break
        return records

    def run_until_time(self, target_time: float) -> list[EventRecord]:
        if target_time < self.time:
            raise ValueError("target_time cannot be in the past")
        records: list[EventRecord] = []

        if self.scheduler_kind is SchedulerKind.THINNING:
            while self.time < target_time:
                pending = self._plan_internal(search_limit=target_time)
                deterministic = self._next_deterministic_kind()
                deterministic_time = (
                    deterministic[1].simulation_time if deterministic is not None else math.inf
                )
                internal_time = pending.absolute_time if pending is not None else math.inf
                next_time = min(internal_time, deterministic_time)
                if next_time > target_time or math.isinf(next_time):
                    self.time = target_time
                    break
                result = self.step()
                if result.event is not None:
                    records.append(result.event)
                if result.status is StepStatus.ABSORBED:
                    self.time = target_time
                    break
            return records

        while self.time < target_time:
            next_time = self.peek_next_event_time()
            if next_time is None:
                self.time = target_time
                break
            if next_time > target_time:
                # Direct SSA retains its sampled proposal. Next-reaction retains
                # internal clocks; merely advancing the observation clock is safe.
                self.time = target_time
                break
            result = self.step()
            if result.event is not None:
                records.append(result.event)
            if result.status is StepStatus.ABSORBED:
                self.time = target_time
                break
        return records

    def run_until(
        self,
        predicate: Callable[["Runtime"], bool],
        *,
        max_events: int | None = None,
    ) -> list[EventRecord]:
        records: list[EventRecord] = []
        limit = self.config.max_events if max_events is None else max_events
        while not predicate(self):
            if len(records) >= limit:
                raise ResourceLimitError("run_until event limit reached")
            result = self.step()
            if result.event is not None:
                records.append(result.event)
            if result.status is StepStatus.ABSORBED:
                break
        return records

    # ------------------------------------------------------------------
    # Post-commit indexing and adaptive validation
    # ------------------------------------------------------------------

    def _normalize_rewrite_result(self, result: RewriteResult) -> RewriteResult:
        normalized = self.adaptive_registry.normalize(result.parameters)
        result.parameters = normalized
        result.parameter_after = copy.deepcopy(normalized)
        return result

    def _post_commit_refresh(
        self,
        *,
        delta: GraphDelta,
        state_changed: bool,
        boundary_changed: bool = False,
        fired_key: OccurrenceKey | None = None,
        force: bool = False,
    ) -> list[RandomDraw]:
        if self.scheduler_kind is SchedulerKind.THINNING:
            self.thinning_audit.reset_after_commit(self.time)
        occurrence_delta = self._refresh_occurrences(
            delta=delta,
            state_changed=state_changed,
            force=force or boundary_changed,
        )
        if self.scheduler_kind is SchedulerKind.NEXT_REACTION and self._next_reaction_initialized:
            self.next_reaction.sync(
                self.occurrence_index.occurrences,
                now=self.time,
                random=self.random,
                changed=occurrence_delta.touched,
                fired_key=fired_key,
                force_all=state_changed or force or boundary_changed,
            )
            return self.next_reaction.drain_audit_draws()
        return []

    # ------------------------------------------------------------------
    # State-changing event implementations
    # ------------------------------------------------------------------

    def _fire_internal(self, pending: PendingInternalEvent) -> EventRecord:
        occurrence = pending.occurrence
        if any(
            entity_id not in self.graph.vertices
            for entity_id in occurrence.match.vertex_map.values()
        ):
            raise ReplayError("Pending internal event became invalid without a state transition")
        pre_time = self.last_event_time
        pre_hash = self._state_hash_at(pre_time)
        post_time = pending.absolute_time
        if post_time < pre_time:
            raise ReplayError("Pending internal event lies in the past")
        next_index = self.event_index + 1
        event_id = stable_hash(
            {
                "run_id": self.run_id,
                "event_index": next_index,
                "kind": EventKind.INTERNAL_REWRITE.value,
                "rule": occurrence.rule.rule_id,
                "match": occurrence.match.match_id,
            }
        )

        result = self.rewrite_engine.apply(
            graph=self.graph,
            boundary=self.boundary,
            parameters=self.parameters,
            memory=self.memory,
            rule=occurrence.rule,
            match=occurrence.match,
            time=post_time,
            delta_time=post_time - pre_time,
            event_index=next_index,
            event_id=event_id,
        )
        result = self._normalize_rewrite_result(result)
        state_changed = (
            result.parameter_before != result.parameter_after
            or result.memory_before != result.memory_after
        )
        boundary_changed = not result.boundary_delta.is_empty()

        self.graph = result.graph
        self.boundary = result.boundary
        self.parameters = result.parameters
        self.memory = result.memory
        self.time = post_time
        self.last_event_time = post_time
        self.event_index = next_index
        self.output_events.extend(result.outputs)
        self._validate_limits()
        self._record_event_time()

        fired_key = OccurrenceKey(occurrence.rule.rule_id, occurrence.match.match_id)
        extra_draws = self._post_commit_refresh(
            delta=result.graph_delta,
            state_changed=state_changed,
            boundary_changed=boundary_changed,
            fired_key=fired_key if self.scheduler_kind is SchedulerKind.NEXT_REACTION else None,
        )

        if pending.scheduler_kind is SchedulerKind.NEXT_REACTION:
            random_draws = self.next_reaction.drain_audit_draws()
            # _post_commit_refresh already drained; include any threshold draws that
            # existed before commit plus post-event draws captured in extra_draws.
            random_draws = pending.draws + random_draws + extra_draws
        else:
            random_draws = pending.draws + extra_draws

        post_hash = self.state_hash
        cause: dict[str, Any] = {
            "rule_id": occurrence.rule.rule_id,
            "rule_version": occurrence.rule.version,
            "rule_hash": occurrence.rule.hash,
            "match_id": occurrence.match.match_id,
            "vertex_map": occurrence.match.vertex_map,
            "edge_map": occurrence.match.edge_map,
            "hazard": occurrence.hazard,
            "pre_total_activity": pending.total_activity,
            "scheduler": pending.scheduler_kind.value,
            "post_graph_epoch": self.graph.epoch,
        }
        if pending.survival_integral_exact:
            survival = (
                pending.survival_integral
                if pending.survival_integral is not None
                else pending.total_activity * (post_time - pre_time)
            )
            cause["survival_integral"] = survival
            cause["survival_integral_exact"] = True
        else:
            cause["survival_integral_exact"] = False

        record = EventRecord(
            event_id=event_id,
            event_index=next_index,
            kind=EventKind.INTERNAL_REWRITE,
            pre_time=pre_time,
            post_time=post_time,
            delta_time=post_time - pre_time,
            cause=cause,
            random_draws=random_draws,
            graph_delta=result.graph_delta,
            boundary_delta=result.boundary_delta,
            parameter_before=result.parameter_before,
            parameter_after=result.parameter_after,
            memory_before=result.memory_before,
            memory_after=result.memory_after,
            pre_state_hash=pre_hash,
            post_state_hash=post_hash,
            outputs=result.outputs,
        )
        self.event_log.append(record)
        return record

    def _process_external(
        self,
        event: ExternalEvent,
        draws: list[RandomDraw],
        survival_integral: float | None,
    ) -> EventRecord:
        handle = self.boundary.handles[event.handle_id]
        if handle.direction not in {BoundaryDirection.INPUT, BoundaryDirection.BIDIRECTIONAL}:
            raise ValidationError(f"Boundary handle {event.handle_id!r} does not accept input")
        handle.validate_payload(event.payload)
        pre_time = self.last_event_time
        pre_hash = self._state_hash_at(pre_time)
        parameter_before = copy.deepcopy(self.parameters)
        memory_before = copy.deepcopy(self.memory)
        delta = GraphDelta()

        if handle.input_mode is not InputMode.SIGNAL_ONLY:
            if handle.binding is None:
                raise ValidationError(f"Input handle {event.handle_id!r} is unbound")
            before, after = self.graph.set_vertex_attributes(
                handle.binding,
                event.payload,
                replace=handle.input_mode is InputMode.REPLACE_BOUND_VERTEX_ATTRIBUTES,
                increment_epoch=False,
            )
            if before != after:
                delta.updated_vertices_before[handle.binding] = before
                delta.updated_vertices_after[handle.binding] = after
                self.graph.epoch += 1

        self.time = event.simulation_time
        self.last_event_time = self.time
        self.event_index += 1
        self._validate_limits()
        self._record_event_time()
        extra_draws = self._post_commit_refresh(
            delta=delta,
            state_changed=False,
            force=delta.is_empty(),
        )
        event_id = stable_hash(
            {
                "run_id": self.run_id,
                "event_index": self.event_index,
                "kind": EventKind.EXTERNAL_INPUT.value,
                "external_event_id": event.event_id,
            }
        )
        post_hash = self.state_hash
        cause: dict[str, Any] = {
            "external_event_id": event.event_id,
            "source_namespace": event.source_namespace,
            "source_sequence": event.source_sequence,
            "handle_id": event.handle_id,
            "payload": event.payload,
            "bound_vertex": handle.binding,
            "post_graph_epoch": self.graph.epoch,
            "scheduler": self.scheduler_kind.value,
            "survival_integral_exact": survival_integral is not None,
        }
        if survival_integral is not None:
            cause["survival_integral"] = survival_integral
        record = EventRecord(
            event_id=event_id,
            event_index=self.event_index,
            kind=EventKind.EXTERNAL_INPUT,
            pre_time=pre_time,
            post_time=self.time,
            delta_time=self.time - pre_time,
            cause=cause,
            random_draws=draws + extra_draws,
            graph_delta=delta,
            boundary_delta=BoundaryDelta(),
            parameter_before=parameter_before,
            parameter_after=copy.deepcopy(self.parameters),
            memory_before=memory_before,
            memory_after=copy.deepcopy(self.memory),
            pre_state_hash=pre_hash,
            post_state_hash=post_hash,
        )
        self.event_log.append(record)
        return record

    def _process_scheduled_adaptation(
        self,
        update: ScheduledAdaptation,
        draws: list[RandomDraw],
        survival_integral: float | None,
    ) -> EventRecord:
        pre_time = self.last_event_time
        pre_hash = self._state_hash_at(pre_time)
        parameter_before = copy.deepcopy(self.parameters)
        memory_before = copy.deepcopy(self.memory)
        context = {
            "p": self.parameters,
            "parameters": self.parameters,
            "z": self.memory,
            "memory": self.memory,
            "time": update.simulation_time,
            "delta_time": update.simulation_time - pre_time,
            "payload": {},
        }
        evaluated = [
            (assignment.target, evaluate_value(assignment.value, context))
            for assignment in update.assignments
        ]
        next_parameters = copy.deepcopy(self.parameters)
        next_memory = copy.deepcopy(self.memory)
        for target, value in evaluated:
            root, path = target.split(".", 1)
            set_path(next_parameters if root == "parameters" else next_memory, path, value)
        next_parameters = self.adaptive_registry.normalize(next_parameters)

        self.parameters = next_parameters
        self.memory = next_memory
        self.time = update.simulation_time
        self.last_event_time = self.time
        self.event_index += 1
        self._validate_limits()
        self._record_event_time()
        extra_draws = self._post_commit_refresh(
            delta=GraphDelta(),
            state_changed=True,
            force=True,
        )
        event_id = stable_hash(
            {
                "run_id": self.run_id,
                "event_index": self.event_index,
                "kind": EventKind.SCHEDULED_ADAPTATION.value,
                "update_id": update.update_id,
            }
        )
        post_hash = self.state_hash
        cause: dict[str, Any] = {
            "update_id": update.update_id,
            "post_graph_epoch": self.graph.epoch,
            "scheduler": self.scheduler_kind.value,
            "survival_integral_exact": survival_integral is not None,
        }
        if survival_integral is not None:
            cause["survival_integral"] = survival_integral
        record = EventRecord(
            event_id=event_id,
            event_index=self.event_index,
            kind=EventKind.SCHEDULED_ADAPTATION,
            pre_time=pre_time,
            post_time=self.time,
            delta_time=self.time - pre_time,
            cause=cause,
            random_draws=draws + extra_draws,
            graph_delta=GraphDelta(),
            boundary_delta=BoundaryDelta(),
            parameter_before=parameter_before,
            parameter_after=copy.deepcopy(self.parameters),
            memory_before=memory_before,
            memory_after=copy.deepcopy(self.memory),
            pre_state_hash=pre_hash,
            post_state_hash=post_hash,
        )
        self.event_log.append(record)
        return record

    def _process_meta(
        self,
        event: MetaRuleEvent,
        draws: list[RandomDraw],
        survival_integral: float | None,
    ) -> EventRecord:
        pre_time = self.last_event_time
        pre_hash = self._state_hash_at(pre_time)
        parameter_before = copy.deepcopy(self.parameters)
        memory_before = copy.deepcopy(self.memory)
        before_rules = self._rule_state_canonical()
        rule_after: Rule | None = None

        if event.action is MetaRuleAction.INSTANTIATE:
            assert event.template_id is not None
            try:
                template = self.rule_templates[event.template_id]
            except KeyError as exc:
                raise ValidationError(f"Unknown rule template {event.template_id!r}") from exc
            if event.rule_id in self.rules:
                raise ValidationError(f"Rule {event.rule_id!r} already exists")
            instance_count = sum(
                1
                for rule in self.rules.values()
                if rule.meta.get("__osahr_template_id") == template.template_id
            )
            if instance_count >= template.max_instances:
                raise ResourceLimitError(
                    f"Template {template.template_id!r} reached max_instances"
                )
            rule_after = template.instantiate(event.rule_id, event.bindings)
            rule_after = replace(
                rule_after,
                meta={
                    **rule_after.meta,
                    "__osahr_template_id": template.template_id,
                },
            )
            self.rules[event.rule_id] = rule_after
        elif event.action is MetaRuleAction.ENABLE:
            if event.rule_id not in self.rules:
                raise ValidationError(f"Unknown rule {event.rule_id!r}")
            rule_after = replace(self.rules[event.rule_id], enabled=True)
            self.rules[event.rule_id] = rule_after
        elif event.action is MetaRuleAction.DISABLE:
            if event.rule_id not in self.rules:
                raise ValidationError(f"Unknown rule {event.rule_id!r}")
            rule_after = replace(self.rules[event.rule_id], enabled=False)
            self.rules[event.rule_id] = rule_after
        elif event.action is MetaRuleAction.REMOVE:
            if event.rule_id not in self.rules:
                raise ValidationError(f"Unknown rule {event.rule_id!r}")
            self.rules.pop(event.rule_id)
            self.occurrence_index.invalidate_rule(event.rule_id)
        else:  # pragma: no cover
            raise ValidationError(f"Unsupported meta action {event.action}")

        self._validate_scheduler_contract()
        self.time = event.simulation_time
        self.last_event_time = self.time
        self.event_index += 1
        self._validate_limits()
        self._record_event_time()
        extra_draws = self._post_commit_refresh(
            delta=GraphDelta(),
            state_changed=True,
            force=True,
        )
        event_record_id = stable_hash(
            {
                "run_id": self.run_id,
                "event_index": self.event_index,
                "kind": EventKind.META_RULE_UPDATE.value,
                "meta_event_id": event.event_id,
            }
        )
        post_hash = self.state_hash
        cause: dict[str, Any] = {
            "meta_event_id": event.event_id,
            "action": event.action.value,
            "rule_id": event.rule_id,
            "template_id": event.template_id,
            "bindings": dict(event.bindings),
            "rules_before": before_rules,
            "rules_after": self._rule_state_canonical(),
            "rule_after": rule_after,
            "post_graph_epoch": self.graph.epoch,
            "scheduler": self.scheduler_kind.value,
            "survival_integral_exact": survival_integral is not None,
        }
        if survival_integral is not None:
            cause["survival_integral"] = survival_integral
        record = EventRecord(
            event_id=event_record_id,
            event_index=self.event_index,
            kind=EventKind.META_RULE_UPDATE,
            pre_time=pre_time,
            post_time=self.time,
            delta_time=self.time - pre_time,
            cause=cause,
            random_draws=draws + extra_draws,
            graph_delta=GraphDelta(),
            boundary_delta=BoundaryDelta(),
            parameter_before=parameter_before,
            parameter_after=copy.deepcopy(self.parameters),
            memory_before=memory_before,
            memory_after=copy.deepcopy(self.memory),
            pre_state_hash=pre_hash,
            post_state_hash=post_hash,
        )
        self.event_log.append(record)
        return record

    # ------------------------------------------------------------------
    # Persistence and replay
    # ------------------------------------------------------------------

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            graph=self.graph.clone(),
            boundary=self.boundary.clone(),
            rules=copy.deepcopy(self.rules),
            parameters=copy.deepcopy(self.parameters),
            memory=copy.deepcopy(self.memory),
            time=self.time,
            last_event_time=self.last_event_time,
            event_index=self.event_index,
            root_seed=self.root_seed,
            rng_states=self.random.snapshot(),
            external_queue=copy.deepcopy(self.external_queue),
            adaptation_queue=copy.deepcopy(self.adaptation_queue),
            meta_queue=copy.deepcopy(self.meta_queue),
            pending_internal=copy.deepcopy(self.pending_internal),
            output_events=copy.deepcopy(self.output_events),
            run_id=self.run_id,
            scheduler_kind=self.scheduler_kind,
            next_reaction_snapshot=(
                self.next_reaction.snapshot() if self._next_reaction_initialized else None
            ),
            next_reaction_initialized=self._next_reaction_initialized,
            thinning_audit=copy.deepcopy(self.thinning_audit),
        )

    @classmethod
    def from_snapshot(
        cls,
        model: Model,
        snapshot: RuntimeSnapshot,
        *,
        config: RuntimeConfig | None = None,
    ) -> "Runtime":
        if config is None:
            config = RuntimeConfig(scheduler=snapshot.scheduler_kind)
        runtime = cls(model, root_seed=snapshot.root_seed, config=config)
        if runtime.scheduler_kind is not snapshot.scheduler_kind:
            raise ReplayError("Snapshot scheduler differs from requested runtime scheduler")
        runtime.graph = snapshot.graph.clone()
        runtime.boundary = snapshot.boundary.clone()
        runtime.rules = copy.deepcopy(snapshot.rules)
        runtime.parameters = copy.deepcopy(snapshot.parameters)
        runtime.memory = copy.deepcopy(snapshot.memory)
        runtime.time = snapshot.time
        runtime.last_event_time = snapshot.last_event_time
        runtime.event_index = snapshot.event_index
        runtime.random.restore(snapshot.rng_states)
        runtime.external_queue = copy.deepcopy(snapshot.external_queue)
        heapq.heapify(runtime.external_queue)
        runtime.adaptation_queue = copy.deepcopy(snapshot.adaptation_queue)
        heapq.heapify(runtime.adaptation_queue)
        runtime.meta_queue = copy.deepcopy(snapshot.meta_queue)
        heapq.heapify(runtime.meta_queue)
        runtime.pending_internal = copy.deepcopy(snapshot.pending_internal)
        runtime.output_events = copy.deepcopy(snapshot.output_events)
        runtime.run_id = snapshot.run_id
        runtime.event_log = []
        runtime.thinning_audit = copy.deepcopy(snapshot.thinning_audit)
        runtime.occurrence_index.clear()
        runtime._indexed_augmented_hash = None
        runtime._next_reaction_initialized = snapshot.next_reaction_initialized
        if snapshot.next_reaction_snapshot is not None:
            runtime.next_reaction.restore(snapshot.next_reaction_snapshot)
        return runtime

    @classmethod
    def replay_deltas(
        cls,
        model: Model,
        initial_snapshot: RuntimeSnapshot,
        records: Iterable[EventRecord],
        *,
        config: RuntimeConfig | None = None,
    ) -> "Runtime":
        runtime = cls.from_snapshot(model, initial_snapshot, config=config)
        runtime.pending_internal = None
        runtime._next_reaction_initialized = False
        runtime.next_reaction = NextReactionScheduler()
        for record in records:
            if runtime.state_hash != record.pre_state_hash:
                raise ReplayError(
                    f"Pre-state hash mismatch at event {record.event_index}: "
                    f"{runtime.state_hash} != {record.pre_state_hash}"
                )
            if not record.graph_delta.is_empty():
                runtime.graph.apply_delta(record.graph_delta)
            for handle_id, binding in record.boundary_delta.after.items():
                runtime.boundary.handles[handle_id].binding = binding
            for handle_id in record.boundary_delta.deleted_handles:
                runtime.boundary.handles.pop(handle_id, None)

            if record.kind is EventKind.META_RULE_UPDATE:
                action = MetaRuleAction(record.cause["action"])
                rule_id = str(record.cause["rule_id"])
                rule_after = record.cause.get("rule_after")
                if action is MetaRuleAction.REMOVE:
                    runtime.rules.pop(rule_id, None)
                else:
                    if not isinstance(rule_after, Rule):
                        raise ReplayError(
                            "Delta replay of meta-rule events requires in-memory Rule payloads"
                        )
                    runtime.rules[rule_id] = copy.deepcopy(rule_after)

            runtime.parameters = copy.deepcopy(record.parameter_after)
            runtime.memory = copy.deepcopy(record.memory_after)
            runtime.time = record.post_time
            runtime.last_event_time = record.post_time
            runtime.event_index = record.event_index
            runtime.graph.epoch = int(
                record.cause.get("post_graph_epoch", runtime.graph.epoch)
            )
            runtime.output_events.extend(copy.deepcopy(record.outputs))
            if runtime.state_hash != record.post_state_hash:
                raise ReplayError(
                    f"Post-state hash mismatch at event {record.event_index}: "
                    f"{runtime.state_hash} != {record.post_state_hash}"
                )
            runtime.event_log.append(copy.deepcopy(record))
        runtime.occurrence_index.clear()
        runtime._indexed_augmented_hash = None
        return runtime
