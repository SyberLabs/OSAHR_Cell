"""NWDAF-like AnLF: inference only. Never a rewrite engine."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from osahr.boundary import BoundaryDirection, BoundaryHandle
from osahr.schema import AttributeSpec, ValueKind

from .protocol import ANLF_LOAD_VERSION, ANLF_OUTAGE_VERSION

# MTLF (training) is off the event clock. See scripts/mtlf_refit.py.


def load_handle(handle_id: str = "edge-load") -> BoundaryHandle:
    return BoundaryHandle(
        handle_id,
        BoundaryDirection.INPUT,
        "EdgeNode",
        payload_schema={"load": AttributeSpec(ValueKind.INT, required=True, minimum=0)},
        allow_payload_extensions=False,
    )


def outage_handle(handle_id: str = "fast-edge-control") -> BoundaryHandle:
    return BoundaryHandle(
        handle_id,
        BoundaryDirection.INPUT,
        "EdgeNode",
        payload_schema={"available": AttributeSpec(ValueKind.BOOL, required=True)},
        allow_payload_extensions=False,
    )


def _ema(series: Sequence[float], alpha: float) -> float:
    if not series:
        raise ValueError("empty KPM series")
    value = float(series[0])
    for item in series[1:]:
        value = alpha * float(item) + (1.0 - alpha) * value
    return value


@dataclass
class LoadLevel:
    """Exponential smoothing of PRB util / EdgeNode.load. Versioned AnLF."""

    version: str = ANLF_LOAD_VERSION
    alpha: float = 0.35
    capacity: int = 6

    def infer(self, series: Sequence[float]) -> dict[str, Any]:
        smoothed = _ema(series, self.alpha)
        load = int(np.clip(round(smoothed), 0, self.capacity))
        return {"load": load}

    def validate(self, handle: BoundaryHandle, payload: dict[str, Any]) -> dict[str, Any]:
        handle.validate_payload(payload)
        return payload


@dataclass
class AbnormalBehavior:
    """Threshold + CUSUM change-point on availability / utilization."""

    version: str = ANLF_OUTAGE_VERSION
    drop_threshold: float = 0.45
    cusum_k: float = 0.15
    cusum_h: float = 1.25

    def infer(self, series: Sequence[float]) -> dict[str, Any]:
        if not series:
            raise ValueError("empty KPM series")
        values = np.asarray(series, dtype=float)
        last = float(values[-1])
        if last <= 0.0:
            return {"available": False}
        if last >= 0.99:
            return {"available": True}
        if last < self.drop_threshold:
            return {"available": False}
        centered = values - np.mean(values[: max(1, len(values) // 2)])
        cusum = 0.0
        for item in centered:
            cusum = max(0.0, cusum - (item + self.cusum_k))
            if cusum > self.cusum_h:
                return {"available": False}
        return {"available": True}

    def validate(self, handle: BoundaryHandle, payload: dict[str, Any]) -> dict[str, Any]:
        handle.validate_payload(payload)
        return payload


def kpm_outage_series(
    *,
    horizon: float,
    dt: float,
    outage_start: float,
    outage_end: float,
) -> list[float]:
    """Synthetic availability KPM at Non-RT cadence (not 10 ms PHY)."""
    times = np.arange(0.0, horizon + 1e-9, dt)
    return [0.0 if outage_start <= t < outage_end else 1.0 for t in times]


def kpm_load_series(values: Sequence[float]) -> list[float]:
    return [float(item) for item in values]
