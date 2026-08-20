"""Held-out point-process diagnostics for Liquid-OSAHR."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import numpy as np
import torch
from scipy import stats

from .teacher import MARKS
from .training import poisson_process_nll


@dataclass
class RegimeMetrics:
    model: str
    regime: str
    n_traces: int
    intervals: int
    events: int
    nll_per_interval: float
    nll_per_event: float
    rate_mae: float
    rate_rmse: float
    rate_spearman: float
    count_ratio: float
    mark_count_ratios: dict[str, float]
    time_rescaling_ks: dict[str, float]
    time_rescaling_p: dict[str, float]


def _predict_trace_neural(model, trace, normalizer, device="cpu") -> np.ndarray:
    x = torch.from_numpy(normalizer.transform(trace.features)).unsqueeze(0).to(device)
    prev = np.zeros((len(trace.times), 1), dtype=np.float32)
    if len(trace.times) > 1:
        prev[1:, 0] = np.diff(trace.times).astype(np.float32)
    dt = torch.from_numpy(prev).unsqueeze(0).to(device)
    mask = torch.ones((1, len(trace.times)), dtype=torch.bool, device=device)
    model.eval()
    with torch.no_grad():
        rates = model(x, dt, mask)[0].cpu().numpy()
    return rates


def predict_trace(model_name, model, trace, normalizer, device="cpu") -> np.ndarray:
    if model_name == "constant":
        return model.predict_trace(len(trace.times)).cpu().numpy()
    return _predict_trace_neural(model, trace, normalizer, device)


def _compensator_increments(trace, rates: np.ndarray, mark: int) -> list[float]:
    """Cumulative predicted hazard increments between successive mark events.

    Predicted rates are constant on telemetry intervals. We exactly integrate
    that piecewise-constant model between teacher event times.
    """
    boundaries = np.concatenate([trace.times, [trace.times[-1] + trace.interval_dt[-1]]])
    event_times = trace.event_times[trace.event_marks == mark]
    if len(event_times) < 2:
        return []
    out = []
    previous = 0.0
    for et in event_times:
        if et <= previous + 1e-12:
            continue
        a = previous
        b = float(et)
        integral = 0.0
        i = max(0, int(np.searchsorted(boundaries, a, side="right") - 1))
        while a < b - 1e-12 and i < len(rates):
            seg_end = min(b, float(boundaries[i+1]))
            integral += float(rates[i, mark]) * max(0.0, seg_end - a)
            a = seg_end
            i += 1
        if previous > 0.0:  # omit first-event initialization effect per trace
            out.append(integral)
        previous = b
    return out


def evaluate_model(model_name, model, traces, normalizer, *, regime: str, device="cpu") -> RegimeMetrics:
    nll = 0.0
    intervals = 0
    events = 0
    true_all = []
    pred_all = []
    total_pred_counts = np.zeros(len(MARKS), dtype=np.float64)
    total_obs_counts = np.zeros(len(MARKS), dtype=np.float64)
    rescaled: dict[int, list[float]] = {k: [] for k in range(len(MARKS))}
    for trace in traces:
        pred = predict_trace(model_name, model, trace, normalizer, device)
        counts = trace.event_counts.astype(np.float64)
        exposure = trace.interval_dt[:, None].astype(np.float64)
        nll += float((pred * exposure - counts * np.log(np.clip(pred, 1e-8, None))).sum())
        intervals += len(trace.times)
        events += int(counts.sum())
        true_all.append(trace.true_avg_rates)
        pred_all.append(pred)
        total_pred_counts += (pred * exposure).sum(axis=0)
        total_obs_counts += counts.sum(axis=0)
        for k in range(len(MARKS)):
            rescaled[k].extend(_compensator_increments(trace, pred, k))
    y = np.concatenate(true_all, axis=0).reshape(-1)
    p = np.concatenate(pred_all, axis=0).reshape(-1)
    mae = float(np.mean(np.abs(p-y)))
    rmse = float(np.sqrt(np.mean((p-y)**2)))
    rho = float(stats.spearmanr(y, p).statistic)
    mark_ratios = {MARKS[k]: float(total_pred_counts[k] / max(total_obs_counts[k], 1e-9)) for k in range(len(MARKS))}
    ks = {}
    kp = {}
    for k, name in enumerate(MARKS):
        vals = np.asarray(rescaled[k], dtype=np.float64)
        if len(vals) >= 8:
            uniforms = 1.0 - np.exp(-vals)
            test = stats.kstest(uniforms, "uniform")
            ks[name] = float(test.statistic)
            kp[name] = float(test.pvalue)
        else:
            ks[name] = math.nan
            kp[name] = math.nan
    return RegimeMetrics(
        model=model_name,
        regime=regime,
        n_traces=len(traces),
        intervals=intervals,
        events=events,
        nll_per_interval=nll/max(intervals,1),
        nll_per_event=nll/max(events,1),
        rate_mae=mae,
        rate_rmse=rmse,
        rate_spearman=rho,
        count_ratio=float(total_pred_counts.sum()/max(total_obs_counts.sum(),1e-9)),
        mark_count_ratios=mark_ratios,
        time_rescaling_ks=ks,
        time_rescaling_p=kp,
    )
