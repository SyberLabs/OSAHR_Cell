"""Authoritative model identity and runtime resource contracts."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any

from .adaptive import AdaptiveParameter, AdaptiveRegistry
from .boundary import BoundaryState
from .canonical import stable_hash, validate_state_value
from .errors import ValidationError
from .graph import Hypergraph
from .meta import RuleTemplate
from .pattern import Rule
from .schedulers import SchedulerKind


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    max_events: int = 10_000_000
    max_vertices: int = 1_000_000
    max_edges: int = 1_000_000
    max_incidences: int = 10_000_000
    max_matches_per_rule: int = 5_000_000
    max_total_activity: float = 1e300
    max_simulation_time: float = math.inf
    max_events_per_time_window: int = 100_000
    explosion_window: float = 1e-12
    invalid_hazard_policy: str = "raise"  # raise | disable_occurrence

    scheduler: SchedulerKind | str = SchedulerKind.DIRECT_SSA
    matcher_backend: str = "incremental"  # incremental | reference
    incremental_verify: bool = False

    thinning_window: float = 1.0
    max_thinning_windows_per_plan: int = 100_000

    def __post_init__(self) -> None:
        positive_ints = {
            "max_events": self.max_events,
            "max_matches_per_rule": self.max_matches_per_rule,
            "max_events_per_time_window": self.max_events_per_time_window,
            "max_thinning_windows_per_plan": self.max_thinning_windows_per_plan,
        }
        nonnegative_ints = {
            "max_vertices": self.max_vertices,
            "max_edges": self.max_edges,
            "max_incidences": self.max_incidences,
        }
        for name, value in positive_ints.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name, value in nonnegative_ints.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            isinstance(self.max_total_activity, bool)
            or not isinstance(self.max_total_activity, (int, float))
            or not math.isfinite(self.max_total_activity)
            or self.max_total_activity < 0.0
        ):
            raise ValueError("max_total_activity must be finite and non-negative")
        if (
            isinstance(self.max_simulation_time, bool)
            or not isinstance(self.max_simulation_time, (int, float))
            or math.isnan(self.max_simulation_time)
            or self.max_simulation_time < 0.0
        ):
            raise ValueError("max_simulation_time must be non-negative and not NaN")
        if (
            isinstance(self.explosion_window, bool)
            or not isinstance(self.explosion_window, (int, float))
            or not math.isfinite(self.explosion_window)
            or self.explosion_window < 0.0
        ):
            raise ValueError("explosion_window must be finite and non-negative")
        if not isinstance(self.incremental_verify, bool):
            raise ValueError("incremental_verify must be boolean")
        if not isinstance(self.invalid_hazard_policy, str) or self.invalid_hazard_policy not in {
            "raise",
            "disable_occurrence",
        }:
            raise ValueError("invalid_hazard_policy must be raise or disable_occurrence")
        if not isinstance(self.matcher_backend, str) or self.matcher_backend not in {
            "incremental",
            "reference",
        }:
            raise ValueError("matcher_backend must be incremental or reference")
        try:
            SchedulerKind(self.scheduler)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unknown scheduler {self.scheduler!r}") from exc
        if (
            isinstance(self.thinning_window, bool)
            or not isinstance(self.thinning_window, (int, float))
            or not math.isfinite(self.thinning_window)
            or self.thinning_window <= 0.0
        ):
            raise ValueError("thinning_window must be finite and positive")

    @property
    def scheduler_kind(self) -> SchedulerKind:
        return SchedulerKind(self.scheduler)

    def to_canonical(self) -> dict[str, Any]:
        def canonical_number(value: int | float) -> int | float:
            # Preserve large integer limits exactly.  Integral floats are the
            # same contract as integers; non-integral floats are encoded by
            # canonicalize() with float.hex(), and signed zero becomes zero.
            if isinstance(value, int):
                return value
            if value == 0.0:
                return 0
            if value.is_integer():
                return int(value)
            return value

        simulation_limit: int | float | str = canonical_number(
            self.max_simulation_time
        )
        if math.isinf(self.max_simulation_time):
            simulation_limit = "infinity"
        return {
            "max_events": self.max_events,
            "max_vertices": self.max_vertices,
            "max_edges": self.max_edges,
            "max_incidences": self.max_incidences,
            "max_matches_per_rule": self.max_matches_per_rule,
            "max_total_activity": canonical_number(self.max_total_activity),
            "max_simulation_time": simulation_limit,
            "max_events_per_time_window": self.max_events_per_time_window,
            "explosion_window": canonical_number(self.explosion_window),
            "invalid_hazard_policy": self.invalid_hazard_policy,
            "scheduler": self.scheduler_kind.value,
            "matcher_backend": self.matcher_backend,
            "incremental_verify": self.incremental_verify,
            "thinning_window": canonical_number(self.thinning_window),
            "max_thinning_windows_per_plan": self.max_thinning_windows_per_plan,
        }


@dataclass(slots=True)
class Model:
    graph: Hypergraph
    boundary: BoundaryState
    rules: tuple[Rule, ...]
    parameters: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    model_id: str = "model"
    version: str = "1.0.0"
    adaptive_parameters: tuple[AdaptiveParameter, ...] = ()
    rule_templates: tuple[RuleTemplate, ...] = ()
    hash: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.graph, Hypergraph) or not isinstance(
            self.boundary, BoundaryState
        ):
            raise ValidationError("Model graph and boundary have invalid types")
        self.graph = copy.deepcopy(self.graph)
        self.boundary = copy.deepcopy(self.boundary)
        self.rules = tuple(copy.deepcopy(tuple(self.rules)))
        self.parameters = copy.deepcopy(self.parameters)
        self.memory = copy.deepcopy(self.memory)
        self.adaptive_parameters = tuple(copy.deepcopy(tuple(self.adaptive_parameters)))
        self.rule_templates = tuple(copy.deepcopy(tuple(self.rule_templates)))
        if not isinstance(self.parameters, dict) or not isinstance(self.memory, dict):
            raise ValidationError("Model parameters and memory must be dictionaries")
        try:
            if stable_hash(self.graph.schema.to_canonical()) != self.graph.schema.hash:
                raise ValidationError("Model schema hash is stale")
            self.graph.validate()
            validate_state_value(self.parameters)
            validate_state_value(self.memory)
            for rule in self.rules:
                if stable_hash(rule.to_canonical()) != rule.hash:
                    raise ValidationError(f"Rule {rule.rule_id!r} hash is stale")
            for template in self.rule_templates:
                if stable_hash(template.prototype.to_canonical()) != template.prototype.hash:
                    raise ValidationError(
                        f"Rule template {template.template_id!r} prototype hash is stale"
                    )
        except (TypeError, ValueError) as exc:
            raise ValidationError("Model contains non-canonical authoritative state") from exc
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValidationError("Duplicate rule IDs")
        template_ids = [template.template_id for template in self.rule_templates]
        if len(template_ids) != len(set(template_ids)):
            raise ValidationError("Duplicate rule template IDs")
        self.boundary.validate(set(self.graph.vertices))
        for handle in self.boundary.handles.values():
            if handle.binding is not None:
                vertex_type = self.graph.vertices[handle.binding].type_id
                if not self.graph.schema.is_vertex_compatible(vertex_type, handle.interface_type):
                    raise ValidationError(
                        f"Boundary {handle.handle_id!r} expects {handle.interface_type}, "
                        f"got {vertex_type}"
                    )
        AdaptiveRegistry(self.adaptive_parameters).validate(self.parameters)
        object.__setattr__(self, "hash", stable_hash(self.to_canonical()))

    def to_canonical(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "schema_hash": self.graph.schema.hash,
            "graph": self.graph.to_canonical(),
            "boundary": self.boundary.to_canonical(),
            "rules": [rule.hash for rule in sorted(self.rules, key=lambda item: item.rule_id)],
            "parameters": self.parameters,
            "memory": self.memory,
            "adaptive_parameters": self.adaptive_parameters,
            "rule_templates": [
                template.to_canonical()
                for template in sorted(self.rule_templates, key=lambda item: item.template_id)
            ],
        }
