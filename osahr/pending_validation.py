"""Independent validation of authoritative runtime and pending scheduler state."""

from __future__ import annotations

import copy
import math
from typing import Any

from .canonical import stable_hash
from .errors import ReplayError
from .matcher import Match
from .pattern import Rule
from .rng import RandomDraw
from .runtime_state import EnabledOccurrence, PendingInternalEvent
from .schedulers import SchedulerKind


def finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def valid_draw(draw: object) -> bool:
    return (
        isinstance(draw, RandomDraw)
        and isinstance(draw.domain, str)
        and isinstance(draw.purpose, str)
        and not isinstance(draw.raw_uint64, bool)
        and isinstance(draw.raw_uint64, int)
        and 0 <= draw.raw_uint64 < 1 << 64
        and isinstance(draw.uniform, float)
        and math.isfinite(draw.uniform)
        and 0.0 < draw.uniform < 1.0
        and draw.uniform == ((draw.raw_uint64 >> 11) + 0.5) / float(1 << 53)
        and isinstance(draw.discarded, bool)
    )


def validate_pending_event(
    runtime: Any,
    pending: object,
    *,
    expected_integrity: str | None = None,
) -> PendingInternalEvent:
    """Re-derive a pending proposal from authoritative state before it is used."""
    if not isinstance(pending, PendingInternalEvent):
        raise ReplayError("Pending internal event has an invalid type")
    if (
        expected_integrity is not None
        and pending.integrity_hash != expected_integrity
    ):
        raise ReplayError("Pending internal event changed after planning")
    try:
        if pending.integrity_hash != pending.calculate_integrity_hash():
            raise ReplayError("Pending internal event integrity check failed")
    except ReplayError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ReplayError("Pending internal event integrity check failed") from exc

    if (
        not isinstance(pending.occurrence, EnabledOccurrence)
        or not isinstance(pending.occurrence.rule, Rule)
        or not isinstance(pending.occurrence.match, Match)
        or not isinstance(pending.draws, list)
        or not all(valid_draw(draw) for draw in pending.draws)
        or not finite_number(pending.absolute_time)
        or pending.absolute_time < runtime.time
        or not finite_number(pending.planned_at_time)
        or pending.planned_at_time < 0.0
        or pending.planned_at_time > runtime.time
        or not finite_number(pending.total_activity)
        or pending.total_activity <= 0.0
        or pending.total_activity > runtime.config.max_total_activity
        or not finite_number(pending.occurrence.hazard)
        or pending.occurrence.hazard <= 0.0
        or pending.occurrence.hazard > pending.total_activity
        or not isinstance(pending.planned_state_hash, str)
        or not pending.planned_state_hash
        or not isinstance(pending.scheduler_kind, SchedulerKind)
        or pending.scheduler_kind is not runtime.scheduler_kind
        or not isinstance(pending.survival_integral_exact, bool)
        or (
            pending.survival_integral is not None
            and (
                not finite_number(pending.survival_integral)
                or pending.survival_integral < 0.0
            )
        )
    ):
        raise ReplayError("Pending internal event state is invalid")

    rule = runtime.rules.get(pending.occurrence.rule.rule_id)
    if (
        rule is None
        or stable_hash(rule.to_canonical()) != rule.hash
        or stable_hash(pending.occurrence.rule.to_canonical())
        != pending.occurrence.rule.hash
        or rule.hash != pending.occurrence.rule.hash
    ):
        raise ReplayError("Pending rule is not authoritative")
    authoritative = runtime.matcher.authoritative_rule_match(
        runtime.graph,
        rule,
        pending.occurrence.match,
        parameters=runtime.parameters,
        memory=runtime.memory,
        time=pending.planned_at_time,
    )
    if authoritative is None:
        raise ReplayError("Pending match is not authoritative")
    if pending.planned_state_hash != runtime._state_hash_at(
        pending.planned_at_time
    ):
        raise ReplayError("Pending proposal state has changed since planning")

    try:
        # Planning already populated this cache.  Rebuild only after restore or
        # rollback cleared it; do not defeat the incremental matcher per event.
        runtime._ensure_occurrences()
    except Exception as exc:
        raise ReplayError("Pending occurrence set is invalid") from exc
    indexed = runtime.occurrence_index.occurrences
    occurrence_key = (rule.rule_id, authoritative.match_id)
    indexed_by_id = {
        (key.rule_id, key.match_id): occurrence
        for key, occurrence in indexed.items()
    }
    if occurrence_key not in indexed_by_id:
        raise ReplayError("Pending occurrence is not enabled")

    if pending.scheduler_kind is SchedulerKind.DIRECT_SSA:
        expected_draws = (
            ("waiting_time", "direct_ssa_wait"),
            ("event_selection", "direct_ssa_rule"),
            ("event_selection", "direct_ssa_match"),
        )
        if (
            len(pending.draws) != 3
            or tuple((draw.domain, draw.purpose) for draw in pending.draws)
            != expected_draws
            or any(draw.discarded for draw in pending.draws)
            or pending.survival_integral_exact is not True
            or pending.survival_integral is not None
        ):
            raise ReplayError("Pending direct-SSA scheduler state is invalid")
        total_activity = runtime.occurrence_index.total_activity
        selected = runtime.occurrence_index.select(
            pending.draws[1].uniform,
            pending.draws[2].uniform,
        )
        expected_time = pending.planned_at_time - math.log(
            pending.draws[0].uniform
        ) / total_activity
        if (
            pending.total_activity != total_activity
            or pending.absolute_time != expected_time
            or occurrence_key != (selected.rule.rule_id, selected.match.match_id)
            or pending.occurrence.hazard != selected.hazard
        ):
            raise ReplayError("Pending direct-SSA proposal provenance is invalid")
    elif pending.scheduler_kind is SchedulerKind.THINNING:
        if pending.survival_integral_exact != (
            pending.survival_integral is not None
        ):
            raise ReplayError("Pending thinning integral state is inconsistent")
        hazards = runtime.occurrence_index.hazards_at(
            graph=runtime.graph,
            parameters=runtime.parameters,
            memory=runtime.memory,
            time=pending.absolute_time,
        )
        total_activity = math.fsum(hazards.values())
        selection_draws = [
            draw
            for draw in pending.draws
            if draw.domain == "thinning_selection"
            and draw.purpose == "accepted_occurrence"
            and not draw.discarded
        ]
        if len(selection_draws) != 1:
            raise ReplayError("Pending thinning selection draw is invalid")
        selected = runtime.occurrence_index.select_from_hazards(
            hazards,
            selection_draws[0].uniform,
        )
        if (
            runtime.thinning_audit.cursor_time != pending.absolute_time
            or pending.total_activity != total_activity
            or occurrence_key != (selected.rule.rule_id, selected.match.match_id)
            or pending.occurrence.hazard != selected.hazard
        ):
            raise ReplayError("Pending thinning proposal provenance is invalid")
        if pending.survival_integral_exact:
            survival = runtime.occurrence_index.integrated_activity(
                graph=runtime.graph,
                parameters=runtime.parameters,
                memory=runtime.memory,
                start_time=runtime.last_event_time,
                end_time=pending.absolute_time,
            )
            if survival is None or survival != pending.survival_integral:
                raise ReplayError("Pending thinning survival integral is invalid")
    else:
        if (
            pending.draws
            or pending.survival_integral_exact is not True
            or pending.survival_integral is not None
            or pending.planned_at_time != runtime.time
            or not runtime._next_reaction_initialized
        ):
            raise ReplayError("Pending next-reaction scheduler state is invalid")
        proposal = runtime.next_reaction.peek()
        if proposal is None:
            raise ReplayError("Pending next-reaction proposal is missing")
        selected_time, selected_key = proposal
        selected = indexed.get(selected_key)
        if (
            selected is None
            or selected_time != pending.absolute_time
            or occurrence_key != (selected_key.rule_id, selected_key.match_id)
            or pending.total_activity != runtime.occurrence_index.total_activity
            or pending.occurrence.hazard != selected.hazard
        ):
            raise ReplayError("Pending next-reaction proposal provenance is invalid")

    return PendingInternalEvent(
        absolute_time=pending.absolute_time,
        occurrence=EnabledOccurrence(
            copy.deepcopy(rule),
            copy.deepcopy(authoritative),
            pending.occurrence.hazard,
        ),
        draws=copy.deepcopy(pending.draws),
        planned_at_time=pending.planned_at_time,
        planned_state_hash=pending.planned_state_hash,
        total_activity=pending.total_activity,
        scheduler_kind=pending.scheduler_kind,
        survival_integral_exact=pending.survival_integral_exact,
        survival_integral=pending.survival_integral,
    )
