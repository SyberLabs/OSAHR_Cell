#!/usr/bin/env python3
"""MTLF (training) is a batch script, not run_until_time."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def fit_ema_alpha(series: list[float]) -> float:
    """One-step MSE grid search. Off the event clock."""
    y = np.asarray(series, dtype=float)
    if len(y) < 3:
        return 0.35
    best_alpha = 0.35
    best_mse = float("inf")
    for alpha in np.linspace(0.05, 0.9, 18):
        pred = y[0]
        err = []
        for value in y[1:]:
            err.append((pred - value) ** 2)
            pred = alpha * value + (1.0 - alpha) * pred
        mse = float(np.mean(err))
        if mse < best_mse:
            best_mse = mse
            best_alpha = float(alpha)
    return best_alpha


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch MTLF refit (not an occurrence type)")
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.series.read_text(encoding="utf-8"))
    alpha = fit_ema_alpha([float(x) for x in raw])
    args.output.write_text(
        json.dumps({"alpha": alpha, "anlf": "anlf.load.ema_v1", "mtlf": "batch"}, indent=2)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
