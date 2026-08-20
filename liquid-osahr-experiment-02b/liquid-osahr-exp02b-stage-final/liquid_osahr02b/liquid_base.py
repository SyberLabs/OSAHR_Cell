"""Continuous-time recurrent cells used by Liquid-OSAHR Experiment 02B.

The CfC cell follows the default closed-form architecture documented by the
Neural Circuit Policies project (Lechner/Hasani et al.).  The LTC cell is an
independent fully-connected PyTorch implementation of the semi-implicit liquid
time-constant update described in Hasani et al. and the official ncps code.

These cells are intentionally small and self-contained so the experiment is
reproducible without a network installation of ``ncps``.  See
THIRD_PARTY_NOTICES.md and RESEARCH_NOTES.md for source references.
"""
from __future__ import annotations

import math
import torch
from torch import nn
from torch.nn import functional as F


class LeCunTanh(nn.Module):
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return 1.7159 * torch.tanh(0.666 * x)


class CfCCell(nn.Module):
    """Closed-form continuous-time recurrent cell.

    ``elapsed`` is a batch-wise elapsed-time tensor with shape ``(B, 1)``.
    The default gated interpolation is

        h' = f1 * (1-sigma(a*dt+b)) + f2 * sigma(a*dt+b)

    where all heads are conditioned on the current input and previous state.
    """

    def __init__(
        self,
        input_size: int,
        hidden_size: int,
        *,
        backbone_units: int = 64,
        backbone_layers: int = 1,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        if input_size <= 0 or hidden_size <= 0:
            raise ValueError("input_size and hidden_size must be positive")
        self.input_size = input_size
        self.hidden_size = hidden_size
        layers: list[nn.Module] = []
        in_dim = input_size + hidden_size
        if backbone_layers > 0:
            for layer_i in range(backbone_layers):
                out_dim = backbone_units
                layers.extend([nn.Linear(in_dim, out_dim), LeCunTanh()])
                if dropout > 0 and layer_i + 1 < backbone_layers:
                    layers.append(nn.Dropout(dropout))
                in_dim = out_dim
            self.backbone = nn.Sequential(*layers)
        else:
            self.backbone = nn.Identity()
        self.ff1 = nn.Linear(in_dim, hidden_size)
        self.ff2 = nn.Linear(in_dim, hidden_size)
        self.time_a = nn.Linear(in_dim, hidden_size)
        self.time_b = nn.Linear(in_dim, hidden_size)
        self.reset_parameters()

    def reset_parameters(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                nn.init.zeros_(module.bias)

    def forward(
        self, x: torch.Tensor, h: torch.Tensor, elapsed: torch.Tensor
    ) -> torch.Tensor:
        if elapsed.ndim == 1:
            elapsed = elapsed.unsqueeze(-1)
        if elapsed.ndim != 2 or elapsed.shape[1] != 1:
            raise ValueError("elapsed must have shape (B,1) or (B,)")
        z = torch.cat([x, h], dim=-1)
        z = self.backbone(z)
        f1 = torch.tanh(self.ff1(z))
        f2 = torch.tanh(self.ff2(z))
        gate = torch.sigmoid(self.time_a(z) * elapsed + self.time_b(z))
        return f1 * (1.0 - gate) + gate * f2


class FullyConnectedLTCCell(nn.Module):
    """Dense LTC cell using the semi-implicit solver from the LTC formulation.

    This is not an NCP wiring implementation; every sensory input connects to
    every liquid neuron and every liquid neuron connects to every other liquid
    neuron. Positive conductance-like parameters use softplus constraints.
    """

    def __init__(
        self,
        input_size: int,
        hidden_size: int,
        *,
        ode_unfolds: int = 6,
        epsilon: float = 1e-8,
        seed: int = 0,
    ) -> None:
        super().__init__()
        if ode_unfolds <= 0:
            raise ValueError("ode_unfolds must be positive")
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.ode_unfolds = ode_unfolds
        self.epsilon = epsilon
        gen = torch.Generator().manual_seed(seed)

        def uniform(shape, lo, hi):
            return torch.rand(shape, generator=gen) * (hi - lo) + lo

        # unconstrained parameters transformed by softplus where positivity is
        # required. Initial inverse-softplus is unnecessary for this experiment;
        # moderate raw values yield numerically stable positive values.
        self.gleak_raw = nn.Parameter(uniform((hidden_size,), -1.0, 0.0))
        self.vleak = nn.Parameter(uniform((hidden_size,), -0.2, 0.2))
        self.cm_raw = nn.Parameter(uniform((hidden_size,), -0.3, 0.2))
        self.mu = nn.Parameter(uniform((hidden_size, hidden_size), 0.3, 0.8))
        self.sigma_raw = nn.Parameter(uniform((hidden_size, hidden_size), 1.0, 2.0))
        self.w_raw = nn.Parameter(uniform((hidden_size, hidden_size), -1.0, 0.0))
        erev = torch.randint(0, 2, (hidden_size, hidden_size), generator=gen).float() * 2 - 1
        self.erev = nn.Parameter(erev)
        self.sensory_mu = nn.Parameter(uniform((input_size, hidden_size), 0.3, 0.8))
        self.sensory_sigma_raw = nn.Parameter(uniform((input_size, hidden_size), 1.0, 2.0))
        self.sensory_w_raw = nn.Parameter(uniform((input_size, hidden_size), -1.0, 0.0))
        sensory_erev = torch.randint(0, 2, (input_size, hidden_size), generator=gen).float() * 2 - 1
        self.sensory_erev = nn.Parameter(sensory_erev)
        self.input_w = nn.Parameter(torch.ones(input_size))
        self.input_b = nn.Parameter(torch.zeros(input_size))

    @staticmethod
    def _positive(x: torch.Tensor) -> torch.Tensor:
        return F.softplus(x) + 1e-5

    @staticmethod
    def _sigmoid_activation(
        source: torch.Tensor, mu: torch.Tensor, sigma: torch.Tensor
    ) -> torch.Tensor:
        # source: (B,S); mu/sigma: (S,H) -> (B,S,H)
        return torch.sigmoid(sigma.unsqueeze(0) * (source.unsqueeze(-1) - mu.unsqueeze(0)))

    def forward(
        self, x: torch.Tensor, h: torch.Tensor, elapsed: torch.Tensor
    ) -> torch.Tensor:
        if elapsed.ndim == 1:
            elapsed = elapsed.unsqueeze(-1)
        elapsed = elapsed.clamp_min(1e-4)
        x = x * self.input_w + self.input_b

        sensory_act = self._positive(self.sensory_w_raw).unsqueeze(0) * self._sigmoid_activation(
            x, self.sensory_mu, self._positive(self.sensory_sigma_raw)
        )
        sensory_num = (sensory_act * self.sensory_erev.unsqueeze(0)).sum(dim=1)
        sensory_den = sensory_act.sum(dim=1)

        cm_t = self._positive(self.cm_raw).unsqueeze(0) / (elapsed / float(self.ode_unfolds))
        gleak = self._positive(self.gleak_raw).unsqueeze(0)
        w = self._positive(self.w_raw)
        sigma = self._positive(self.sigma_raw)
        v = h
        for _ in range(self.ode_unfolds):
            rec_act = w.unsqueeze(0) * self._sigmoid_activation(v, self.mu, sigma)
            rec_num = (rec_act * self.erev.unsqueeze(0)).sum(dim=1) + sensory_num
            rec_den = rec_act.sum(dim=1) + sensory_den
            numerator = cm_t * v + gleak * self.vleak.unsqueeze(0) + rec_num
            denominator = cm_t + gleak + rec_den + self.epsilon
            v = numerator / denominator
        return v


def count_parameters(module: nn.Module) -> int:
    return sum(p.numel() for p in module.parameters() if p.requires_grad)
