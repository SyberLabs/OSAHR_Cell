"""Continuous topology-coupled state models for Liquid-OSAHR Experiment 02A.

The experiment deliberately distinguishes two objects:

1. :class:`OracleField`: an analytically soluble topology-coupled continuous
   teacher.  Between graph jumps its latent state follows a stable linear flow
   with a graph-dependent equilibrium, so the exact latent state at any time is
   known in closed form.
2. :class:`NeuralLiquidField`: a learned entity-scoped continuous recurrent
   field.  Its segment map is anchored at the committed state and uses a CfC or
   GRU candidate update plus a continuous exponential blend.  Event-specific
   jump maps then update affected entity states after an OSAHR rewrite.

All learned hazard heads are bounded sigmoid maps.  Therefore each stochastic
rewrite channel has an analytic global upper bound suitable for exact rejection
thinning in OSAHR.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence
import copy
import math
import sys
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .liquid_base import CfCCell

VENDOR = Path(__file__).resolve().parents[1] / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from osahr.graph import Hypergraph  # type: ignore
from osahr.ids import EntityId  # type: ignore
from osahr.matcher import Match  # type: ignore


HEADS = ("service", "failure", "recovery", "handover")
HEAD_INDEX = {name: i for i, name in enumerate(HEADS)}
EVENTS = (
    "init",
    "generate-critical",
    "generate-background",
    "route-task",
    "complete-task",
    "reroute-failed-edge",
    "handover",
    "edge-failure",
    "edge-recovery",
)
EVENT_INDEX = {name: i for i, name in enumerate(EVENTS)}
RELATIONS = ("association", "path", "transit")


@dataclass(frozen=True)
class Scenario:
    """Episode-level exogenous context.

    These are intentionally compact latent-driving descriptors rather than a
    claim about a standards-complete radio channel.  They are observable to the
    learned twin, analogous to coarse mobility/environment/load context.
    """

    mobility: float = 1.0
    stress: float = 1.0
    channel: float = 1.0
    demand: float = 1.0

    def vector(self) -> np.ndarray:
        return np.asarray([self.mobility, self.stress, self.channel, self.demand], dtype=np.float32)


@dataclass(frozen=True)
class HazardBounds:
    service: float = 5.0
    failure: float = 0.22
    recovery: float = 0.85
    handover: float = 0.24
    floor: float = 1e-5

    def max_for(self, head: str) -> float:
        return float(getattr(self, head))

    def vector(self) -> np.ndarray:
        return np.asarray([self.service, self.failure, self.recovery, self.handover], dtype=np.float64)


@dataclass(frozen=True)
class PersistentIndex:
    ids: tuple[EntityId, ...]
    types: tuple[str, ...]
    id_to_index: Mapping[EntityId, int]

    @classmethod
    def from_graph(cls, graph: Hypergraph) -> "PersistentIndex":
        keep = [v for v in graph.vertices.values() if v.type_id in {"UE", "GNB", "EdgeNode"}]
        order = sorted(keep, key=lambda v: (0 if v.type_id == "UE" else 1 if v.type_id == "GNB" else 2, v.entity_id))
        ids = tuple(v.entity_id for v in order)
        types = tuple(v.type_id for v in order)
        return cls(ids, types, {entity_id: i for i, entity_id in enumerate(ids)})

    @property
    def n(self) -> int:
        return len(self.ids)


@dataclass
class GraphView:
    structural: np.ndarray  # (N,F)
    adjacency: np.ndarray   # (R,N,N), row-normalized receiver <- sender


STRUCT_FEATURES = (
    "type_ue", "type_gnb", "type_edge",
    "available", "load_ratio",
    "association_degree", "path_degree",
    "queued_tasks", "inflight_tasks",
    "mean_path_quality",
    "scenario_mobility", "scenario_stress", "scenario_channel", "scenario_demand",
)
STRUCT_DIM = len(STRUCT_FEATURES)


def _edge_vertices(edge) -> tuple[EntityId, ...]:
    return tuple(inc.vertex_id for inc in edge.incidences)


def graph_view(graph: Hypergraph, index: PersistentIndex, scenario: Scenario) -> GraphView:
    """Extract deterministic typed structural features and role-aware coupling.

    The three relation channels intentionally preserve coarse semantic relation
    types rather than flattening the hypergraph into one adjacency matrix.
    Transit is projected onto the persistent UE/gNB/MEC participants; Task
    vertices remain explicit in OSAHR but do not own liquid state in 02A.
    """

    n = index.n
    x = np.zeros((n, STRUCT_DIM), dtype=np.float32)
    A = np.zeros((len(RELATIONS), n, n), dtype=np.float32)
    scenario_vec = scenario.vector()

    # Base type / vertex-state features.
    for i, entity_id in enumerate(index.ids):
        vertex = graph.vertices[entity_id]
        if vertex.type_id == "UE":
            x[i, 0] = 1.0
        elif vertex.type_id == "GNB":
            x[i, 1] = 1.0
        else:
            x[i, 2] = 1.0
            x[i, 3] = 1.0 if vertex.attributes.get("available", True) else 0.0
            capacity = max(float(vertex.attributes.get("capacity", 1)), 1.0)
            x[i, 4] = float(vertex.attributes.get("load", 0)) / capacity
        x[i, 10:14] = scenario_vec

    # Association coupling and degree.
    for edge_id in graph.edges_by_type.get("Association", set()):
        edge = graph.edges[edge_id]
        ids = _edge_vertices(edge)
        if len(ids) != 2:
            continue
        a, b = ids
        if a in index.id_to_index and b in index.id_to_index:
            ia, ib = index.id_to_index[a], index.id_to_index[b]
            A[0, ia, ib] += 1.0; A[0, ib, ia] += 1.0
            x[ia, 5] += 1.0; x[ib, 5] += 1.0

    # Path coupling, degree, path-quality accumulation.
    quality_sum = np.zeros(n, dtype=np.float32)
    quality_count = np.zeros(n, dtype=np.float32)
    for edge_id in graph.edges_by_type.get("Path", set()):
        edge = graph.edges[edge_id]
        ids = _edge_vertices(edge)
        if len(ids) != 2:
            continue
        a, b = ids
        if a in index.id_to_index and b in index.id_to_index:
            ia, ib = index.id_to_index[a], index.id_to_index[b]
            A[1, ia, ib] += 1.0; A[1, ib, ia] += 1.0
            x[ia, 6] += 1.0; x[ib, 6] += 1.0
            q = float(edge.attributes.get("link_quality", 1.0))
            quality_sum[ia] += q; quality_sum[ib] += q
            quality_count[ia] += 1.0; quality_count[ib] += 1.0

    # Task-state counts and transit hyperedge coupling.
    for edge_id in graph.edges_by_type.get("Queued", set()):
        edge = graph.edges[edge_id]
        for inc in edge.incidences:
            if inc.vertex_id in index.id_to_index and graph.vertices[inc.vertex_id].type_id == "UE":
                x[index.id_to_index[inc.vertex_id], 7] += 1.0

    for edge_id in graph.edges_by_type.get("Transit", set()):
        edge = graph.edges[edge_id]
        persistent = [inc.vertex_id for inc in edge.incidences if inc.vertex_id in index.id_to_index]
        for entity_id in persistent:
            x[index.id_to_index[entity_id], 8] += 1.0
        for a in persistent:
            for b in persistent:
                if a != b:
                    A[2, index.id_to_index[a], index.id_to_index[b]] += 1.0

    # Normalize count-like features to keep magnitudes stable.
    x[:, 5] /= 4.0
    x[:, 6] /= 4.0
    x[:, 7] /= 6.0
    x[:, 8] /= 6.0
    nonzero = quality_count > 0
    x[nonzero, 9] = quality_sum[nonzero] / quality_count[nonzero]

    # Receiver-normalize each relation matrix.
    for r in range(A.shape[0]):
        row = A[r].sum(axis=1, keepdims=True)
        nz = row[:, 0] > 0
        A[r, nz] /= row[nz]
    return GraphView(x, A)


def event_affected_mask(rule_id: str, match: Match | None, index: PersistentIndex) -> np.ndarray:
    mask = np.zeros(index.n, dtype=np.float32)
    if match is None:
        return mask
    keys_by_rule = {
        "generate-critical": ("ue",),
        "generate-background": ("ue",),
        "route-task": ("ue", "gnb", "edge"),
        "complete-task": ("ue", "gnb", "edge"),
        "reroute-failed-edge": ("ue", "gnb", "edge"),
        "handover": ("ue", "old", "new"),
        "edge-failure": ("edge",),
        "edge-recovery": ("edge",),
    }
    for key in keys_by_rule.get(rule_id, ()):  # pragma: no branch - fixed mapping
        entity_id = match.vertex_map.get(key)
        if entity_id in index.id_to_index:
            mask[index.id_to_index[entity_id]] = 1.0
    return mask


def applicable_head_mask(graph: Hypergraph, index: PersistentIndex) -> np.ndarray:
    """Return an (N,4) mask for semantically meaningful base hazards."""
    out = np.zeros((index.n, len(HEADS)), dtype=np.float32)
    for i, entity_id in enumerate(index.ids):
        vertex = graph.vertices[entity_id]
        if vertex.type_id == "UE":
            out[i, HEAD_INDEX["handover"]] = 1.0
        elif vertex.type_id == "EdgeNode":
            out[i, HEAD_INDEX["service"]] = 1.0
            if vertex.attributes.get("available", True):
                out[i, HEAD_INDEX["failure"]] = 1.0
            else:
                out[i, HEAD_INDEX["recovery"]] = 1.0
    return out


class FieldBase:
    """Stateful continuous field interface used by the hybrid runtime."""

    name = "base"

    def __init__(self, index: PersistentIndex, scenario: Scenario, bounds: HazardBounds):
        self.index = index
        self.scenario = scenario
        self.bounds = bounds
        self.anchor_time = 0.0

    def initialize(self, graph: Hypergraph) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def state_at(self, time: float, graph: Hypergraph) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def base_rates_at(self, time: float, graph: Hypergraph) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def commit_event(
        self,
        time: float,
        pre_graph: Hypergraph,
        post_graph: Hypergraph,
        rule_id: str,
        match: Match,
    ) -> dict[str, object]:  # pragma: no cover
        raise NotImplementedError

    def snapshot(self) -> dict[str, object]:  # pragma: no cover
        raise NotImplementedError

    def restore(self, snapshot: Mapping[str, object]) -> None:  # pragma: no cover
        raise NotImplementedError

    def canonical_at(self, time: float, graph: Hypergraph) -> dict[str, object]:
        state = self.state_at(time, graph)
        return {
            "name": self.name,
            "anchor_time": float(self.anchor_time),
            "state_time": float(time),
            "state": np.asarray(state, dtype=np.float64).tolist(),
            "scenario": self.scenario.__dict__,
            "bounds": self.bounds.__dict__,
        }


class OracleField(FieldBase):
    """Analytically soluble topology-coupled teacher field.

    Between jumps each entity dimension follows

        dh/dt = -alpha_type * (h - mu(G, scenario))

    where ``mu`` is constant while the OSAHR structural state is unchanged.
    Therefore

        h(t+dt) = mu + (h(t)-mu) exp(-alpha dt)

    is exact.  Structural rewrites alter ``mu`` and selected events also apply
    explicit bounded jump increments to affected entity states.
    """

    name = "oracle"

    def __init__(self, index: PersistentIndex, scenario: Scenario, bounds: HazardBounds, *, seed: int = 0, initial_noise: float = 0.0):
        super().__init__(index, scenario, bounds)
        self.seed = int(seed)
        self.initial_noise = float(initial_noise)
        self.anchor_state = np.zeros((index.n, 3), dtype=np.float64)
        self._state_cache_key = None
        self._state_cache = None
        self._rate_cache_key = None
        self._rate_cache = None

    def _invalidate_eval_cache(self) -> None:
        self._state_cache_key=None; self._state_cache=None
        self._rate_cache_key=None; self._rate_cache=None

    def _alpha(self) -> np.ndarray:
        out = np.zeros((self.index.n, 3), dtype=np.float64)
        for i, typ in enumerate(self.index.types):
            if typ == "UE": out[i] = (0.75, 0.55, 0.65)
            elif typ == "GNB": out[i] = (0.62, 0.48, 0.52)
            else: out[i] = (0.88, 0.44, 0.70)
        return out

    def _equilibrium(self, graph: Hypergraph) -> np.ndarray:
        v = graph_view(graph, self.index, self.scenario).structural.astype(np.float64)
        mu = np.zeros((self.index.n, 3), dtype=np.float64)
        for i, typ in enumerate(self.index.types):
            if typ == "UE":
                # mobility propensity, radio stress, local task pressure
                mu[i, 0] = 0.35 + 0.55*self.scenario.mobility + 0.35*v[i,5]
                mu[i, 1] = 0.20 + 0.45*(1.0-v[i,9]) + 0.25*self.scenario.stress
                mu[i, 2] = 0.15 + 0.80*v[i,7] + 0.35*v[i,8]
            elif typ == "GNB":
                mu[i, 0] = 0.15 + 0.85*v[i,5] + 0.35*v[i,8]
                mu[i, 1] = 0.20 + 0.45*(1.0-v[i,9]) + 0.25*self.scenario.channel
                mu[i, 2] = 0.25 + 0.50*self.scenario.mobility + 0.20*v[i,5]
            else:
                mu[i, 0] = 0.10 + 1.30*v[i,4] + 0.35*v[i,8] + 0.20*self.scenario.demand
                mu[i, 1] = 0.10 + 0.55*self.scenario.stress + 0.55*v[i,4] + 0.45*(1.0-v[i,3])
                mu[i, 2] = 0.25 + 0.70*self.scenario.channel + 0.35*v[i,9] - 0.55*v[i,4]
        return np.clip(mu, -2.5, 2.5)

    def initialize(self, graph: Hypergraph) -> None:
        rng = np.random.default_rng(self.seed)
        mu = self._equilibrium(graph)
        # Small episode-specific perturbation is deterministic from seed.
        self.anchor_state = np.clip(mu + rng.normal(0.0, self.initial_noise, size=mu.shape), -3.0, 3.0)
        self.anchor_time = 0.0
        self._invalidate_eval_cache()

    def state_at(self, time: float, graph: Hypergraph) -> np.ndarray:
        if time < self.anchor_time - 1e-12:
            raise ValueError("oracle field cannot evaluate before anchor time")
        key=(float(time),graph.epoch,float(self.anchor_time))
        if self._state_cache_key==key and self._state_cache is not None:
            return self._state_cache.copy()
        dt = max(0.0, float(time - self.anchor_time))
        mu = self._equilibrium(graph)
        decay = np.exp(-self._alpha() * dt)
        value=mu + (self.anchor_state - mu) * decay
        self._state_cache_key=key; self._state_cache=value
        return value.copy()

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        return 1.0/(1.0+np.exp(-np.clip(x, -40.0, 40.0)))

    def base_rates_at(self, time: float, graph: Hypergraph) -> np.ndarray:
        key=(float(time),graph.epoch,float(self.anchor_time))
        if self._rate_cache_key==key and self._rate_cache is not None:
            return self._rate_cache.copy()
        h = self.state_at(time, graph)
        view = graph_view(graph, self.index, self.scenario).structural.astype(np.float64)
        out = np.zeros((self.index.n, len(HEADS)), dtype=np.float64)
        floor = self.bounds.floor
        maxima = self.bounds.vector()
        for i, typ in enumerate(self.index.types):
            if typ == "UE":
                z = -3.00 + 1.45*h[i,0] + 0.85*h[i,1] + 0.30*self.scenario.mobility + 0.25*view[i,7]
                out[i,3] = floor + (maxima[3]-floor)*self._sigmoid(np.asarray(z))
            elif typ == "EdgeNode":
                z_s = 0.55 + 1.75*h[i,2] - 1.35*h[i,0] - 0.45*h[i,1] + 0.40*self.scenario.channel
                z_f = -3.10 + 1.55*h[i,1] + 0.85*h[i,0] + 0.35*self.scenario.stress
                z_r = -0.20 - 0.55*h[i,1] + 0.25*h[i,2]
                out[i,0] = floor + (maxima[0]-floor)*self._sigmoid(np.asarray(z_s))
                if graph.vertices[self.index.ids[i]].attributes.get("available", True):
                    out[i,1] = floor + (maxima[1]-floor)*self._sigmoid(np.asarray(z_f))
                else:
                    out[i,2] = floor + (maxima[2]-floor)*self._sigmoid(np.asarray(z_r))
        self._rate_cache_key=key; self._rate_cache=out
        return out.copy()

    def _jump_delta(self, rule_id: str, affected: np.ndarray, post_graph: Hypergraph) -> np.ndarray:
        delta = np.zeros_like(self.anchor_state)
        # Event-specific mechanistic jump directions.
        vectors = {
            "generate-critical": np.array([0.00, 0.00, +0.16]),
            "generate-background": np.array([0.00, 0.00, +0.06]),
            "route-task": np.array([0.00, +0.02, +0.08]),
            "complete-task": np.array([0.00, -0.03, -0.11]),
            "reroute-failed-edge": np.array([+0.02, +0.08, +0.05]),
            "handover": np.array([-0.14, +0.04, 0.00]),
            "edge-failure": np.array([0.00, +0.55, -0.25]),
            "edge-recovery": np.array([0.00, -0.35, +0.20]),
        }
        vec = vectors.get(rule_id, np.zeros(3))
        delta += affected[:,None] * vec[None,:]
        # A failure also raises stress at gNBs connected to that edge through Path.
        if rule_id == "edge-failure":
            view = graph_view(post_graph, self.index, self.scenario)
            edge_idxs = np.flatnonzero(affected > 0.5)
            for ei in edge_idxs:
                for gi in np.flatnonzero(view.adjacency[1, :, ei] > 0):
                    delta[gi,0] += 0.12
        return delta

    def commit_event(self, time: float, pre_graph: Hypergraph, post_graph: Hypergraph, rule_id: str, match: Match) -> dict[str, object]:
        pre = self.state_at(time, pre_graph)
        affected = event_affected_mask(rule_id, match, self.index)
        post = np.clip(pre + self._jump_delta(rule_id, affected, post_graph), -3.0, 3.0)
        before = self.anchor_state.copy()
        self.anchor_state = post
        self.anchor_time = float(time)
        self._invalidate_eval_cache()
        return {
            "rule": rule_id,
            "affected": affected.tolist(),
            "pre_state": pre.tolist(),
            "post_state": post.tolist(),
            "previous_anchor": before.tolist(),
        }

    def snapshot(self) -> dict[str, object]:
        return {"anchor_time": self.anchor_time, "anchor_state": self.anchor_state.copy(), "seed": self.seed, "initial_noise": self.initial_noise}

    def restore(self, snapshot: Mapping[str, object]) -> None:
        self.anchor_time = float(snapshot["anchor_time"])
        self.anchor_state = np.asarray(snapshot["anchor_state"], dtype=np.float64).copy()
        self._invalidate_eval_cache()


class AnchoredGraphCfC(nn.Module):
    """Entity-scoped topology-conditioned anchored CfC field.

    ``CfCCell`` produces a continuous-time candidate state.  A strictly
    continuous outer anchor blend ensures Phi(h, 0) = h exactly:

        h(t+dt) = h + (1-exp(-softplus(kappa) dt)) * (cfc(x,h,dt)-h)

    Relation-specific hidden-state messages are computed on the current OSAHR
    topology before the candidate update.
    """

    def __init__(self, structural_dim: int, hidden_size: int = 20, *, use_jumps: bool = True, dynamic_topology: bool = True):
        super().__init__()
        self.structural_dim = structural_dim
        self.hidden_size = hidden_size
        self.use_jumps = use_jumps
        self.dynamic_topology = dynamic_topology
        self.rel = nn.ModuleList([nn.Linear(hidden_size, hidden_size, bias=False) for _ in RELATIONS])
        self.input_proj = nn.Sequential(
            nn.Linear(structural_dim + hidden_size, 48), nn.Tanh(), nn.Linear(48, 32), nn.Tanh()
        )
        self.cell = CfCCell(32, hidden_size, backbone_units=48, backbone_layers=1)
        self.kappa_raw = nn.Parameter(torch.zeros(hidden_size))
        self.init_net = nn.Sequential(nn.Linear(structural_dim, 48), nn.Tanh(), nn.Linear(48, hidden_size), nn.Tanh())
        self.jump_event = nn.Embedding(len(EVENTS), hidden_size)
        self.jump_struct = nn.Linear(structural_dim, hidden_size)
        self.jump_gate = nn.Linear(hidden_size + structural_dim, hidden_size)
        self.hazard_head = nn.Linear(hidden_size + structural_dim, len(HEADS))
        self.reset_parameters()

    def reset_parameters(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None: nn.init.zeros_(module.bias)
        nn.init.normal_(self.jump_event.weight, mean=0.0, std=0.08)

    def initial_state(self, structural: torch.Tensor) -> torch.Tensor:
        return self.init_net(structural)

    def _message(self, h: torch.Tensor, adjacency: torch.Tensor) -> torch.Tensor:
        # h (B,N,H), adjacency (B,R,N,N), receiver <- sender
        out = torch.zeros_like(h)
        for r, layer in enumerate(self.rel):
            transformed = layer(h)
            out = out + torch.einsum("bij,bjh->bih", adjacency[:,r], transformed)
        return out / float(len(self.rel))

    def flow(self, h: torch.Tensor, structural: torch.Tensor, adjacency: torch.Tensor, dt: torch.Tensor) -> torch.Tensor:
        if dt.ndim == 1: dt = dt[:,None]
        msg = self._message(h, adjacency)
        inp = self.input_proj(torch.cat([structural, msg], dim=-1))
        B,N,_ = inp.shape
        elapsed = dt[:,None,:].expand(B,N,1).reshape(B*N,1)
        candidate = self.cell(inp.reshape(B*N,-1), h.reshape(B*N,-1), elapsed).reshape(B,N,-1)
        kappa = torch.nn.functional.softplus(self.kappa_raw).view(1,1,-1) + 1e-4
        alpha = 1.0 - torch.exp(-kappa * dt[:,None,:])
        return h + alpha * (candidate - h)

    def jump(self, h: torch.Tensor, event_code: torch.Tensor, affected: torch.Tensor, structural: torch.Tensor) -> torch.Tensor:
        if not self.use_jumps:
            return h
        event = self.jump_event(event_code)[:,None,:]
        proposal = torch.tanh(event + self.jump_struct(structural))
        gate = torch.sigmoid(self.jump_gate(torch.cat([h, structural], dim=-1)))
        return h + affected[:,:,None] * 0.35 * gate * proposal

    def rates(self, h: torch.Tensor, structural: torch.Tensor, bounds: torch.Tensor, floor: float) -> torch.Tensor:
        logits = self.hazard_head(torch.cat([h, structural], dim=-1))
        return floor + (bounds.view(1,1,-1)-floor) * torch.sigmoid(logits)


class AnchoredGraphGRU(nn.Module):
    """Matched conceptual baseline with the same graph messages and jump API."""

    def __init__(self, structural_dim: int, hidden_size: int = 20, *, use_jumps: bool = True, dynamic_topology: bool = True):
        super().__init__()
        self.structural_dim = structural_dim; self.hidden_size = hidden_size
        self.use_jumps = use_jumps; self.dynamic_topology = dynamic_topology
        self.rel = nn.ModuleList([nn.Linear(hidden_size, hidden_size, bias=False) for _ in RELATIONS])
        self.input_proj = nn.Sequential(nn.Linear(structural_dim+hidden_size+1,48), nn.Tanh(), nn.Linear(48,32), nn.Tanh())
        self.cell = nn.GRUCell(32, hidden_size)
        self.kappa_raw = nn.Parameter(torch.zeros(hidden_size))
        self.init_net = nn.Sequential(nn.Linear(structural_dim,48), nn.Tanh(), nn.Linear(48,hidden_size), nn.Tanh())
        self.jump_event = nn.Embedding(len(EVENTS), hidden_size)
        self.jump_struct = nn.Linear(structural_dim, hidden_size)
        self.jump_gate = nn.Linear(hidden_size+structural_dim, hidden_size)
        self.hazard_head = nn.Linear(hidden_size+structural_dim, len(HEADS))
        self.reset_parameters()

    def reset_parameters(self):
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None: nn.init.zeros_(module.bias)
        nn.init.normal_(self.jump_event.weight, mean=0.0, std=0.08)

    def initial_state(self, structural): return self.init_net(structural)
    def _message(self,h,adjacency):
        out=torch.zeros_like(h)
        for r,layer in enumerate(self.rel):
            out=out+torch.einsum("bij,bjh->bih",adjacency[:,r],layer(h))
        return out/float(len(self.rel))
    def flow(self,h,structural,adjacency,dt):
        if dt.ndim==1: dt=dt[:,None]
        msg=self._message(h,adjacency)
        B,N,_=h.shape
        logdt=torch.log1p(dt)[:,None,:].expand(B,N,1)
        inp=self.input_proj(torch.cat([structural,msg,logdt],dim=-1))
        candidate=self.cell(inp.reshape(B*N,-1),h.reshape(B*N,-1)).reshape(B,N,-1)
        kappa=torch.nn.functional.softplus(self.kappa_raw).view(1,1,-1)+1e-4
        alpha=1.0-torch.exp(-kappa*dt[:,None,:])
        return h+alpha*(candidate-h)
    def jump(self,h,event_code,affected,structural):
        if not self.use_jumps: return h
        event=self.jump_event(event_code)[:,None,:]
        proposal=torch.tanh(event+self.jump_struct(structural))
        gate=torch.sigmoid(self.jump_gate(torch.cat([h,structural],dim=-1)))
        return h+affected[:,:,None]*0.35*gate*proposal
    def rates(self,h,structural,bounds,floor):
        logits=self.hazard_head(torch.cat([h,structural],dim=-1))
        return floor+(bounds.view(1,1,-1)-floor)*torch.sigmoid(logits)


class NeuralLiquidField(FieldBase):
    """Runtime adapter for a trained anchored graph liquid/recurrent field."""

    def __init__(
        self,
        model: nn.Module,
        index: PersistentIndex,
        scenario: Scenario,
        bounds: HazardBounds,
        *,
        device: str = "cpu",
        name: str = "cfc_closed",
        frozen_adjacency: np.ndarray | None = None,
    ):
        super().__init__(index, scenario, bounds)
        self.model = model.to(device).eval()
        self.device = device
        self.name = name
        self.anchor_state = np.zeros((index.n, int(model.hidden_size)), dtype=np.float32)
        self.frozen_adjacency = None if frozen_adjacency is None else np.asarray(frozen_adjacency,dtype=np.float32).copy()
        self._view_cache_epoch: int | None = None
        self._view_cache = None
        self._state_cache_key = None
        self._state_cache = None
        self._rate_cache_key = None
        self._rate_cache = None

    def _view_tensors(self, graph: Hypergraph):
        if self._view_cache_epoch == graph.epoch and self._view_cache is not None:
            return self._view_cache
        view=graph_view(graph,self.index,self.scenario)
        structural=torch.from_numpy(view.structural).unsqueeze(0).to(self.device)
        adj_np=self.frozen_adjacency if self.frozen_adjacency is not None else view.adjacency
        adjacency=torch.from_numpy(adj_np).unsqueeze(0).to(self.device)
        self._view_cache_epoch=graph.epoch
        self._view_cache=(structural,adjacency)
        return self._view_cache

    def _invalidate_eval_cache(self):
        self._state_cache_key=None; self._state_cache=None
        self._rate_cache_key=None; self._rate_cache=None

    def initialize(self, graph: Hypergraph) -> None:
        structural,_=self._view_tensors(graph)
        with torch.no_grad():
            self.anchor_state=self.model.initial_state(structural)[0].cpu().numpy().astype(np.float32)
        self.anchor_time=0.0
        self._invalidate_eval_cache()

    def state_at(self,time:float,graph:Hypergraph)->np.ndarray:
        if time < self.anchor_time-1e-12: raise ValueError("neural field cannot evaluate before anchor time")
        key=(float(time),graph.epoch,float(self.anchor_time))
        if self._state_cache_key==key and self._state_cache is not None:
            return self._state_cache.copy()
        structural,adjacency=self._view_tensors(graph)
        h=torch.from_numpy(self.anchor_state).unsqueeze(0).to(self.device)
        dt=torch.tensor([[max(0.0,float(time-self.anchor_time))]],dtype=h.dtype,device=self.device)
        with torch.inference_mode():
            out=self.model.flow(h,structural,adjacency,dt)
        value=out[0].cpu().numpy().astype(np.float64)
        self._state_cache_key=key; self._state_cache=value
        return value.copy()

    def base_rates_at(self,time:float,graph:Hypergraph)->np.ndarray:
        key=(float(time),graph.epoch,float(self.anchor_time))
        if self._rate_cache_key==key and self._rate_cache is not None:
            return self._rate_cache.copy()
        structural,adjacency=self._view_tensors(graph)
        h=torch.from_numpy(self.anchor_state).unsqueeze(0).to(self.device)
        dt=torch.tensor([[max(0.0,float(time-self.anchor_time))]],dtype=h.dtype,device=self.device)
        bounds=torch.tensor(self.bounds.vector(),dtype=h.dtype,device=self.device)
        with torch.inference_mode():
            state=self.model.flow(h,structural,adjacency,dt)
            rates=self.model.rates(state,structural,bounds,self.bounds.floor)
        out=rates[0].cpu().numpy().astype(np.float64)
        out*=applicable_head_mask(graph,self.index)
        self._rate_cache_key=key; self._rate_cache=out
        # State and rate evaluation share the same state; cache it too.
        self._state_cache_key=key; self._state_cache=state[0].cpu().numpy().astype(np.float64)
        return out.copy()

    def commit_event(self,time:float,pre_graph:Hypergraph,post_graph:Hypergraph,rule_id:str,match:Match)->dict[str,object]:
        # Flow under the PRE-event topology, then apply a jump using POST-event structure.
        pre_struct,pre_adj=self._view_tensors(pre_graph)
        h=torch.from_numpy(self.anchor_state).unsqueeze(0).to(self.device)
        dt=torch.tensor([[max(0.0,float(time-self.anchor_time))]],dtype=h.dtype,device=self.device)
        post_view=graph_view(post_graph,self.index,self.scenario)
        post_struct=torch.from_numpy(post_view.structural).unsqueeze(0).to(self.device)
        affected_np=event_affected_mask(rule_id,match,self.index)
        affected=torch.from_numpy(affected_np).unsqueeze(0).to(self.device)
        code=torch.tensor([EVENT_INDEX.get(rule_id,0)],dtype=torch.long,device=self.device)
        with torch.inference_mode():
            pre_state=self.model.flow(h,pre_struct,pre_adj,dt)
            post_state=self.model.jump(pre_state,code,affected,post_struct)
        before=self.anchor_state.copy()
        self.anchor_state=post_state[0].cpu().numpy().astype(np.float32)
        self.anchor_time=float(time)
        self._invalidate_eval_cache()
        self._view_cache_epoch=None; self._view_cache=None
        return {"rule":rule_id,"affected":affected_np.tolist(),"pre_state":pre_state[0].cpu().numpy().tolist(),"post_state":self.anchor_state.tolist(),"previous_anchor":before.tolist()}

    def snapshot(self)->dict[str,object]:
        return {"anchor_time":self.anchor_time,"anchor_state":self.anchor_state.copy(),"name":self.name}
    def restore(self,snapshot:Mapping[str,object])->None:
        self.anchor_time=float(snapshot["anchor_time"])
        self.anchor_state=np.asarray(snapshot["anchor_state"],dtype=np.float32).copy()
        self._invalidate_eval_cache(); self._view_cache_epoch=None; self._view_cache=None


def parameter_count(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)

class FrozenOpenLoopNeuralField(FieldBase):
    """Open-loop neural field ablation for Experiment 02A.

    The neural model sees the *initial* structural features and adjacency for the
    entire episode and receives no event jump feedback.  Candidate rates evolve
    continuously with elapsed time from the fixed initial anchor.  OSAHR still
    controls structural legality: ``applicable_head_mask`` is evaluated on the
    current graph, so (for example) failure cannot fire on an already failed
    edge and recovery cannot fire on an available one.

    This is intentionally not the proposed architecture.  It is a controlled
    ablation that asks whether feeding graph rewrites back into the continuous
    learned state improves counterfactual fidelity.
    """
    def __init__(self, model: nn.Module, index: PersistentIndex, scenario: Scenario, bounds: HazardBounds, *, device: str='cpu', name: str='cfc_openloop'):
        super().__init__(index, scenario, bounds)
        self.model=model.to(device).eval(); self.device=device; self.name=name
        self.initial_state_array=np.zeros((index.n,int(model.hidden_size)),dtype=np.float32)
        self._structural=None; self._adjacency=None
        self._state_cache_key=None; self._state_cache=None; self._rate_cache_key=None; self._rate_cache=None

    def initialize(self, graph: Hypergraph)->None:
        view=graph_view(graph,self.index,self.scenario)
        self._structural=torch.from_numpy(view.structural).unsqueeze(0).to(self.device)
        self._adjacency=torch.from_numpy(view.adjacency).unsqueeze(0).to(self.device)
        with torch.inference_mode():
            self.initial_state_array=self.model.initial_state(self._structural)[0].cpu().numpy().astype(np.float32)
        self.anchor_time=0.0; self._invalidate()

    def _invalidate(self):
        self._state_cache_key=None; self._state_cache=None; self._rate_cache_key=None; self._rate_cache=None

    def state_at(self,time:float,graph:Hypergraph)->np.ndarray:
        if time < -1e-12: raise ValueError('open-loop field cannot evaluate negative time')
        key=float(time)
        if self._state_cache_key==key and self._state_cache is not None: return self._state_cache.copy()
        h=torch.from_numpy(self.initial_state_array).unsqueeze(0).to(self.device)
        dt=torch.tensor([[max(0.0,float(time))]],dtype=h.dtype,device=self.device)
        with torch.inference_mode(): out=self.model.flow(h,self._structural,self._adjacency,dt)
        val=out[0].cpu().numpy().astype(np.float64); self._state_cache_key=key; self._state_cache=val
        return val.copy()

    def base_rates_at(self,time:float,graph:Hypergraph)->np.ndarray:
        key=(float(time),graph.epoch)
        if self._rate_cache_key==key and self._rate_cache is not None: return self._rate_cache.copy()
        h=torch.from_numpy(self.initial_state_array).unsqueeze(0).to(self.device)
        dt=torch.tensor([[max(0.0,float(time))]],dtype=h.dtype,device=self.device)
        b=torch.tensor(self.bounds.vector(),dtype=h.dtype,device=self.device)
        with torch.inference_mode():
            state=self.model.flow(h,self._structural,self._adjacency,dt)
            rates=self.model.rates(state,self._structural,b,self.bounds.floor)
        out=rates[0].cpu().numpy().astype(np.float64)*applicable_head_mask(graph,self.index)
        self._rate_cache_key=key; self._rate_cache=out
        self._state_cache_key=float(time); self._state_cache=state[0].cpu().numpy().astype(np.float64)
        return out.copy()

    def commit_event(self,time:float,pre_graph:Hypergraph,post_graph:Hypergraph,rule_id:str,match:Match)->dict[str,object]:
        # Deliberately no feedback.  Only invalidate the legality-masked rate
        # cache because the current graph may have changed availability state.
        self._rate_cache_key=None; self._rate_cache=None
        return {'rule':rule_id,'open_loop':True,'affected':event_affected_mask(rule_id,match,self.index).tolist()}

    def snapshot(self)->dict[str,object]:
        return {'anchor_time':0.0,'initial_state':self.initial_state_array.copy(),'name':self.name}

    def restore(self,snapshot:Mapping[str,object])->None:
        self.anchor_time=0.0; self.initial_state_array=np.asarray(snapshot['initial_state'],dtype=np.float32).copy(); self._invalidate()
