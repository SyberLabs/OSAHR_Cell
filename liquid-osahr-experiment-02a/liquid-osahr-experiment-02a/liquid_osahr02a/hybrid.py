"""Hybrid Liquid-OSAHR runtime with exact thinning and bounded neural hazards."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import copy
import math

from osahr import Runtime, RuntimeConfig, Model, SchedulerKind  # type: ignore
from osahr.canonical import stable_hash  # type: ignore
from osahr.errors import HazardBoundError, HazardError  # type: ignore
from osahr.graph import Hypergraph, GraphDelta  # type: ignore
from osahr.matcher import Match  # type: ignore
from osahr.occurrence import Occurrence, OccurrenceIndex, OccurrenceKey  # type: ignore
from osahr.pattern import Rule  # type: ignore

from .field import FieldBase, HEAD_INDEX


NEURAL_RULES = {
    "complete-task": ("service", "edge"),
    "edge-failure": ("failure", "edge"),
    "edge-recovery": ("recovery", "edge"),
    "handover": ("handover", "ue"),
}


class LiquidOccurrenceIndex(OccurrenceIndex):
    """Occurrence index whose selected hazards are supplied by a liquid field.

    Structural matching, DPO applicability, and all non-neural rules remain the
    authoritative OSAHR implementation.  Only the scalar stochastic intensity
    of explicitly tagged rules is delegated to the field.
    """

    def __init__(self, field: FieldBase, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.field = field

    def _liquid_hazard(self, graph: Hypergraph, rule: Rule, match: Match, time: float, parameters: dict[str,Any]) -> float:
        head_info = NEURAL_RULES.get(rule.rule_id)
        if head_info is None:
            raise KeyError(rule.rule_id)
        head, vertex_key = head_info
        entity_id = match.vertex_map[vertex_key]
        idx = self.field.index.id_to_index[entity_id]
        base = float(self.field.base_rates_at(time, graph)[idx, HEAD_INDEX[head]])
        if rule.rule_id == "complete-task":
            b = match.bindings
            payload = max(float(b.get("task_payload", 1.0)), 1.0)
            reliability = min(max(float(b.get("reliability", 1.0)), 0.0), 1.0)
            link_quality = min(max(float(b.get("link_quality", 1.0)), 0.0), 1.0)
            load = max(float(b.get("load", 1.0)), 1.0)
            penalty = max(float(parameters.get("congestion_penalty", 0.0)), 0.0)
            base *= reliability * link_quality / (payload * (1.0 + penalty * max(0.0, load - 1.0)))
        if not math.isfinite(base) or base < 0.0:
            raise HazardError(f"Invalid liquid hazard {base!r} for {rule.rule_id}/{match.match_id}")
        return base

    def _hazard(self, graph: Hypergraph, rule: Rule, match: Match, *, parameters: dict[str,Any], memory: dict[str,Any], time: float) -> float | None:
        if rule.rule_id in NEURAL_RULES:
            return self._liquid_hazard(graph, rule, match, time, parameters)
        return super()._hazard(graph, rule, match, parameters=parameters, memory=memory, time=time)

    def hazard_at(self, occurrence: Occurrence, *, graph: Hypergraph, parameters: dict[str,Any], memory: dict[str,Any], time: float) -> float:
        if occurrence.rule.rule_id in NEURAL_RULES:
            return self._liquid_hazard(graph, occurrence.rule, occurrence.match, time, parameters)
        return super().hazard_at(occurrence, graph=graph, parameters=parameters, memory=memory, time=time)

    def bound_at(self, occurrence: Occurrence, *, graph: Hypergraph, parameters: dict[str,Any], memory: dict[str,Any], time: float, horizon: float) -> float:
        if occurrence.rule.rule_id not in NEURAL_RULES:
            return super().bound_at(occurrence, graph=graph, parameters=parameters, memory=memory, time=time, horizon=horizon)
        head, _ = NEURAL_RULES[occurrence.rule.rule_id]
        bound = self.field.bounds.max_for(head)
        # Completion modifiers are in [0,1], so the base-head maximum remains a valid bound.
        actual = self.hazard_at(occurrence, graph=graph, parameters=parameters, memory=memory, time=time)
        tolerance = 1e-12 * max(1.0, abs(actual), abs(bound))
        if actual > bound + tolerance:
            raise HazardBoundError(
                f"Liquid hazard bound violated for {occurrence.key}: actual={actual}, bound={bound}"
            )
        return float(bound)

    def integrated_hazard(self, occurrence: Occurrence, *, graph: Hypergraph, parameters: dict[str,Any], memory: dict[str,Any], start_time: float, end_time: float) -> float | None:
        if occurrence.rule.rule_id in NEURAL_RULES:
            # Exact event generation does not require this integral. Experiment
            # 02A intentionally leaves likelihood survival terms numerical.
            return None
        return super().integrated_hazard(
            occurrence, graph=graph, parameters=parameters, memory=memory,
            start_time=start_time, end_time=end_time,
        )


@dataclass
class HybridSnapshot:
    base: Any
    field: dict[str,object]


class HybridLiquidRuntime(Runtime):
    """OSAHR runtime with continuous liquid state in the augmented state.

    Candidate thinning evaluations are pure: the field computes ``state_at(t)``
    from the last committed anchor without mutating it.  Only an accepted OSAHR
    rewrite commits the pre-event continuous state and applies an event jump.
    This is essential because rejected thinning candidates must not advance the
    authoritative latent state.
    """

    RUNTIME_VERSION = "liquid-osahr-02a-0.1.0"

    def __init__(self, model: Model, *, field: FieldBase, root_seed: int, config: RuntimeConfig | None = None) -> None:
        config = config or RuntimeConfig(scheduler=SchedulerKind.THINNING, matcher_backend="incremental", thinning_window=0.75)
        if config.scheduler_kind is not SchedulerKind.THINNING:
            raise ValueError("HybridLiquidRuntime requires the exact thinning scheduler")
        super().__init__(model, root_seed=root_seed, config=config)
        self.field = field
        self.field.initialize(self.graph)
        self.occurrence_index = LiquidOccurrenceIndex(
            field,
            matcher_backend=self.config.matcher_backend,
            max_matches_per_rule=self.config.max_matches_per_rule,
            max_total_activity=self.config.max_total_activity,
            invalid_hazard_policy=self.config.invalid_hazard_policy,
        )
        self.matcher = self.occurrence_index.reference
        self._indexed_augmented_hash = None
        self.liquid_audit: list[dict[str,object]] = []
        self.run_id = stable_hash({
            "base_run_id": self.run_id,
            "field": self.field.name,
            "field_initial": self.field.canonical_at(0.0, self.graph),
        })

    def _state_hash_at(self, time_value: float) -> str:
        base = {
            "graph": self.graph.to_canonical(),
            "boundary": self.boundary.to_canonical(),
            "rules": self._rule_state_canonical(),
            "parameters": self.parameters,
            "memory": self.memory,
            "time": time_value,
            "event_index": self.event_index,
        }
        field = getattr(self, "field", None)
        if field is not None:
            base["liquid"] = field.canonical_at(time_value, self.graph)
        return stable_hash(base)

    def _fire_internal(self, pending):
        # Preserve the pre-jump structural state for the continuous segment.
        pre_graph = self.graph.clone()
        occurrence = pending.occurrence
        record = super()._fire_internal(pending)

        # super() has committed the structural rewrite.  Now atomically commit
        # the corresponding continuous segment and jump, then rebuild hazards.
        liquid_info = self.field.commit_event(
            record.post_time,
            pre_graph,
            self.graph,
            occurrence.rule.rule_id,
            occurrence.match,
        )
        self._refresh_occurrences(force=True, state_changed=True)
        record.cause["liquid_field"] = self.field.name
        record.cause["liquid_jump"] = liquid_info
        record.cause["neural_hazard_bound_certified"] = occurrence.rule.rule_id in NEURAL_RULES
        record.post_state_hash = self.state_hash
        self.liquid_audit.append({
            "event_index": record.event_index,
            "time": record.post_time,
            "rule": occurrence.rule.rule_id,
            "state_hash": record.post_state_hash,
            "liquid": self.field.canonical_at(record.post_time, self.graph),
        })
        return record

    def snapshot_hybrid(self) -> HybridSnapshot:
        return HybridSnapshot(self.snapshot(), copy.deepcopy(self.field.snapshot()))

    def restore_hybrid(self, snap: HybridSnapshot) -> None:
        # In-place restoration is useful for deterministic branch tests.
        restored = Runtime.from_snapshot(self.model_from_current(), snap.base, config=self.config)
        # Copy authoritative base runtime fields.  This intentionally avoids
        # replacing self.field, whose class/model object is experiment-owned.
        for name in (
            "graph","boundary","rules","parameters","memory","time","last_event_time","event_index",
            "external_queue","adaptation_queue","meta_queue","pending_internal","output_events","run_id",
            "thinning_audit","random",
        ):
            if hasattr(restored,name):
                setattr(self,name,copy.deepcopy(getattr(restored,name)))
        self.field.restore(snap.field)
        self.occurrence_index.clear(); self._indexed_augmented_hash=None

    def model_from_current(self) -> Model:
        return Model(
            self.graph.clone(), self.boundary.clone(), tuple(copy.deepcopy(list(self.rules.values()))),
            parameters=copy.deepcopy(self.parameters), memory=copy.deepcopy(self.memory),
            model_id="hybrid-snapshot-model", version="1.0.0",
        )
