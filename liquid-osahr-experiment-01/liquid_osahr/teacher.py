"""Synthetic continuous-time 6G link teacher for Liquid-OSAHR Experiment 01.

The teacher is deliberately mechanistic and hidden-state based. It is not
claimed to be a calibrated RF simulator. Its purpose is to create a known,
nontrivial stochastic law with irregular observations and regime shifts so
neural point-process identification can be evaluated against ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal
import numpy as np

MARKS = ("service", "down", "up")
FEATURE_NAMES = (
    "sinr_db",
    "rsrp_dbm",
    "cqi",
    "bler_proxy",
    "load",
    "speed",
    "service_class",
    "robustness_class",
    "prev_service_event_rate",
    "prev_down_count",
    "prev_up_count",
)

Regime = Literal["train", "id", "high_mobility", "high_congestion", "sparse", "shock"]
Profile = Literal["fast", "robust"]


@dataclass(frozen=True)
class TeacherConfig:
    horizon: float = 36.0
    process_dt: float = 0.05
    telemetry_mean_dt: float = 0.42
    telemetry_min_dt: float = 0.10
    telemetry_max_dt: float = 1.10


@dataclass
class LinkTrace:
    trace_id: str
    regime: str
    profile: str
    times: np.ndarray              # (L,)
    features: np.ndarray           # (L,F)
    interval_dt: np.ndarray        # (L,) exposure until next observation/horizon
    event_counts: np.ndarray       # (L,K) counts in each observation interval
    true_avg_rates: np.ndarray     # (L,K) exact teacher integrated rate / interval_dt
    event_times: np.ndarray        # (N,)
    event_marks: np.ndarray        # (N,) integer mark indices
    latent_summary: dict[str, float]


class LinkTeacher:
    """Piecewise-smooth latent wireless process with exact within-grid jump sampling."""

    def __init__(self, config: TeacherConfig | None = None) -> None:
        self.cfg = config or TeacherConfig()

    @staticmethod
    def _ou_step(x: float, mean: float, tau: float, sigma: float, dt: float, rng: np.random.Generator) -> float:
        decay = math.exp(-dt / tau)
        var_scale = math.sqrt(max(0.0, 1.0 - decay * decay))
        return mean + (x - mean) * decay + sigma * var_scale * float(rng.normal())

    def _regime_params(self, regime: Regime, profile: Profile) -> dict[str, float]:
        if profile == "fast":
            p = dict(base_sinr=13.5, load_mean=0.48, speed_mean=0.75,
                     service_scale=7.2, down_scale=1.0, up_scale=1.0,
                     service_class=1.0, robustness_class=0.20)
        else:
            p = dict(base_sinr=11.3, load_mean=0.37, speed_mean=0.68,
                     service_scale=4.7, down_scale=0.42, up_scale=1.35,
                     service_class=0.55, robustness_class=1.00)
        if regime == "high_mobility":
            p["speed_mean"] *= 2.0
            p["down_scale"] *= 1.45
        elif regime == "high_congestion":
            p["load_mean"] = min(0.93, p["load_mean"] + 0.35)
            p["service_scale"] *= 0.86
        elif regime == "shock":
            p["down_scale"] *= 2.3
            p["load_mean"] = min(0.9, p["load_mean"] + 0.2)
        return p

    def _telemetry_steps(self, regime: Regime, rng: np.random.Generator) -> set[int]:
        dt = self.cfg.process_dt
        max_step = int(round(self.cfg.horizon / dt))
        mean = self.cfg.telemetry_mean_dt * (2.15 if regime == "sparse" else 1.0)
        current = 0
        out = {0}
        while current < max_step:
            raw = float(rng.lognormal(mean=math.log(mean) - 0.12, sigma=0.42))
            raw = float(np.clip(raw, self.cfg.telemetry_min_dt, self.cfg.telemetry_max_dt * (2.0 if regime == "sparse" else 1.0)))
            step = max(1, int(round(raw / dt)))
            current = min(max_step, current + step)
            if current < max_step:
                out.add(current)
        return out

    @staticmethod
    def _rates(
        sinr: float,
        load: float,
        speed: float,
        obstruction: float,
        blocked: bool,
        p: dict[str, float],
    ) -> np.ndarray:
        # Unit-payload successful service opportunity intensity. The event does
        # not mutate state; it is a point-process calibration target.
        log_service = (
            math.log(p["service_scale"])
            + 0.115 * (sinr - 9.0)
            - 1.45 * load
            - 1.05 * obstruction
            - (2.6 if blocked else 0.0)
        )
        service = math.exp(float(np.clip(log_service, -4.5, 3.2)))

        if blocked:
            down = 0.0
            log_up = -0.10 + 0.70 * (1.0 - obstruction) + 0.075 * max(sinr - 3.0, -5.0)
            up = p["up_scale"] * math.exp(float(np.clip(log_up, -4.0, 1.2)))
        else:
            risk = 1.75 * obstruction + 0.48 * speed + 0.85 * load + 0.055 * max(5.0 - sinr, 0.0)
            down = p["down_scale"] * math.exp(float(np.clip(-3.0 + risk, -6.0, 0.8)))
            up = 0.0
        return np.asarray([service, down, up], dtype=np.float64)

    def generate(self, seed: int, *, regime: Regime = "train", profile: Profile = "fast", trace_id: str | None = None) -> LinkTrace:
        rng = np.random.default_rng(seed)
        p = self._regime_params(regime, profile)
        dt = self.cfg.process_dt
        n_steps = int(round(self.cfg.horizon / dt))
        tele_steps = self._telemetry_steps(regime, rng)

        shadow = float(rng.normal(0, 1.8))
        load = float(np.clip(rng.normal(p["load_mean"], 0.08), 0.02, 0.98))
        speed = float(max(0.05, rng.normal(p["speed_mean"], 0.18)))
        obstruction = float(np.clip(rng.normal(0.30, 0.16), 0.0, 1.0))
        blocked = False

        obs_times: list[float] = []
        obs_features: list[list[float]] = []
        event_times: list[float] = []
        event_marks: list[int] = []
        # exact exposure integral under the teacher's piecewise-constant rate on
        # each process-grid segment, later accumulated by telemetry interval.
        rate_integrals_by_step = np.zeros((n_steps, len(MARKS)), dtype=np.float64)

        # Cache state observations on irregular grid before advancing each step.
        def observe(t: float) -> None:
            sinr = p["base_sinr"] + shadow - 7.0 * load - 4.5 * obstruction + float(rng.normal(0, 0.75))
            rsrp = -80.0 + 0.58 * shadow - 5.2 * obstruction - 3.0 * load + float(rng.normal(0, 1.1))
            cqi = float(np.clip((sinr + 6.0) / 1.7, 0.0, 15.0))
            bler = float(np.clip(1.0 / (1.0 + math.exp(0.48 * (sinr - 3.0))) + rng.normal(0, 0.025), 0.0, 1.0))
            obs_times.append(t)
            obs_features.append([
                sinr, rsrp, cqi, bler, load, speed,
                p["service_class"], p["robustness_class"],
            ])

        for step in range(n_steps):
            t0 = step * dt
            if step in tele_steps:
                observe(t0)

            # latent physical state at this segment; the event rate is held
            # constant between jumps, while jump-induced blocked state changes
            # trigger immediate rate recomputation inside the segment.
            base_sinr = p["base_sinr"] + shadow - 7.0 * load - 4.5 * obstruction
            remaining = dt
            cursor = t0
            integral = np.zeros(len(MARKS), dtype=np.float64)
            while remaining > 1e-12:
                rates = self._rates(base_sinr, load, speed, obstruction, blocked, p)
                total = float(rates.sum())
                if total <= 0:
                    integral += rates * remaining
                    break
                wait = float(rng.exponential(1.0 / total))
                if wait >= remaining:
                    integral += rates * remaining
                    break
                integral += rates * wait
                cursor += wait
                remaining -= wait
                threshold = float(rng.random()) * total
                mark = int(np.searchsorted(np.cumsum(rates), threshold, side="right"))
                mark = min(mark, len(MARKS) - 1)
                event_times.append(cursor)
                event_marks.append(mark)
                if mark == 1:
                    blocked = True
                elif mark == 2:
                    blocked = False
                # service event leaves latent state unchanged
            rate_integrals_by_step[step] = integral

            # exact-discretized OU-style latent evolution to next process grid.
            shadow = self._ou_step(shadow, 0.0, 3.2, 2.10, dt, rng)
            load = self._ou_step(load, p["load_mean"], 1.8, 0.16, dt, rng)
            load = float(np.clip(load, 0.01, 0.99))
            speed = self._ou_step(speed, p["speed_mean"], 3.5, 0.13, dt, rng)
            speed = float(max(0.03, speed))
            obstruction_mean = 0.29 + 0.13 * min(speed, 2.5)
            obstruction = self._ou_step(obstruction, obstruction_mean, 1.45, 0.17, dt, rng)
            obstruction = float(np.clip(obstruction, 0.0, 1.0))

        times = np.asarray(obs_times, dtype=np.float64)
        features = np.asarray(obs_features, dtype=np.float32)
        boundaries = np.concatenate([times, [self.cfg.horizon]])
        interval_dt = np.diff(boundaries).astype(np.float32)
        if np.any(interval_dt <= 0):
            raise RuntimeError("non-positive telemetry exposure interval")

        event_times_a = np.asarray(event_times, dtype=np.float64)
        event_marks_a = np.asarray(event_marks, dtype=np.int64)
        counts = np.zeros((len(times), len(MARKS)), dtype=np.float32)
        for et, em in zip(event_times_a, event_marks_a):
            idx = int(np.searchsorted(boundaries, et, side="right") - 1)
            if 0 <= idx < len(times):
                counts[idx, em] += 1.0

        true_int = np.zeros_like(counts, dtype=np.float64)
        obs_step_indices = np.rint(times / dt).astype(int)
        end_step_indices = np.concatenate([obs_step_indices[1:], [n_steps]])
        for i, (a, b) in enumerate(zip(obs_step_indices, end_step_indices)):
            true_int[i] = rate_integrals_by_step[a:b].sum(axis=0)
        true_avg = (true_int / interval_dt[:, None]).astype(np.float32)

        # Causal event-history telemetry available at observation i summarizes
        # only the completed interval i-1. This lets the recurrent models know
        # about observed link-state events without exposing future labels.
        lag = np.zeros((len(times), 3), dtype=np.float32)
        if len(times) > 1:
            lag[1:, 0] = counts[:-1, 0] / np.maximum(interval_dt[:-1], 1e-6)
            lag[1:, 1] = counts[:-1, 1]
            lag[1:, 2] = counts[:-1, 2]
        features = np.concatenate([features, lag], axis=1).astype(np.float32)

        return LinkTrace(
            trace_id=trace_id or f"{regime}-{profile}-{seed}",
            regime=regime,
            profile=profile,
            times=times,
            features=features,
            interval_dt=interval_dt,
            event_counts=counts,
            true_avg_rates=true_avg,
            event_times=event_times_a,
            event_marks=event_marks_a,
            latent_summary={
                "mean_service_rate": float(true_avg[:, 0].mean()),
                "mean_down_rate": float(true_avg[:, 1].mean()),
                "mean_up_rate": float(true_avg[:, 2].mean()),
                "events": float(len(event_times_a)),
            },
        )
