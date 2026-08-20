"""Safe, finite meta-rewriting of the transition repertoire.

Meta-rewriting never compiles arbitrary source during a run. A RuleTemplate wraps
an already compiled Rule whose expressions may read typed values from ``meta``.
Instantiation changes only validated data bindings and the stable rule identity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping

from .errors import MetaRewriteError
from .pattern import Rule


class MetaValueKind(str, Enum):
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    STRING = "string"


@dataclass(frozen=True, slots=True)
class MetaParameter:
    name: str
    kind: MetaValueKind
    required: bool = True
    default: Any = None
    lower: float | None = None
    upper: float | None = None
    choices: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise MetaRewriteError(f"Invalid meta parameter name {self.name!r}")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise MetaRewriteError("Meta parameter lower bound exceeds upper bound")
        if not self.required:
            self.validate(self.default)

    def validate(self, value: Any) -> Any:
        if self.kind is MetaValueKind.BOOL:
            if not isinstance(value, bool):
                raise MetaRewriteError(f"Meta parameter {self.name!r} expects bool")
        elif self.kind is MetaValueKind.INT:
            if isinstance(value, bool) or not isinstance(value, int):
                raise MetaRewriteError(f"Meta parameter {self.name!r} expects int")
        elif self.kind is MetaValueKind.FLOAT:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise MetaRewriteError(f"Meta parameter {self.name!r} expects float")
            value = float(value)
            if not math.isfinite(value):
                raise MetaRewriteError(f"Meta parameter {self.name!r} must be finite")
        elif self.kind is MetaValueKind.STRING:
            if not isinstance(value, str):
                raise MetaRewriteError(f"Meta parameter {self.name!r} expects string")
        if self.choices and value not in self.choices:
            raise MetaRewriteError(
                f"Meta parameter {self.name!r} must be one of {self.choices!r}"
            )
        if self.lower is not None and float(value) < self.lower:
            raise MetaRewriteError(f"Meta parameter {self.name!r} is below lower bound")
        if self.upper is not None and float(value) > self.upper:
            raise MetaRewriteError(f"Meta parameter {self.name!r} is above upper bound")
        return value


@dataclass(frozen=True, slots=True)
class RuleTemplate:
    template_id: str
    prototype: Rule
    parameters: tuple[MetaParameter, ...] = ()
    max_instances: int = 10_000
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        names = [item.name for item in self.parameters]
        if len(names) != len(set(names)):
            raise MetaRewriteError("Duplicate meta template parameters")
        if self.max_instances <= 0:
            raise MetaRewriteError("max_instances must be positive")

    @property
    def parameter_map(self) -> dict[str, MetaParameter]:
        return {item.name: item for item in self.parameters}

    def instantiate(self, instance_id: str, bindings: Mapping[str, Any]) -> Rule:
        if not instance_id:
            raise MetaRewriteError("Rule instance ID cannot be empty")
        specs = self.parameter_map
        unknown = set(bindings) - set(specs)
        if unknown:
            raise MetaRewriteError(f"Unknown meta bindings: {sorted(unknown)!r}")
        resolved: dict[str, Any] = {}
        for name, spec in specs.items():
            if name in bindings:
                resolved[name] = spec.validate(bindings[name])
            elif spec.required:
                raise MetaRewriteError(f"Missing required meta binding {name!r}")
            else:
                resolved[name] = spec.validate(spec.default)
        meta = dict(self.prototype.meta)
        meta.update(resolved)
        return replace(
            self.prototype,
            rule_id=instance_id,
            version=f"{self.version}+instance",
            meta=meta,
        )


class MetaRuleAction(str, Enum):
    INSTANTIATE = "instantiate"
    ENABLE = "enable"
    DISABLE = "disable"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True, order=True)
class MetaRuleEvent:
    simulation_time: float
    source_sequence: int
    event_id: str = field(compare=False)
    action: MetaRuleAction = field(compare=False)
    rule_id: str = field(compare=False)
    template_id: str | None = field(default=None, compare=False)
    bindings: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if self.simulation_time < 0.0 or not math.isfinite(self.simulation_time):
            raise MetaRewriteError("Meta-rule event time must be finite and nonnegative")
        if self.action is MetaRuleAction.INSTANTIATE and self.template_id is None:
            raise MetaRewriteError("Instantiation requires template_id")
