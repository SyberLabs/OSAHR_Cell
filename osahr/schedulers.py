"""Exact stochastic scheduling backends.

- Direct SSA: standard exponential waiting-time / weighted-event selection.
- Modified next-reaction: independent unit-rate Poisson internal clocks, updated
  lazily when occurrence hazards change.
- Thinning: helper state for exact time-inhomogeneous hazards given declared
  dominating bounds on finite windows.
"""

from __future__ import annotations

import copy
import heapq
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .errors import HazardBoundError, ResourceLimitError, SchedulerError
from .occurrence import Occurrence, OccurrenceIndex, OccurrenceKey
from .rng import RandomDraw, RandomStreams


class SchedulerKind(str, Enum):
    DIRECT_SSA = "direct_ssa"
    NEXT_REACTION = "next_reaction"
    THINNING = "thinning"


@dataclass(slots=True)
class NextReactionChannel:
    key: OccurrenceKey
    hazard: float
    internal_time: float
    threshold: float
    last_update_time: float
    planned_time: float
    version: int = 0

    def advance_to(self, time: float) -> None:
        if time < self.last_update_time:
            raise SchedulerError("Cannot move a next-reaction clock backwards")
        self.internal_time += self.hazard * (time - self.last_update_time)
        self.last_update_time = time

    def replan(self, now: float) -> None:
        remaining = max(0.0, self.threshold - self.internal_time)
        self.planned_time = math.inf if self.hazard <= 0.0 else now + remaining / self.hazard
        self.version += 1


@dataclass(slots=True)
class NextReactionSnapshot:
    channels: dict[OccurrenceKey, NextReactionChannel]
    heap: list[tuple[float, int, str, str, OccurrenceKey]]
    audit_draws: list[RandomDraw]


class NextReactionScheduler:
    """Sparse modified-next-reaction scheduler for piecewise-constant hazards.

    Occurrence identities are stochastic channel identities. If an occurrence
    disappears, its residual Poisson clock is discarded. If the same structural
    match later reappears after absence, it receives a fresh independent clock.
    """

    def __init__(self) -> None:
        self.channels: dict[OccurrenceKey, NextReactionChannel] = {}
        self._heap: list[tuple[float, int, str, str, OccurrenceKey]] = []
        self._audit_draws: list[RandomDraw] = []

    @staticmethod
    def _exp_increment(draw: RandomDraw) -> float:
        return -math.log(draw.uniform)

    def _new_threshold(self, random: RandomStreams, purpose: str) -> tuple[float, RandomDraw]:
        draw = random.draw("next_reaction_threshold", purpose)
        self._audit_draws.append(draw)
        return self._exp_increment(draw), draw

    def _push(self, channel: NextReactionChannel) -> None:
        heapq.heappush(
            self._heap,
            (
                channel.planned_time,
                channel.version,
                channel.key.rule_id,
                channel.key.match_id,
                channel.key,
            ),
        )

    def initialize(
        self,
        occurrences: Mapping[OccurrenceKey, Occurrence],
        *,
        now: float,
        random: RandomStreams,
    ) -> None:
        self.channels.clear()
        self._heap.clear()
        for key in sorted(occurrences, key=lambda item: (item.rule_id, item.match_id)):
            occurrence = occurrences[key]
            threshold, _ = self._new_threshold(
                random, f"channel_birth:{key.rule_id}:{key.match_id}"
            )
            channel = NextReactionChannel(
                key=key,
                hazard=occurrence.hazard,
                internal_time=0.0,
                threshold=threshold,
                last_update_time=now,
                planned_time=math.inf,
            )
            channel.replan(now)
            self.channels[key] = channel
            self._push(channel)

    def sync(
        self,
        occurrences: Mapping[OccurrenceKey, Occurrence],
        *,
        now: float,
        random: RandomStreams,
        changed: set[OccurrenceKey] | frozenset[OccurrenceKey] | None = None,
        fired_key: OccurrenceKey | None = None,
        force_all: bool = False,
    ) -> None:
        current_keys = set(self.channels)
        next_keys = set(occurrences)

        for key in current_keys - next_keys:
            # Advance only for consistency/audit; the clock then ceases to exist.
            self.channels[key].advance_to(now)
            del self.channels[key]

        new_keys = next_keys - current_keys
        for key in sorted(new_keys, key=lambda item: (item.rule_id, item.match_id)):
            occurrence = occurrences[key]
            threshold, _ = self._new_threshold(
                random, f"channel_birth:{key.rule_id}:{key.match_id}"
            )
            channel = NextReactionChannel(
                key=key,
                hazard=occurrence.hazard,
                internal_time=0.0,
                threshold=threshold,
                last_update_time=now,
                planned_time=math.inf,
            )
            channel.replan(now)
            self.channels[key] = channel
            self._push(channel)

        if force_all or changed is None:
            update_keys = next_keys & current_keys
        else:
            update_keys = set(changed) & next_keys & current_keys
        if fired_key is not None and fired_key in next_keys & current_keys:
            update_keys.add(fired_key)

        for key in sorted(update_keys, key=lambda item: (item.rule_id, item.match_id)):
            channel = self.channels[key]
            channel.advance_to(now)
            if fired_key == key:
                tolerance = 1e-10 * max(1.0, abs(channel.threshold))
                if channel.internal_time + tolerance < channel.threshold:
                    raise SchedulerError(
                        f"Fired next-reaction channel {key} before its internal threshold"
                    )
                channel.internal_time = channel.threshold
                increment, _ = self._new_threshold(
                    random, f"channel_refire:{key.rule_id}:{key.match_id}"
                )
                channel.threshold += increment
            channel.hazard = occurrences[key].hazard
            channel.replan(now)
            self._push(channel)

    def _clean_heap(self) -> None:
        while self._heap:
            planned, version, _, _, key = self._heap[0]
            channel = self.channels.get(key)
            if channel is None or version != channel.version or planned != channel.planned_time:
                heapq.heappop(self._heap)
                continue
            break

    def peek(self) -> tuple[float, OccurrenceKey] | None:
        self._clean_heap()
        if not self._heap or math.isinf(self._heap[0][0]):
            return None
        planned, _, _, _, key = self._heap[0]
        return planned, key

    def consume(self, key: OccurrenceKey, time: float) -> None:
        self._clean_heap()
        if not self._heap:
            raise SchedulerError("No next-reaction event to consume")
        planned, _, _, _, heap_key = heapq.heappop(self._heap)
        if heap_key != key or not math.isclose(planned, time, rel_tol=1e-12, abs_tol=1e-15):
            raise SchedulerError("Consumed next-reaction event does not match scheduler minimum")

    def drain_audit_draws(self) -> list[RandomDraw]:
        draws = self._audit_draws
        self._audit_draws = []
        return draws

    def snapshot(self) -> NextReactionSnapshot:
        return NextReactionSnapshot(
            channels=copy.deepcopy(self.channels),
            heap=copy.deepcopy(self._heap),
            audit_draws=copy.deepcopy(self._audit_draws),
        )

    def restore(self, snapshot: NextReactionSnapshot) -> None:
        self.channels = copy.deepcopy(snapshot.channels)
        self._heap = copy.deepcopy(snapshot.heap)
        heapq.heapify(self._heap)
        self._audit_draws = copy.deepcopy(snapshot.audit_draws)


@dataclass(slots=True)
class ThinningAudit:
    """Audit state accumulated between committed thinning events.

    Candidate rejections and observation-horizon crossings are not committed
    model events, so their random draws and survival integral must survive until
    the next committed event (or deterministic preemption) for replay/audit.
    """

    draws: list[RandomDraw] = field(default_factory=list)
    rejected_candidates: int = 0
    windows_crossed: int = 0
    integrated_activity: float = 0.0
    integral_exact: bool = True
    cursor_time: float | None = None

    def cursor(self, now: float) -> float:
        if self.cursor_time is None:
            self.cursor_time = now
        if self.cursor_time < now:
            # Advancing the public observation clock without a committed event is
            # legitimate only if the planner had already integrated through that
            # horizon. A lagging cursor has no pending stochastic evidence, so it
            # may safely start at the current observation time.
            self.cursor_time = now
        return self.cursor_time

    def advance_cursor(self, time: float) -> None:
        if self.cursor_time is not None and time < self.cursor_time:
            raise SchedulerError("Thinning planner cursor cannot move backwards")
        self.cursor_time = time

    def reset_after_commit(self, time: float) -> None:
        self.draws = []
        self.integrated_activity = 0.0
        self.integral_exact = True
        self.cursor_time = time

    def add_survival(self, value: float | None) -> None:
        if value is None:
            self.integral_exact = False
            return
        if value < 0.0 or not math.isfinite(value):
            raise SchedulerError(f"Invalid thinning survival integral {value!r}")
        self.integrated_activity += value

    def drain_survival(self) -> float | None:
        result = self.integrated_activity if self.integral_exact else None
        self.integrated_activity = 0.0
        self.integral_exact = True
        return result

    def drain(self) -> list[RandomDraw]:
        result = self.draws
        self.draws = []
        return result


def plan_thinning_event(
    audit: ThinningAudit,
    *,
    index: OccurrenceIndex,
    graph: Any,
    parameters: dict[str, Any],
    memory: dict[str, Any],
    now: float,
    thinning_window: float,
    max_windows: int,
    max_total_activity: float,
    max_simulation_time: float,
    random: RandomStreams,
    next_deterministic_time: float,
    search_limit: float | None,
) -> tuple[float, Occurrence, list[RandomDraw], float, bool, float | None] | None:
    """Propose the next thinning event, or None if a horizon is hit first."""

    def accumulate(start: float, end: float) -> None:
        audit.add_survival(
            index.integrated_activity(
                graph=graph,
                parameters=parameters,
                memory=memory,
                start_time=start,
                end_time=end,
            )
        )

    def skip_window(
        cursor: float, window_end: float, discarded: RandomDraw | None = None
    ) -> bool:
        if discarded is not None:
            audit.draws.append(
                RandomDraw(
                    discarded.domain,
                    discarded.purpose,
                    discarded.raw_uint64,
                    discarded.uniform,
                    True,
                )
            )
        accumulate(cursor, window_end)
        audit.advance_cursor(window_end)
        audit.windows_crossed += 1
        return window_end == next_deterministic_time or (
            search_limit is not None and window_end == search_limit
        )

    if not index.occurrences:
        return None

    for _ in range(max_windows):
        cursor = audit.cursor(now)
        window_end = min(
            cursor + thinning_window,
            next_deterministic_time,
            search_limit if search_limit is not None else math.inf,
            max_simulation_time,
        )
        if window_end < cursor:
            raise SchedulerError("Thinning window moved backwards")
        if window_end == cursor:
            return None

        bounds: dict[OccurrenceKey, float] = {
            key: index.bound_at(
                occurrence,
                graph=graph,
                parameters=parameters,
                memory=memory,
                time=cursor,
                horizon=window_end,
            )
            for key, occurrence in index.occurrences.items()
        }
        bound_total = math.fsum(bounds.values())
        if not math.isfinite(bound_total) or bound_total > max_total_activity:
            raise ResourceLimitError(
                f"Thinning bound activity {bound_total!r} exceeds configured limit"
            )

        if bound_total <= 0.0:
            if skip_window(cursor, window_end):
                return None
            continue

        wait = random.draw("thinning_wait", "dominating_process_wait")
        candidate_time = cursor - math.log(wait.uniform) / bound_total
        if candidate_time >= window_end:
            if skip_window(cursor, window_end, discarded=wait):
                return None
            continue

        accumulate(cursor, candidate_time)
        audit.advance_cursor(candidate_time)
        hazards = index.hazards_at(
            graph=graph,
            parameters=parameters,
            memory=memory,
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
        accept = random.draw("thinning_accept", "candidate_acceptance")
        audit.draws.extend([wait, accept])
        if actual_total <= 0.0 or accept.uniform * bound_total >= actual_total:
            audit.rejected_candidates += 1
            continue

        selection = random.draw("thinning_selection", "accepted_occurrence")
        audit.draws.append(selection)
        chosen = index.select_from_hazards(hazards, selection.uniform)
        survival_integral = audit.drain_survival()
        return (
            candidate_time,
            chosen,
            audit.drain(),
            actual_total,
            survival_integral is not None,
            survival_integral,
        )

    raise ResourceLimitError("Maximum thinning windows per plan exceeded")
