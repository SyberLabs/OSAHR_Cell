"""Exact stochastic scheduling backends.

- Direct SSA: standard exponential waiting-time / weighted-event selection.
- Modified next-reaction: independent unit-rate Poisson internal clocks, updated
  lazily when occurrence hazards change.
- Thinning: helper state for exact time-inhomogeneous hazards given declared
  dominating bounds on finite windows.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .errors import SchedulerError
from .occurrence import Occurrence, OccurrenceKey
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
        import copy

        return NextReactionSnapshot(
            channels=copy.deepcopy(self.channels),
            heap=copy.deepcopy(self._heap),
            audit_draws=copy.deepcopy(self._audit_draws),
        )

    def restore(self, snapshot: NextReactionSnapshot) -> None:
        import copy

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
