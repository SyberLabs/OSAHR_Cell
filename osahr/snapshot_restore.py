"""Validation and reconstruction of resumable runtime snapshots."""

from __future__ import annotations

import copy
import heapq
import math
from collections import deque
from typing import Any

from .boundary import BoundaryDirection, BoundaryState, ExternalEvent, OutputEvent
from .canonical import stable_hash
from .errors import ReplayError, SchedulerError, ValidationError
from .graph import Hypergraph
from .meta import MetaRuleEvent
from .model import Model, RuntimeConfig
from .pattern import Rule, StateAssignment
from .pending_validation import finite_number, valid_draw, validate_pending_event
from .runtime_state import RuntimeSnapshot, ScheduledAdaptation
from .schedulers import NextReactionSnapshot, SchedulerKind, ThinningAudit


def restore_runtime(
    runtime_type: type[Any],
    model: Model,
    snapshot: RuntimeSnapshot,
    *,
    config: RuntimeConfig | None = None,
) -> Any:
    if not isinstance(snapshot, RuntimeSnapshot):
        raise ReplayError("Checkpoint does not contain a RuntimeSnapshot")
    if getattr(snapshot, "format_version", None) != 2:
        raise ReplayError(
            "Unsupported snapshot format version "
            f"{getattr(snapshot, 'format_version', None)!r}"
        )
    if snapshot.model_hash != model.hash:
        raise ReplayError("Snapshot model hash differs from the requested model")
    if not isinstance(snapshot.config, RuntimeConfig):
        raise ReplayError("Snapshot RuntimeConfig is invalid")
    try:
        snapshot.config.__post_init__()
    except (TypeError, ValueError) as exc:
        raise ReplayError("Snapshot RuntimeConfig is invalid") from exc
    if config is not None and config != snapshot.config:
        raise ReplayError(
            "Snapshot RuntimeConfig differs from the requested RuntimeConfig"
        )
    config = snapshot.config
    if (
        not isinstance(snapshot.scheduler_kind, SchedulerKind)
        or config.scheduler_kind is not snapshot.scheduler_kind
    ):
        raise ReplayError("Snapshot scheduler and RuntimeConfig are inconsistent")

    if (
        not finite_number(snapshot.time)
        or snapshot.time < 0.0
        or not finite_number(snapshot.last_event_time)
        or snapshot.last_event_time < 0.0
        or snapshot.last_event_time > snapshot.time
    ):
        raise ReplayError("Snapshot time state is invalid")
    if (
        isinstance(snapshot.event_index, bool)
        or not isinstance(snapshot.event_index, int)
        or snapshot.event_index < 0
        or snapshot.event_index > config.max_events
    ):
        raise ReplayError("Snapshot event index is invalid")
    if (
        isinstance(snapshot.root_seed, bool)
        or not isinstance(snapshot.root_seed, int)
        or snapshot.root_seed < 0
        or snapshot.root_seed >= 1 << 128
    ):
        raise ReplayError("Snapshot root seed is invalid")
    if not isinstance(snapshot.continuation_allowed, bool):
        raise ReplayError("Snapshot continuation flag is invalid")
    identity_version = getattr(snapshot, "identity_version", None)
    if (
        isinstance(identity_version, bool)
        or not isinstance(identity_version, int)
        or identity_version not in {1, 2}
    ):
        raise ReplayError("Snapshot run identity version is invalid")

    runtime = runtime_type(model, root_seed=snapshot.root_seed, config=config)
    if identity_version == 2 and runtime.run_id != snapshot.run_id:
        raise ReplayError("Snapshot run identity does not match the requested model/config")
    if identity_version == 1 and (
        not isinstance(snapshot.run_id, str)
        or len(snapshot.run_id) != 64
        or any(character not in "0123456789abcdef" for character in snapshot.run_id)
    ):
        raise ReplayError("Legacy snapshot run identity is invalid")
    if not isinstance(snapshot.recent_event_times, tuple):
        raise ReplayError("Snapshot recent event times are invalid")
    recent_event_times = tuple(snapshot.recent_event_times)
    if any(
        not finite_number(value)
        or value < 0.0
        or value > snapshot.last_event_time
        for value in recent_event_times
    ) or any(
        right < left for left, right in zip(recent_event_times, recent_event_times[1:])
    ):
        raise ReplayError("Snapshot recent event times are invalid")
    if (
        len(recent_event_times) > snapshot.event_index
        or len(recent_event_times) > config.max_events_per_time_window
    ):
        raise ReplayError("Snapshot recent event history exceeds configured limits")

    if not isinstance(snapshot.graph, Hypergraph):
        raise ReplayError("Snapshot graph is invalid")
    if snapshot.graph.schema.hash != model.graph.schema.hash:
        raise ReplayError("Snapshot graph schema differs from the requested model")
    if not isinstance(snapshot.boundary, BoundaryState):
        raise ReplayError("Snapshot boundary is invalid")
    if not isinstance(snapshot.rules, dict) or not all(
        isinstance(rule_id, str)
        and isinstance(rule, Rule)
        and rule_id == rule.rule_id
        for rule_id, rule in snapshot.rules.items()
    ):
        raise ReplayError("Snapshot rule map is invalid")
    if not isinstance(snapshot.parameters, dict) or not isinstance(snapshot.memory, dict):
        raise ReplayError("Snapshot adaptive state is invalid")
    try:
        if stable_hash(snapshot.graph.schema.to_canonical()) != snapshot.graph.schema.hash:
            raise ReplayError("Snapshot graph schema hash is invalid")
        snapshot.graph.validate()
        snapshot.boundary.validate(set(snapshot.graph.vertices))
        for handle in snapshot.boundary.handles.values():
            if handle.binding is not None:
                vertex_type = snapshot.graph.vertices[handle.binding].type_id
                if not snapshot.graph.schema.is_vertex_compatible(
                    vertex_type,
                    handle.interface_type,
                ):
                    raise ReplayError(
                        f"Snapshot boundary {handle.handle_id!r} has an incompatible binding"
                    )
        for rule in snapshot.rules.values():
            if stable_hash(rule.to_canonical()) != rule.hash:
                raise ReplayError(f"Snapshot rule {rule.rule_id!r} hash is invalid")
        stable_hash(snapshot.parameters)
        stable_hash(snapshot.memory)
        runtime.adaptive_registry.validate(snapshot.parameters)
    except ReplayError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ReplayError("Snapshot authoritative state is invalid") from exc

    queue_specs = (
        (snapshot.external_queue, ExternalEvent, "external"),
        (snapshot.adaptation_queue, ScheduledAdaptation, "adaptation"),
        (snapshot.meta_queue, MetaRuleEvent, "meta-rule"),
    )
    for queue, expected_type, label in queue_specs:
        if not isinstance(queue, list) or any(
            not isinstance(item, expected_type)
            or not finite_number(item.simulation_time)
            or item.simulation_time < snapshot.time
            for item in queue
        ):
            raise ReplayError(f"Snapshot {label} queue is invalid")
    try:
        for event in snapshot.external_queue:
            handle = snapshot.boundary.handles[event.handle_id]
            if handle.direction not in {
                BoundaryDirection.INPUT,
                BoundaryDirection.BIDIRECTIONAL,
            }:
                raise ReplayError(
                    f"Snapshot input handle {event.handle_id!r} rejects input"
                )
            handle.validate_payload(event.payload)
        for update in snapshot.adaptation_queue:
            if not isinstance(update.assignments, tuple) or not all(
                isinstance(assignment, StateAssignment)
                for assignment in update.assignments
            ):
                raise ReplayError("Snapshot adaptation assignments are invalid")
        for event in snapshot.meta_queue:
            stable_hash(event.bindings)
    except ReplayError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ReplayError("Snapshot queued state is invalid") from exc

    if not isinstance(snapshot.rng_states, dict):
        raise ReplayError("Snapshot random-stream state is invalid")
    for domain, state in snapshot.rng_states.items():
        if (
            not isinstance(domain, str)
            or not isinstance(state, tuple)
            or len(state) != 4
            or not any(state)
            or any(
                isinstance(word, bool)
                or not isinstance(word, int)
                or word < 0
                or word >= 1 << 64
                for word in state
            )
        ):
            raise ReplayError("Snapshot random-stream state is invalid")

    if not isinstance(snapshot.output_events, list) or any(
        not isinstance(event, OutputEvent)
        or not finite_number(event.simulation_time)
        or event.simulation_time < 0.0
        or event.simulation_time > snapshot.time
        or isinstance(event.event_index, bool)
        or not isinstance(event.event_index, int)
        or event.event_index < 0
        or event.event_index > snapshot.event_index
        for event in snapshot.output_events
    ):
        raise ReplayError("Snapshot output events are invalid")
    try:
        for event in snapshot.output_events:
            stable_hash(event.payload)
    except (TypeError, ValueError) as exc:
        raise ReplayError("Snapshot output payload is invalid") from exc

    if snapshot.next_reaction_initialized != (
        snapshot.next_reaction_snapshot is not None
    ) or not isinstance(snapshot.next_reaction_initialized, bool):
        raise ReplayError("Snapshot next-reaction state is inconsistent")
    if (
        snapshot.scheduler_kind is not SchedulerKind.NEXT_REACTION
        and snapshot.next_reaction_initialized
    ):
        raise ReplayError("Snapshot next-reaction state uses the wrong scheduler")
    if snapshot.next_reaction_snapshot is not None:
        if not isinstance(snapshot.next_reaction_snapshot, NextReactionSnapshot):
            raise ReplayError("Snapshot next-reaction state is invalid")
        if not all(
            valid_draw(draw) for draw in snapshot.next_reaction_snapshot.audit_draws
        ):
            raise ReplayError("Snapshot next-reaction audit draws are invalid")
    if not isinstance(snapshot.thinning_audit, ThinningAudit):
        raise ReplayError("Snapshot thinning audit is invalid")
    audit = snapshot.thinning_audit
    if (
        not isinstance(audit.draws, list)
        or not all(valid_draw(draw) for draw in audit.draws)
        or isinstance(audit.rejected_candidates, bool)
        or not isinstance(audit.rejected_candidates, int)
        or audit.rejected_candidates < 0
        or isinstance(audit.windows_crossed, bool)
        or not isinstance(audit.windows_crossed, int)
        or audit.windows_crossed < 0
        or not finite_number(audit.integrated_activity)
        or audit.integrated_activity < 0.0
        or not isinstance(audit.integral_exact, bool)
        or (
            audit.cursor_time is not None
            and (
                not finite_number(audit.cursor_time)
                or audit.cursor_time < snapshot.last_event_time
            )
        )
    ):
        raise ReplayError("Snapshot thinning audit is invalid")

    try:
        if (
            not isinstance(snapshot.integrity_hash, str)
            or snapshot.integrity_hash != snapshot.calculate_integrity_hash()
        ):
            raise ReplayError("Snapshot integrity check failed")
    except ReplayError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ReplayError("Snapshot integrity check failed") from exc

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
    runtime._identity_version = identity_version
    runtime.event_log = []
    runtime.thinning_audit = copy.deepcopy(snapshot.thinning_audit)
    runtime._recent_event_times = deque(recent_event_times)
    runtime._continuation_allowed = snapshot.continuation_allowed
    runtime.occurrence_index.clear()
    runtime._indexed_augmented_hash = None
    runtime._validate_scheduler_contract()
    runtime._validate_limits()

    if runtime.pending_internal is not None:
        runtime.pending_internal = validate_pending_event(
            runtime,
            runtime.pending_internal,
        )
        runtime._pending_integrity = runtime.pending_internal.integrity_hash

    runtime._next_reaction_initialized = snapshot.next_reaction_initialized
    if snapshot.next_reaction_snapshot is not None:
        try:
            runtime.next_reaction.restore(snapshot.next_reaction_snapshot)
        except (TypeError, ValueError, SchedulerError) as exc:
            raise ReplayError("Snapshot next-reaction state is invalid") from exc
        try:
            runtime._refresh_occurrences(force=True)
        except Exception as exc:
            raise ReplayError("Snapshot next-reaction occurrences are invalid") from exc
        occurrences = runtime.occurrence_index.occurrences
        if set(runtime.next_reaction.channels) != set(occurrences):
            raise ReplayError("Snapshot next-reaction channels are incomplete")
        for key, channel in runtime.next_reaction.channels.items():
            occurrence = occurrences[key]
            remaining = max(0.0, channel.threshold - channel.internal_time)
            planned_time = (
                math.inf
                if channel.hazard <= 0.0
                else channel.last_update_time + remaining / channel.hazard
            )
            if (
                channel.hazard != occurrence.hazard
                or channel.last_update_time > runtime.time
                or channel.internal_time > channel.threshold
                or channel.planned_time != planned_time
                or (
                    math.isfinite(channel.planned_time)
                    and channel.planned_time < runtime.time
                )
            ):
                raise ReplayError("Snapshot next-reaction channel is invalid")
    runtime.occurrence_index.clear()
    runtime._indexed_augmented_hash = None
    return runtime
