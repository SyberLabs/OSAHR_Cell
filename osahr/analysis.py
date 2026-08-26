"""Trajectory likelihood, ensembles, and first-passage analysis."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from .events import EventKind, EventRecord
from .model import Model, RuntimeConfig
from .rng import derive_seed
from .runtime import Runtime


@dataclass(frozen=True, slots=True)
class PathLikelihood:
    log_likelihood: float
    log_hazard_sum: float
    integrated_activity: float
    internal_events: int
    conditioned_events: int
    horizon: float


def path_log_likelihood(
    records: Iterable[EventRecord],
    *,
    terminal_time: float | None = None,
    terminal_activity: float | None = None,
) -> PathLikelihood:
    """Log density of an observed internal CTMC path, conditioned on exogenous events.

    Each event record must carry the exact survival integral accumulated since
    the preceding committed event. For piecewise-constant hazards this is
    ``A(X_k) * dt``. External/adaptation/meta event densities are not modeled;
    their timing is conditioned upon, but their intervals still contribute CTMC
    survival probability.
    """

    items = list(records)
    log_hazard = 0.0
    integral = 0.0
    internal = 0
    conditioned = 0
    last_time = 0.0
    for record in items:
        try:
            survival = float(record.cause["survival_integral"])
        except KeyError as exc:
            raise ValueError(
                f"Event {record.event_index} lacks exact survival_integral metadata"
            ) from exc
        if not math.isfinite(survival) or survival < 0.0:
            raise ValueError(f"Invalid survival integral at event {record.event_index}")
        integral += survival
        if record.kind is EventKind.INTERNAL_REWRITE:
            hazard = float(record.cause["hazard"])
            if not math.isfinite(hazard) or hazard <= 0.0:
                raise ValueError(f"Internal event {record.event_index} has nonpositive hazard")
            log_hazard += math.log(hazard)
            internal += 1
        else:
            conditioned += 1
        last_time = record.post_time

    horizon = last_time
    if terminal_time is not None:
        if terminal_time < last_time:
            raise ValueError("terminal_time precedes the final event")
        horizon = terminal_time
        if terminal_time > last_time:
            if terminal_activity is None:
                raise ValueError("terminal_activity is required beyond the final logged event")
            if terminal_activity < 0.0 or not math.isfinite(terminal_activity):
                raise ValueError("terminal_activity must be finite and nonnegative")
            integral += terminal_activity * (terminal_time - last_time)

    return PathLikelihood(
        log_likelihood=log_hazard - integral,
        log_hazard_sum=log_hazard,
        integrated_activity=integral,
        internal_events=internal,
        conditioned_events=conditioned,
        horizon=horizon,
    )


@dataclass(frozen=True, slots=True)
class EnsembleSample:
    replicate: int
    seed: int
    event_count: int
    final_time: float
    state_hash: str
    observables: Mapping[str, Any]
    first_passage_time: float | None = None


@dataclass(slots=True)
class EnsembleResult:
    samples: list[EnsembleSample] = field(default_factory=list)

    def numeric(self, observable_id: str) -> list[float]:
        values: list[float] = []
        for sample in self.samples:
            value = sample.observables[observable_id]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"Observable {observable_id!r} is not numeric")
            values.append(float(value))
        return values

    def summary(self, observable_id: str) -> dict[str, float]:
        values = self.numeric(observable_id)
        if not values:
            raise ValueError("No ensemble samples")
        ordered = sorted(values)

        def quantile(q: float) -> float:
            if len(ordered) == 1:
                return ordered[0]
            position = q * (len(ordered) - 1)
            lo = int(math.floor(position))
            hi = int(math.ceil(position))
            if lo == hi:
                return ordered[lo]
            weight = position - lo
            return ordered[lo] * (1.0 - weight) + ordered[hi] * weight

        return {
            "count": float(len(values)),
            "mean": statistics.fmean(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min": ordered[0],
            "q05": quantile(0.05),
            "median": quantile(0.5),
            "q95": quantile(0.95),
            "max": ordered[-1],
        }


ObservationFn = Callable[[Runtime], Any]
PredicateFn = Callable[[Runtime], bool]


def run_ensemble(
    model: Model,
    *,
    replicates: int,
    root_seed: int,
    target_time: float | None = None,
    event_count: int | None = None,
    config: RuntimeConfig | None = None,
    observations: Mapping[str, ObservationFn] | None = None,
    first_passage: PredicateFn | None = None,
) -> EnsembleResult:
    """Run deterministic-seed-partitioned independent replicates.

    Exactly one of ``target_time`` and ``event_count`` must be supplied.
    The implementation is intentionally serial so numerical/replay behavior is
    independent of worker scheduling. Parallel orchestration can safely happen
    above this function by partitioning replicate IDs.
    """

    if replicates <= 0:
        raise ValueError("replicates must be positive")
    if (target_time is None) == (event_count is None):
        raise ValueError("Specify exactly one of target_time or event_count")
    observations = dict(observations or {})
    samples: list[EnsembleSample] = []

    for replicate in range(replicates):
        seed = derive_seed(root_seed, f"ensemble:{replicate}")
        runtime = Runtime(model, root_seed=seed, config=config)
        passage_time: float | None = 0.0 if first_passage and first_passage(runtime) else None
        if target_time is not None:
            if first_passage is None:
                runtime.run_until_time(target_time)
            else:
                while runtime.time < target_time:
                    next_time = runtime.peek_next_event_time()
                    if next_time is None or next_time > target_time:
                        runtime.run_until_time(target_time)
                        break
                    runtime.step()
                    if passage_time is None and first_passage(runtime):
                        passage_time = runtime.time
        else:
            assert event_count is not None
            for _ in range(event_count):
                result = runtime.step()
                if passage_time is None and first_passage is not None and first_passage(runtime):
                    passage_time = runtime.time
                if result.event is None:
                    break

        values = {name: fn(runtime) for name, fn in observations.items()}
        samples.append(
            EnsembleSample(
                replicate=replicate,
                seed=seed,
                event_count=runtime.event_index,
                final_time=runtime.time,
                state_hash=runtime.state_hash,
                observables=values,
                first_passage_time=passage_time,
            )
        )
    return EnsembleResult(samples)
