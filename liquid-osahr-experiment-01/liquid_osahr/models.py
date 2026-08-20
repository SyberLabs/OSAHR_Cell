"""Neural point-process hazard models for irregular telemetry."""
from __future__ import annotations

from dataclasses import dataclass
import math
import torch
from torch import nn
from torch.nn import functional as F

from .liquid import CfCCell, FullyConnectedLTCCell, count_parameters


@dataclass(frozen=True)
class ModelConfig:
    input_size: int
    marks: int = 3
    hidden_size: int = 32
    backbone_units: int = 64
    backbone_layers: int = 1
    hazard_floor: float = 1e-5


class HazardModel(nn.Module):
    model_name: str = "base"

    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.head = nn.Linear(cfg.hidden_size, cfg.marks)

    def rates_from_hidden(self, h: torch.Tensor) -> torch.Tensor:
        return F.softplus(self.head(h)) + self.cfg.hazard_floor

    def parameter_count(self) -> int:
        return count_parameters(self)


class CfCHazardModel(HazardModel):
    model_name = "cfc"
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__(cfg)
        self.cell = CfCCell(
            cfg.input_size,
            cfg.hidden_size,
            backbone_units=cfg.backbone_units,
            backbone_layers=cfg.backbone_layers,
        )

    def forward(self, x: torch.Tensor, prev_dt: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        B, L, _ = x.shape
        h = torch.zeros(B, self.cfg.hidden_size, device=x.device, dtype=x.dtype)
        outs = []
        for i in range(L):
            proposed = self.cell(x[:, i], h, prev_dt[:, i])
            m = mask[:, i].unsqueeze(-1)
            h = torch.where(m, proposed, h)
            outs.append(self.rates_from_hidden(h))
        return torch.stack(outs, dim=1)


class LTCHazardModel(HazardModel):
    model_name = "ltc"
    def __init__(self, cfg: ModelConfig, *, ode_unfolds: int = 6, seed: int = 0) -> None:
        super().__init__(cfg)
        self.cell = FullyConnectedLTCCell(cfg.input_size, cfg.hidden_size, ode_unfolds=ode_unfolds, seed=seed)

    def forward(self, x: torch.Tensor, prev_dt: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        B, L, _ = x.shape
        h = torch.zeros(B, self.cfg.hidden_size, device=x.device, dtype=x.dtype)
        outs = []
        for i in range(L):
            proposed = self.cell(x[:, i], h, prev_dt[:, i].clamp_min(1e-3))
            m = mask[:, i].unsqueeze(-1)
            h = torch.where(m, proposed, h)
            outs.append(self.rates_from_hidden(h))
        return torch.stack(outs, dim=1)


class GRUHazardModel(HazardModel):
    model_name = "gru_dt"
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__(cfg)
        self.cell = nn.GRUCell(cfg.input_size + 1, cfg.hidden_size)

    def forward(self, x: torch.Tensor, prev_dt: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        B, L, _ = x.shape
        h = torch.zeros(B, self.cfg.hidden_size, device=x.device, dtype=x.dtype)
        outs = []
        for i in range(L):
            inp = torch.cat([x[:, i], torch.log1p(prev_dt[:, i])], dim=-1)
            proposed = self.cell(inp, h)
            h = torch.where(mask[:, i].unsqueeze(-1), proposed, h)
            outs.append(self.rates_from_hidden(h))
        return torch.stack(outs, dim=1)


class LSTMHazardModel(HazardModel):
    model_name = "lstm_dt"
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__(cfg)
        self.cell = nn.LSTMCell(cfg.input_size + 1, cfg.hidden_size)

    def forward(self, x: torch.Tensor, prev_dt: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        B, L, _ = x.shape
        h = torch.zeros(B, self.cfg.hidden_size, device=x.device, dtype=x.dtype)
        c = torch.zeros_like(h)
        outs = []
        for i in range(L):
            inp = torch.cat([x[:, i], torch.log1p(prev_dt[:, i])], dim=-1)
            hp, cp = self.cell(inp, (h, c))
            m = mask[:, i].unsqueeze(-1)
            h = torch.where(m, hp, h)
            c = torch.where(m, cp, c)
            outs.append(self.rates_from_hidden(h))
        return torch.stack(outs, dim=1)


class MLPHazardModel(HazardModel):
    """Memoryless baseline given current telemetry and elapsed time."""
    model_name = "mlp_dt"
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__(cfg)
        self.encoder = nn.Sequential(
            nn.Linear(cfg.input_size + 1, cfg.hidden_size),
            nn.Tanh(),
            nn.Linear(cfg.hidden_size, cfg.hidden_size),
            nn.Tanh(),
        )

    def forward(self, x: torch.Tensor, prev_dt: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        inp = torch.cat([x, torch.log1p(prev_dt)], dim=-1)
        h = self.encoder(inp)
        return self.rates_from_hidden(h)


class ConstantHazardModel:
    """Analytic homogeneous-Poisson baseline fit from event count / exposure."""
    model_name = "constant"
    def __init__(self, rates: torch.Tensor):
        self.rates = rates.detach().clone().float()
    @classmethod
    def fit(cls, traces) -> "ConstantHazardModel":
        total_counts = sum((torch.from_numpy(t.event_counts).sum(dim=0) for t in traces), torch.zeros(3))
        exposure = sum(float(t.interval_dt.sum()) for t in traces)
        rates = (total_counts + 1e-6) / max(exposure, 1e-9)
        return cls(rates)
    def parameter_count(self) -> int:
        return int(self.rates.numel())
    def predict_trace(self, length: int) -> torch.Tensor:
        return self.rates.unsqueeze(0).expand(length, -1)


def build_model(name: str, cfg: ModelConfig, seed: int = 0):
    torch.manual_seed(seed)
    if name == "cfc": return CfCHazardModel(cfg)
    if name == "ltc": return LTCHazardModel(cfg, seed=seed)
    if name == "gru_dt": return GRUHazardModel(cfg)
    if name == "lstm_dt": return LSTMHazardModel(cfg)
    if name == "mlp_dt": return MLPHazardModel(cfg)
    raise ValueError(name)
