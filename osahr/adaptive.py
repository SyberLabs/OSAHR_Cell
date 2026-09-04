"""First-class adaptive parameter contracts and reusable learning primitives."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .canonical import canonical_equal
from .errors import AdaptationError
from .expr import get_path, set_path


class ParameterScope(str, Enum):
    GLOBAL = "global"
    RULE = "rule"
    TYPE = "type"
    ENTITY = "entity"
    BOUNDARY = "boundary"


class ParameterConstraint(str, Enum):
    FREE = "free"
    POSITIVE = "positive"
    NONNEGATIVE = "nonnegative"
    BOUNDED = "bounded"
    PROBABILITY = "probability"


class ConstraintPolicy(str, Enum):
    STRICT = "strict"
    PROJECT = "project"


@dataclass(frozen=True, slots=True)
class AdaptiveParameter:
    """Declares a mutable model parameter and its admissible state space.

    `path` addresses the runtime ``parameters`` mapping.  The representation is
    always the actual model value (not an unconstrained latent); a transform can
    be layered above this API by a learner if desired.  STRICT constraints make
    semantic errors fail atomically.  PROJECT explicitly changes the adaptive
    law by clipping/projecting and is therefore encoded in the model hash.
    """

    path: str
    scope: ParameterScope = ParameterScope.GLOBAL
    constraint: ParameterConstraint = ParameterConstraint.FREE
    policy: ConstraintPolicy = ConstraintPolicy.STRICT
    lower: float | None = None
    upper: float | None = None
    owner: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.path or any(not part for part in self.path.split(".")):
            raise AdaptationError(f"Invalid adaptive parameter path {self.path!r}")
        if self.constraint is ParameterConstraint.BOUNDED:
            if self.lower is None or self.upper is None or self.lower > self.upper:
                raise AdaptationError("Bounded parameters require lower <= upper")
        if self.constraint is ParameterConstraint.PROBABILITY:
            if self.lower is not None or self.upper is not None:
                raise AdaptationError("Probability bounds are fixed to [0, 1]")
        if self.scope is not ParameterScope.GLOBAL and self.owner is None:
            raise AdaptationError(f"Scope {self.scope.value} requires an owner")

    def _numeric(self, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AdaptationError(f"Adaptive parameter {self.path!r} must be numeric")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise AdaptationError(f"Adaptive parameter {self.path!r} must be finite")
        return numeric

    def valid(self, value: Any) -> bool:
        if self.constraint is ParameterConstraint.FREE:
            return True
        try:
            numeric = self._numeric(value)
        except AdaptationError:
            return False
        if self.constraint is ParameterConstraint.POSITIVE:
            return numeric > 0.0
        if self.constraint is ParameterConstraint.NONNEGATIVE:
            return numeric >= 0.0
        if self.constraint is ParameterConstraint.BOUNDED:
            assert self.lower is not None and self.upper is not None
            return self.lower <= numeric <= self.upper
        if self.constraint is ParameterConstraint.PROBABILITY:
            return 0.0 <= numeric <= 1.0
        return True

    def normalize(self, value: Any) -> Any:
        if self.valid(value):
            return value
        if self.policy is ConstraintPolicy.STRICT:
            raise AdaptationError(
                f"Adaptive update violates {self.constraint.value} constraint for {self.path!r}: {value!r}"
            )
        numeric = self._numeric(value)
        if self.constraint is ParameterConstraint.POSITIVE:
            # Projection onto an open set has no nearest point.  Use the smallest
            # positive normal number as an explicit deterministic convention.
            return max(numeric, float.fromhex("0x1.0p-1022"))
        if self.constraint is ParameterConstraint.NONNEGATIVE:
            return max(0.0, numeric)
        if self.constraint is ParameterConstraint.BOUNDED:
            assert self.lower is not None and self.upper is not None
            return min(max(numeric, self.lower), self.upper)
        if self.constraint is ParameterConstraint.PROBABILITY:
            return min(max(numeric, 0.0), 1.0)
        return value


class AdaptiveRegistry:
    def __init__(self, specs: tuple[AdaptiveParameter, ...] = ()) -> None:
        paths = [spec.path for spec in specs]
        if len(paths) != len(set(paths)):
            raise AdaptationError("Duplicate adaptive parameter paths")
        self.specs = {spec.path: spec for spec in specs}

    def validate(self, parameters: Mapping[str, Any]) -> None:
        for path, spec in self.specs.items():
            try:
                value = get_path(parameters, path)
            except Exception as exc:
                raise AdaptationError(f"Missing adaptive parameter {path!r}") from exc
            if not spec.valid(value):
                raise AdaptationError(
                    f"Initial value {value!r} violates {spec.constraint.value} for {path!r}"
                )

    def normalize(self, parameters: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(parameters)
        for path, spec in self.specs.items():
            try:
                value = get_path(result, path)
            except Exception as exc:
                raise AdaptationError(f"Missing adaptive parameter {path!r}") from exc
            set_path(result, path, spec.normalize(value))
        return result

    def changed_paths(self, before: Mapping[str, Any], after: Mapping[str, Any]) -> frozenset[str]:
        changed: set[str] = set()
        for path in self.specs:
            try:
                if not canonical_equal(get_path(before, path), get_path(after, path)):
                    changed.add(path)
            except Exception:
                changed.add(path)
        return frozenset(changed)


@dataclass(frozen=True, slots=True)
class ExponentialTrace:
    """Pure sufficient-statistic primitive: z'=(1-alpha)z+alpha*x."""

    alpha: float

    def __post_init__(self) -> None:
        if not (0.0 < self.alpha <= 1.0):
            raise AdaptationError("alpha must lie in (0, 1]")

    def update(self, previous: float, observation: float) -> float:
        return (1.0 - self.alpha) * previous + self.alpha * observation


@dataclass(frozen=True, slots=True)
class EligibilityTrace:
    """Event-time exponential eligibility trace.

    Between events the trace decays as exp(-dt/tau); an event then adds impulse.
    Keeping the trace in runtime memory makes the augmented state Markov.
    """

    tau: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.tau) or self.tau <= 0.0:
            raise AdaptationError("tau must be finite and positive")

    def update(self, previous: float, delta_time: float, impulse: float = 1.0) -> float:
        if delta_time < 0.0:
            raise AdaptationError("delta_time cannot be negative")
        return previous * math.exp(-delta_time / self.tau) + impulse


@dataclass(frozen=True, slots=True)
class RobbinsMonro:
    """Pure stochastic-approximation primitive theta' = theta + eta * error."""

    learning_rate: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0.0:
            raise AdaptationError("learning_rate must be finite and positive")

    def update(self, value: float, error: float) -> float:
        return value + self.learning_rate * error
