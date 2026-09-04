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
from typing import Any, Callable, Iterable

from .adaptive import AdaptiveRegistry
from .boundary import (
    BoundaryDirection,
    BoundaryState,
    ExternalEvent,
    OutputEvent,
)
from .canonical import stable_hash, validate_state_value
from .commit import (
    fire_internal,
    process_external,
    process_meta,
    process_scheduled_adaptation,
)
from .errors import ReplayError, ResourceLimitError, SchedulerError, ValidationError
from .events import EventKind, EventRecord, StepResult, StepStatus
from .graph import GraphDelta, Hypergraph
from .matcher import Match, Matcher
from .meta import MetaRuleAction, MetaRuleEvent
from .model import Model, RuntimeConfig
from .observables import Observable
from .occurrence import Occurrence, OccurrenceDelta, OccurrenceIndex, OccurrenceKey
from .pattern import Rule, StateAssignment
from .pending_validation import validate_pending_event
from .rewrite import RewriteEngine, RewriteResult
from .rng import RandomDraw, RandomStreams
from .runtime_state import (
    EnabledOccurrence,
    PendingInternalEvent,
    PlanCheckpoint as _PlanCheckpoint,
    RuntimeSnapshot,
    ScheduledAdaptation,
    StepCheckpoint as _StepCheckpoint,
)
from .schedulers import (
    NextReactionScheduler,
    NextReactionSnapshot,
    SchedulerKind,
    ThinningAudit,
    plan_thinning_event,
)


class Runtime:
    RUNTIME_VERSION = "osahr-python-0.2.1"

    def __init__(
        self,
        model: Model,
        *,
        root_seed: int,
        config: RuntimeConfig | None = None,
    ) -> None:
        if (
            isinstance(root_seed, bool)
            or not isinstance(root_seed, int)
            or root_seed < 0
            or root_seed >= 1 << 128
        ):
            raise ValueError("root_seed must be an unsigned 128-bit integer")
        try:
            if stable_hash(model.graph.schema.to_canonical()) != model.graph.schema.hash:
                raise ValidationError("Model schema hash is stale")
            model.graph.validate()
            model.boundary.validate(set(model.graph.vertices))
            for rule in model.rules:
                if stable_hash(rule.to_canonical()) != rule.hash:
                    raise ValidationError(f"Rule {rule.rule_id!r} hash is stale")
            for template in model.rule_templates:
                if stable_hash(template.prototype.to_canonical()) != template.prototype.hash:
                    raise ValidationError(
                        f"Rule template {template.template_id!r} prototype hash is stale"
                    )
            validate_state_value(model.parameters)
            validate_state_value(model.memory)
            if stable_hash(model.to_canonical()) != model.hash:
                raise ValidationError("Model hash is stale")
        except (TypeError, ValueError) as exc:
            raise ValidationError("Model authoritative state is not canonical") from exc
        self.model_hash = model.hash
        self.graph = model.graph.clone()
        self.boundary = model.boundary.clone()
        owned_rules = copy.deepcopy(model.rules)
        owned_templates = copy.deepcopy(model.rule_templates)
        self.rules = {rule.rule_id: rule for rule in owned_rules}
        self.rule_templates = {
            template.template_id: template for template in owned_templates
        }
        self._rule_template_hashes = {
            template_id: stable_hash(template.to_canonical())
            for template_id, template in self.rule_templates.items()
        }
        self.parameters = copy.deepcopy(model.parameters)
        self.memory = copy.deepcopy(model.memory)
        self.adaptive_registry = AdaptiveRegistry(copy.deepcopy(model.adaptive_parameters))
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
        self._pending_integrity: str | None = None

        self.next_reaction = NextReactionScheduler()
        self._next_reaction_initialized = False
        self.thinning_audit = ThinningAudit()

        self.event_log: list[EventRecord] = []
        self.output_events: list[OutputEvent] = []
        self.observables: dict[str, Observable] = {}
        self._recent_event_times: deque[float] = deque()
        self._indexed_augmented_hash: str | None = None
        self._continuation_allowed = True
        self._identity_version = 2

        self.run_id = stable_hash(
            {
                "model_hash": self.model_hash,
                "initial_graph": self.graph.state_hash,
                "root_seed": root_seed,
                "runtime": self.RUNTIME_VERSION,
                "config": self.config.to_canonical(),
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
        result: list[tuple[str, str]] = []
        for rule_id in sorted(self.rules):
            rule = self.rules[rule_id]
            if rule_id != rule.rule_id or stable_hash(rule.to_canonical()) != rule.hash:
                raise ReplayError("Runtime authoritative rule map is stale")
            result.append((rule_id, rule.hash))
        return result

    def _state_hash_at(self, time_value: float) -> str:
        if (
            stable_hash(self.graph.schema.to_canonical())
            != self.graph.schema.hash
        ):
            raise ReplayError("Runtime schema hash is stale")
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
        self._require_continuation()
        if event.simulation_time < self.time:
            raise ValidationError("Cannot inject an event in the simulation past")
        if event.handle_id not in self.boundary.handles:
            raise ValidationError(f"Unknown boundary handle {event.handle_id!r}")
        handle = self.boundary.handles[event.handle_id]
        if handle.direction not in {
            BoundaryDirection.INPUT,
            BoundaryDirection.BIDIRECTIONAL,
        }:
            raise ValidationError(f"Boundary handle {event.handle_id!r} does not accept input")
        handle.validate_payload(event.payload)
        if any(item.event_id == event.event_id for item in self.external_queue):
            raise ValidationError(f"Duplicate external event ID {event.event_id!r}")
        heapq.heappush(self.external_queue, copy.deepcopy(event))

    def schedule_adaptation(self, update: ScheduledAdaptation) -> None:
        self._require_continuation()
        if update.simulation_time < self.time:
            raise ValidationError("Cannot schedule adaptation in the simulation past")
        if any(item.update_id == update.update_id for item in self.adaptation_queue):
            raise ValidationError(f"Duplicate scheduled adaptation ID {update.update_id!r}")
        heapq.heappush(self.adaptation_queue, copy.deepcopy(update))

    def schedule_meta(self, event: MetaRuleEvent) -> None:
        self._require_continuation()
        if event.simulation_time < self.time:
            raise ValidationError("Cannot schedule meta-rule update in the simulation past")
        if any(item.event_id == event.event_id for item in self.meta_queue):
            raise ValidationError(f"Duplicate meta-rule event ID {event.event_id!r}")
        heapq.heappush(self.meta_queue, copy.deepcopy(event))

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

    def _validate_event_preflight(self, event_time: float) -> None:
        if self.event_index >= self.config.max_events:
            raise ResourceLimitError("Event limit exceeded")
        if not math.isfinite(event_time):
            raise ResourceLimitError("Event time must be finite")
        if event_time < self.time:
            raise ReplayError("Next event lies in the simulation past")
        if event_time > self.config.max_simulation_time:
            raise ResourceLimitError("Simulation-time limit exceeded")

    def _require_continuation(self) -> None:
        if not self._continuation_allowed:
            raise ReplayError(
                "Runtime state is audit-only; restore a native V2 snapshot to continue"
            )

    def _capture_step_checkpoint(self) -> _StepCheckpoint:
        return _StepCheckpoint(
            # Authoritative commit paths are copy-on-write. Retaining the old
            # roots makes rollback O(1) instead of cloning the entire model on
            # every event.
            graph=self.graph,
            boundary=self.boundary,
            rules=self.rules,
            parameters=self.parameters,
            memory=self.memory,
            time=self.time,
            last_event_time=self.last_event_time,
            event_index=self.event_index,
            rng_states=self.random.snapshot(),
            external_queue=self.external_queue,
            adaptation_queue=self.adaptation_queue,
            meta_queue=self.meta_queue,
            pending_internal=self.pending_internal,
            pending_integrity=self._pending_integrity,
            next_reaction_snapshot=(
                self.next_reaction.snapshot() if self._next_reaction_initialized else None
            ),
            next_reaction_initialized=self._next_reaction_initialized,
            thinning_audit=copy.deepcopy(self.thinning_audit),
            event_log_length=len(self.event_log),
            output_events_length=len(self.output_events),
            recent_event_times=tuple(self._recent_event_times),
        )

    def _restore_step_checkpoint(self, checkpoint: _StepCheckpoint) -> None:
        self.graph = checkpoint.graph
        self.boundary = checkpoint.boundary
        self.rules = checkpoint.rules
        self.parameters = checkpoint.parameters
        self.memory = checkpoint.memory
        self.time = checkpoint.time
        self.last_event_time = checkpoint.last_event_time
        self.event_index = checkpoint.event_index
        self.random.restore(checkpoint.rng_states)
        self.external_queue = checkpoint.external_queue
        self.adaptation_queue = checkpoint.adaptation_queue
        self.meta_queue = checkpoint.meta_queue
        self.pending_internal = checkpoint.pending_internal
        self._pending_integrity = checkpoint.pending_integrity
        self.next_reaction = NextReactionScheduler()
        self._next_reaction_initialized = checkpoint.next_reaction_initialized
        if checkpoint.next_reaction_snapshot is not None:
            self.next_reaction.restore(checkpoint.next_reaction_snapshot)
        self.thinning_audit = checkpoint.thinning_audit
        del self.event_log[checkpoint.event_log_length :]
        del self.output_events[checkpoint.output_events_length :]
        self._recent_event_times = deque(checkpoint.recent_event_times)
        # Occurrence data is a derived cache. Rebuilding it from the restored
        # authoritative state avoids retaining any partially refreshed matches.
        self.occurrence_index.clear()
        self._indexed_augmented_hash = None

    def _plan_internal_transactionally(
        self, *, search_limit: float | None = None
    ) -> PendingInternalEvent | None:
        checkpoint = _PlanCheckpoint(
            rng_states=self.random.snapshot(),
            pending_internal=copy.deepcopy(self.pending_internal),
            pending_integrity=self._pending_integrity,
            next_reaction_snapshot=(
                self.next_reaction.snapshot() if self._next_reaction_initialized else None
            ),
            next_reaction_initialized=self._next_reaction_initialized,
            thinning_audit=copy.deepcopy(self.thinning_audit),
        )
        try:
            return self._plan_internal(search_limit=search_limit)
        except BaseException:
            self.random.restore(checkpoint.rng_states)
            self.pending_internal = checkpoint.pending_internal
            self._pending_integrity = checkpoint.pending_integrity
            self.next_reaction = NextReactionScheduler()
            self._next_reaction_initialized = checkpoint.next_reaction_initialized
            if checkpoint.next_reaction_snapshot is not None:
                self.next_reaction.restore(checkpoint.next_reaction_snapshot)
            self.thinning_audit = checkpoint.thinning_audit
            self.occurrence_index.clear()
            self._indexed_augmented_hash = None
            raise

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

    def _enabled(self, occurrence: Occurrence, hazard: float | None = None) -> EnabledOccurrence:
        return EnabledOccurrence(
            copy.deepcopy(occurrence.rule),
            self._fresh_match(occurrence.match),
            occurrence.hazard if hazard is None else hazard,
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
                self._enabled(self.occurrence_index.occurrences[key], hazard)
                for key, hazard in hazards.items()
                if hazard > 0.0
            ]
        else:
            items = [
                self._enabled(item)
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
            occurrence=self._enabled(chosen),
            draws=[waiting, select_rule, select_match],
            planned_at_time=self.time,
            planned_state_hash=self.state_hash,
            total_activity=total,
            scheduler_kind=SchedulerKind.DIRECT_SSA,
            survival_integral_exact=True,
        )
        self._pending_integrity = self.pending_internal.integrity_hash
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
            occurrence=self._enabled(occurrence),
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

    def _plan_thinning(self, *, search_limit: float | None = None) -> PendingInternalEvent | None:
        if self.pending_internal is not None:
            return self.pending_internal
        self._ensure_occurrences()
        deterministic = self._next_deterministic_kind()
        planned = plan_thinning_event(
            self.thinning_audit,
            index=self.occurrence_index,
            graph=self.graph,
            parameters=self.parameters,
            memory=self.memory,
            now=self.time,
            thinning_window=self.config.thinning_window,
            max_windows=self.config.max_thinning_windows_per_plan,
            max_total_activity=self.config.max_total_activity,
            max_simulation_time=self.config.max_simulation_time,
            random=self.random,
            next_deterministic_time=(
                deterministic[1].simulation_time if deterministic is not None else math.inf
            ),
            search_limit=search_limit,
        )
        if planned is None:
            return None
        absolute_time, chosen, draws, activity, exact, survival = planned
        self.pending_internal = PendingInternalEvent(
            absolute_time=absolute_time,
            occurrence=self._enabled(chosen),
            draws=draws,
            planned_at_time=self.last_event_time,
            planned_state_hash=self._state_hash_at(self.last_event_time),
            total_activity=activity,
            scheduler_kind=SchedulerKind.THINNING,
            survival_integral_exact=exact,
            survival_integral=survival,
        )
        self._pending_integrity = self.pending_internal.integrity_hash
        return self.pending_internal

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
        self._require_continuation()
        pending = self._plan_internal_transactionally()
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
            survival = self.occurrence_index.integrated_activity(
                graph=self.graph,
                parameters=self.parameters,
                memory=self.memory,
                start_time=self.last_event_time,
                end_time=deterministic_time,
            )
            self.thinning_audit.reset_after_commit(self.time)
            return draws, survival
        return self.thinning_audit.drain(), self.thinning_audit.drain_survival()

    def step(self) -> StepResult:
        self._require_continuation()
        checkpoint = self._capture_step_checkpoint()
        try:
            return self._step_impl()
        except BaseException:
            self._restore_step_checkpoint(checkpoint)
            raise

    def _step_impl(self) -> StepResult:
        self._validate_limits()
        pending = self._plan_internal()
        if pending is not None:
            retained = pending is self.pending_internal
            pending = validate_pending_event(
                self,
                pending,
                expected_integrity=(self._pending_integrity if retained else None),
            )
            if retained:
                self.pending_internal = pending
                self._pending_integrity = pending.integrity_hash
        deterministic = self._next_deterministic_kind()

        if pending is None and deterministic is None:
            return StepResult(StepStatus.ABSORBED, reason="No enabled or scheduled events")

        if deterministic is not None:
            kind, item = deterministic
            deterministic_time = item.simulation_time
            if pending is None or deterministic_time <= pending.absolute_time:
                self._validate_event_preflight(deterministic_time)
                draws, survival = self._preempt_draws_and_survival(
                    pending, deterministic_time
                )
                self.pending_internal = None
                self._pending_integrity = None
                if kind == "external":
                    record = self._process_external(item, draws, survival)
                    heapq.heappop(self.external_queue)
                    return StepResult(StepStatus.PROCESSED_EXTERNAL, event=record)
                if kind == "adaptation":
                    record = self._process_scheduled_adaptation(item, draws, survival)
                    heapq.heappop(self.adaptation_queue)
                    return StepResult(StepStatus.FIRED, event=record)
                record = self._process_meta(item, draws, survival)
                heapq.heappop(self.meta_queue)
                return StepResult(StepStatus.FIRED, event=record)

        assert pending is not None
        self._validate_event_preflight(pending.absolute_time)
        if self.scheduler_kind is SchedulerKind.NEXT_REACTION:
            key = OccurrenceKey(
                pending.occurrence.rule.rule_id, pending.occurrence.match.match_id
            )
            self.next_reaction.consume(key, pending.absolute_time)
        self.pending_internal = None
        self._pending_integrity = None
        record = self._fire_internal(pending)
        return StepResult(StepStatus.FIRED, event=record)

    def run_events(self, count: int) -> list[EventRecord]:
        self._require_continuation()
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
        self._require_continuation()
        if target_time < self.time:
            raise ValueError("target_time cannot be in the past")
        if not math.isfinite(target_time):
            raise ValueError("target_time must be finite")
        if target_time > self.config.max_simulation_time:
            raise ResourceLimitError("Simulation-time limit exceeded")
        records: list[EventRecord] = []
        while self.time < target_time:
            if self.scheduler_kind is SchedulerKind.THINNING:
                pending = self._plan_internal_transactionally(search_limit=target_time)
                deterministic = self._next_deterministic_kind()
                deterministic_time = (
                    deterministic[1].simulation_time if deterministic is not None else math.inf
                )
                internal_time = pending.absolute_time if pending is not None else math.inf
                next_time: float | None = min(internal_time, deterministic_time)
                if math.isinf(next_time):
                    next_time = None
            else:
                next_time = self.peek_next_event_time()
            if next_time is None or next_time > target_time:
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
        self._require_continuation()
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

    def _fire_internal(self, pending: PendingInternalEvent) -> EventRecord:
        return fire_internal(self, pending)

    def _process_external(
        self,
        event: ExternalEvent,
        draws: list[RandomDraw],
        survival_integral: float | None,
    ) -> EventRecord:
        return process_external(self, event, draws, survival_integral)

    def _process_scheduled_adaptation(
        self,
        update: ScheduledAdaptation,
        draws: list[RandomDraw],
        survival_integral: float | None,
    ) -> EventRecord:
        return process_scheduled_adaptation(self, update, draws, survival_integral)

    def _process_meta(
        self,
        event: MetaRuleEvent,
        draws: list[RandomDraw],
        survival_integral: float | None,
    ) -> EventRecord:
        return process_meta(self, event, draws, survival_integral)

    # ------------------------------------------------------------------
    # Persistence and replay
    # ------------------------------------------------------------------

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            model_hash=self.model_hash,
            config=self.config,
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
            recent_event_times=tuple(self._recent_event_times),
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
            continuation_allowed=self._continuation_allowed,
            identity_version=self._identity_version,
        ).seal()

    @classmethod
    def from_snapshot(
        cls,
        model: Model,
        snapshot: RuntimeSnapshot,
        *,
        config: RuntimeConfig | None = None,
    ) -> "Runtime":
        from .snapshot_restore import restore_runtime

        return restore_runtime(cls, model, snapshot, config=config)

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
        runtime._pending_integrity = None
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
            runtime._record_event_time()
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
        runtime._continuation_allowed = False
        return runtime
