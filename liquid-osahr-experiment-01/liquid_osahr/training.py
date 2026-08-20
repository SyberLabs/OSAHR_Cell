"""Training loop for marked temporal point-process hazards."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import copy
import json
import math
import time
import numpy as np
import torch
from torch import nn

from .data import make_loader, Normalizer
from .models import ModelConfig, build_model


@dataclass(frozen=True)
class TrainConfig:
    epochs: int = 45
    batch_size: int = 12
    learning_rate: float = 2e-3
    weight_decay: float = 1e-5
    grad_clip: float = 5.0
    patience: int = 9
    min_delta: float = 1e-4
    seed: int = 1407
    device: str = "cpu"


@dataclass
class TrainResult:
    model_name: str
    best_epoch: int
    best_val_nll_interval: float
    train_seconds: float
    parameter_count: int
    history: list[dict[str, float]]
    checkpoint: str | None = None


def poisson_process_nll(rates, counts, interval_dt, mask, *, reduction="mean"):
    """Piecewise-constant marked Poisson-process NLL.

    For observation interval i and mark k:
        NLL_ik = lambda_ik * Delta_i - n_ik log(lambda_ik)
    ignoring the log(n!) constant because event times/marks, rather than only
    interval counts, are the intended point-process object. With constant
    intensity within each interval this is also the event-time likelihood up
    to terms independent of the model.
    """
    rates = rates.clamp_min(1e-8)
    term = rates * interval_dt - counts * torch.log(rates)
    term = term.sum(dim=-1)
    active = term[mask]
    if reduction == "sum": return active.sum()
    if reduction == "none": return active
    return active.mean()


@torch.no_grad()
def evaluate_nll(model, traces, normalizer: Normalizer, *, batch_size: int = 16, device: str = "cpu") -> float:
    model.eval()
    loader = make_loader(traces, normalizer, batch_size=batch_size, shuffle=False, seed=0)
    total = 0.0
    intervals = 0
    for batch in loader:
        x = batch["x"].to(device)
        prev_dt = batch["prev_dt"].to(device)
        mask = batch["mask"].to(device)
        rates = model(x, prev_dt, mask)
        loss = poisson_process_nll(rates, batch["counts"].to(device), batch["interval_dt"].to(device), mask, reduction="sum")
        total += float(loss)
        intervals += int(mask.sum())
    return total / max(intervals, 1)


def train_model(
    name: str,
    model_cfg: ModelConfig,
    train_traces,
    val_traces,
    normalizer: Normalizer,
    cfg: TrainConfig,
    *,
    checkpoint_path: Path | None = None,
):
    torch.manual_seed(cfg.seed)
    np.random.seed(cfg.seed)
    model = build_model(name, model_cfg, seed=cfg.seed).to(cfg.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.learning_rate, weight_decay=cfg.weight_decay)
    train_loader = make_loader(train_traces, normalizer, batch_size=cfg.batch_size, shuffle=True, seed=cfg.seed)
    best_state = copy.deepcopy(model.state_dict())
    best_val = math.inf
    best_epoch = 0
    patience_left = cfg.patience
    history = []
    start = time.perf_counter()
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        total = 0.0
        intervals = 0
        for batch in train_loader:
            optimizer.zero_grad(set_to_none=True)
            x = batch["x"].to(cfg.device)
            prev_dt = batch["prev_dt"].to(cfg.device)
            mask = batch["mask"].to(cfg.device)
            rates = model(x, prev_dt, mask)
            loss = poisson_process_nll(
                rates,
                batch["counts"].to(cfg.device),
                batch["interval_dt"].to(cfg.device),
                mask,
                reduction="mean",
            )
            if not torch.isfinite(loss):
                raise RuntimeError(f"non-finite training loss for {name}")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
            optimizer.step()
            total += float(loss.detach()) * int(mask.sum())
            intervals += int(mask.sum())
        train_nll = total / max(intervals, 1)
        val_nll = evaluate_nll(model, val_traces, normalizer, batch_size=cfg.batch_size, device=cfg.device)
        history.append({"epoch": epoch, "train_nll_interval": train_nll, "val_nll_interval": val_nll})
        if val_nll < best_val - cfg.min_delta:
            best_val = val_nll
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            patience_left = cfg.patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    elapsed = time.perf_counter() - start
    model.load_state_dict(best_state)
    if checkpoint_path is not None:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "model_name": name,
            "model_config": asdict(model_cfg),
            "train_config": asdict(cfg),
            "state_dict": best_state,
            "best_epoch": best_epoch,
            "best_val_nll_interval": best_val,
            "normalizer": normalizer.to_json(),
        }, checkpoint_path)
    return model, TrainResult(
        model_name=name,
        best_epoch=best_epoch,
        best_val_nll_interval=best_val,
        train_seconds=elapsed,
        parameter_count=sum(p.numel() for p in model.parameters() if p.requires_grad),
        history=history,
        checkpoint=str(checkpoint_path) if checkpoint_path else None,
    )
