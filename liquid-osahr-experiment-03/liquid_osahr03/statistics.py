"""Scenario-level bootstrap utilities. Independent unit is a physical scenario."""
from __future__ import annotations

from typing import Mapping

import numpy as np


def bootstrap_mean(values, *, seed: int, n: int = 50_000) -> dict[str, float]:
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan")}
    rng = np.random.default_rng(seed)
    draws = v[rng.integers(0, len(v), size=(n, len(v)))].mean(axis=1)
    return {
        "mean": float(v.mean()),
        "lo": float(np.quantile(draws, 0.025)),
        "hi": float(np.quantile(draws, 0.975)),
        "n": int(v.size),
    }


def stratified_bootstrap_mean(
    by_regime: Mapping[str, np.ndarray],
    *,
    seed: int,
    n: int = 50_000,
) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    pieces = []
    obs: list[float] = []
    for regime in by_regime:
        v = np.asarray(by_regime[regime], dtype=float)
        obs.extend(v.tolist())
        pieces.append(v[rng.integers(0, len(v), size=(n, len(v)))])
    draws = np.concatenate(pieces, axis=1).mean(axis=1)
    return {
        "mean": float(np.mean(obs)),
        "lo": float(np.quantile(draws, 0.025)),
        "hi": float(np.quantile(draws, 0.975)),
        "n": int(len(obs)),
    }


def paired_delta(a, b, *, seed: int, n: int = 50_000) -> dict[str, float]:
    """Bootstrap mean of (a - b). Negative means a is smaller than b."""
    return bootstrap_mean(np.asarray(a, dtype=float) - np.asarray(b, dtype=float), seed=seed, n=n)
