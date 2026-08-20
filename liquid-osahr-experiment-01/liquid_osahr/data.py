"""Dataset generation, normalization, serialization, and padded batching."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader

from .teacher import LinkTeacher, LinkTrace, FEATURE_NAMES, MARKS


@dataclass(frozen=True)
class DatasetSpec:
    train_traces: int = 72
    val_traces: int = 16
    test_traces: int = 20
    seed: int = 20260817


@dataclass
class Normalizer:
    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(cls, traces: list[LinkTrace]) -> "Normalizer":
        x = np.concatenate([t.features for t in traces], axis=0).astype(np.float64)
        mean = x.mean(axis=0)
        std = x.std(axis=0)
        std = np.where(std < 1e-6, 1.0, std)
        return cls(mean.astype(np.float32), std.astype(np.float32))

    def transform(self, x: np.ndarray) -> np.ndarray:
        return ((x - self.mean) / self.std).astype(np.float32)

    def to_json(self) -> dict:
        return {"feature_names": list(FEATURE_NAMES), "mean": self.mean.tolist(), "std": self.std.tolist()}


@dataclass
class DatasetBundle:
    train: list[LinkTrace]
    val: list[LinkTrace]
    tests: dict[str, list[LinkTrace]]
    normalizer: Normalizer


def _profiles(n: int) -> list[str]:
    return ["fast" if i % 2 == 0 else "robust" for i in range(n)]


def generate_bundle(teacher: LinkTeacher, spec: DatasetSpec) -> DatasetBundle:
    ss = np.random.SeedSequence(spec.seed)
    total_sets = 2 + 4
    children = ss.spawn(total_sets)

    def gen(n: int, regime: str, child: np.random.SeedSequence) -> list[LinkTrace]:
        rng = np.random.default_rng(child)
        traces: list[LinkTrace] = []
        for i, profile in enumerate(_profiles(n)):
            seed = int(rng.integers(1, 2**31 - 1))
            traces.append(teacher.generate(seed, regime=regime, profile=profile, trace_id=f"{regime}-{i:04d}"))
        return traces

    train = gen(spec.train_traces, "train", children[0])
    val = gen(spec.val_traces, "id", children[1])
    regimes = ["id", "high_mobility", "high_congestion", "sparse"]
    tests = {reg: gen(spec.test_traces, reg, children[2+i]) for i, reg in enumerate(regimes)}
    norm = Normalizer.fit(train)
    return DatasetBundle(train, val, tests, norm)


def save_bundle(bundle: DatasetBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, np.ndarray] = {}
    meta: dict[str, object] = {"normalizer": bundle.normalizer.to_json(), "splits": {}}
    split_map = {"train": bundle.train, "val": bundle.val, **{f"test_{k}": v for k, v in bundle.tests.items()}}
    for split_name, traces in split_map.items():
        meta["splits"][split_name] = []
        for i, t in enumerate(traces):
            prefix = f"{split_name}_{i}"
            payload[f"{prefix}_times"] = t.times
            payload[f"{prefix}_features"] = t.features
            payload[f"{prefix}_interval_dt"] = t.interval_dt
            payload[f"{prefix}_counts"] = t.event_counts
            payload[f"{prefix}_true_rates"] = t.true_avg_rates
            payload[f"{prefix}_event_times"] = t.event_times
            payload[f"{prefix}_event_marks"] = t.event_marks
            meta["splits"][split_name].append({"prefix": prefix, "trace_id": t.trace_id, "regime": t.regime, "profile": t.profile, "latent_summary": t.latent_summary})
    payload["__meta_json__"] = np.asarray(json.dumps(meta))
    np.savez_compressed(path, **payload)


class TraceDataset(Dataset):
    def __init__(self, traces: list[LinkTrace], normalizer: Normalizer):
        self.traces = traces
        self.normalizer = normalizer
    def __len__(self) -> int:
        return len(self.traces)
    def __getitem__(self, idx: int) -> dict[str, torch.Tensor | int]:
        t = self.traces[idx]
        x = self.normalizer.transform(t.features)
        times = t.times.astype(np.float32)
        prev_dt = np.zeros_like(times)
        if len(times) > 1:
            prev_dt[1:] = np.diff(times)
        return {
            "x": torch.from_numpy(x),
            "prev_dt": torch.from_numpy(prev_dt[:, None]),
            "interval_dt": torch.from_numpy(t.interval_dt[:, None]),
            "counts": torch.from_numpy(t.event_counts),
            "true_rates": torch.from_numpy(t.true_avg_rates),
            "index": idx,
        }


def collate_traces(items: list[dict]) -> dict[str, torch.Tensor]:
    B = len(items)
    L = max(int(item["x"].shape[0]) for item in items)
    F = int(items[0]["x"].shape[1])
    K = int(items[0]["counts"].shape[1])
    x = torch.zeros(B, L, F)
    prev_dt = torch.zeros(B, L, 1)
    interval_dt = torch.zeros(B, L, 1)
    counts = torch.zeros(B, L, K)
    true_rates = torch.zeros(B, L, K)
    mask = torch.zeros(B, L, dtype=torch.bool)
    indices = torch.zeros(B, dtype=torch.long)
    for b, item in enumerate(items):
        n = item["x"].shape[0]
        x[b, :n] = item["x"]
        prev_dt[b, :n] = item["prev_dt"]
        interval_dt[b, :n] = item["interval_dt"]
        counts[b, :n] = item["counts"]
        true_rates[b, :n] = item["true_rates"]
        mask[b, :n] = True
        indices[b] = int(item["index"])
    return {"x": x, "prev_dt": prev_dt, "interval_dt": interval_dt, "counts": counts, "true_rates": true_rates, "mask": mask, "indices": indices}


def make_loader(traces: list[LinkTrace], normalizer: Normalizer, *, batch_size: int, shuffle: bool, seed: int) -> DataLoader:
    gen = torch.Generator().manual_seed(seed)
    return DataLoader(TraceDataset(traces, normalizer), batch_size=batch_size, shuffle=shuffle, collate_fn=collate_traces, generator=gen, num_workers=0)


def sparsify_trace(trace: LinkTrace, *, keep_probability: float = 0.45, seed: int = 0, trace_id: str | None = None) -> LinkTrace:
    """Create a paired sparse-observation view of an existing physical trace.

    The underlying event times/marks and retained raw telemetry values are
    unchanged. Observation intervals are merged exactly: event counts are
    summed and teacher intensities are exposure-weighted. The three lagged
    event-history features are recomputed from the merged *previous* interval,
    preserving causality and avoiding a sparse-sampling label leak.
    """
    if not (0.0 < keep_probability <= 1.0):
        raise ValueError("keep_probability must be in (0,1]")
    n=len(trace.times)
    if n < 2 or keep_probability >= 1.0:
        return LinkTrace(
            trace_id=trace_id or f"paired-sparse-{trace.trace_id}", regime="paired_sparse", profile=trace.profile,
            times=trace.times.copy(), features=trace.features.copy(), interval_dt=trace.interval_dt.copy(),
            event_counts=trace.event_counts.copy(), true_avg_rates=trace.true_avg_rates.copy(),
            event_times=trace.event_times.copy(), event_marks=trace.event_marks.copy(), latent_summary=dict(trace.latent_summary),
        )
    rng=np.random.default_rng(seed)
    keep=np.zeros(n,dtype=bool); keep[0]=True
    keep[1:]=rng.random(n-1) < keep_probability
    # Ensure enough observations for a meaningful irregular sequence.
    if keep.sum() < 2:
        keep[min(n-1, max(1,n//2))]=True
    idx=np.flatnonzero(keep)
    new_times=trace.times[idx].copy()
    horizon=float(trace.times[-1] + trace.interval_dt[-1])
    new_boundaries=np.concatenate([new_times,[horizon]])
    new_dt=np.diff(new_boundaries).astype(np.float32)
    counts=np.zeros((len(idx), trace.event_counts.shape[1]),dtype=np.float32)
    integrals=np.zeros_like(counts,dtype=np.float64)
    # Original intervals partition [times[0], horizon]. For each retained start,
    # merge all original intervals whose start is before the next retained time.
    for j,start_idx in enumerate(idx):
        end_idx = idx[j+1] if j+1 < len(idx) else n
        counts[j]=trace.event_counts[start_idx:end_idx].sum(axis=0)
        integrals[j]=(trace.true_avg_rates[start_idx:end_idx].astype(np.float64) * trace.interval_dt[start_idx:end_idx,None].astype(np.float64)).sum(axis=0)
    true_avg=(integrals / new_dt[:,None]).astype(np.float32)
    base=trace.features[idx,:8].copy()
    lag=np.zeros((len(idx),3),dtype=np.float32)
    if len(idx)>1:
        lag[1:,0]=counts[:-1,0]/np.maximum(new_dt[:-1],1e-6)
        lag[1:,1]=counts[:-1,1]
        lag[1:,2]=counts[:-1,2]
    features=np.concatenate([base,lag],axis=1).astype(np.float32)
    return LinkTrace(
        trace_id=trace_id or f"paired-sparse-{trace.trace_id}", regime="paired_sparse", profile=trace.profile,
        times=new_times, features=features, interval_dt=new_dt, event_counts=counts, true_avg_rates=true_avg,
        event_times=trace.event_times.copy(), event_marks=trace.event_marks.copy(),
        latent_summary={**trace.latent_summary,"paired_sparse_keep_probability":float(keep_probability),"observations":float(len(idx))},
    )
