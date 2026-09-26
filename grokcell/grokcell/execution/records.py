"""Versioned values for the provisional execution contract; no authority by shape."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import ClassVar

SCHEMA_VERSION = 1
MAX_VALUE_BYTES = 131_072


class Versioned:
    __slots__ = ()
    schema_version: ClassVar[int] = SCHEMA_VERSION


def _json_value(value: object, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("JSON nesting limit")
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("JSON object keys must be strings")
            _json_value(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _json_value(item, depth + 1)
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite JSON number")
    elif value is not None and type(value) not in (str, int, bool):
        raise TypeError("unsupported JSON value")


def canonical(value: object) -> bytes:
    _json_value(value)
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_VALUE_BYTES:
        raise ValueError("JSON byte limit")
    return raw


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def integer(value: int, *, positive: bool = False) -> None:
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError("expected positive integer" if positive else "expected nonnegative integer")


def text(value: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ValueError("expected nonempty bounded string")


@dataclass(frozen=True, slots=True)
class JsonSnapshot(Versioned):
    """Canonical bytes own the value; decoded dictionaries are detached copies."""
    raw: bytes
    schema_version: ClassVar[int] = SCHEMA_VERSION

    def __post_init__(self):
        if type(self.raw) is not bytes or len(self.raw) > MAX_VALUE_BYTES:
            raise ValueError("invalid JSON snapshot")
        if canonical(json.loads(self.raw)) != self.raw:
            raise ValueError("snapshot must contain canonical JSON")

    @classmethod
    def capture(cls, value: object) -> JsonSnapshot:
        return cls(canonical(value))

    def value(self):
        return json.loads(self.raw)

    @property
    def identity(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


@dataclass(frozen=True, slots=True)
class Observation(Versioned):
    value: JsonSnapshot
    dependency_hash: str
    state_revision: int

    @property
    def identity(self):
        return digest([SCHEMA_VERSION, self.value.identity, self.dependency_hash, self.state_revision])


@dataclass(frozen=True, slots=True)
class ActionOffer(Versioned):
    id: str
    effect: str
    target: str

    def __post_init__(self):
        for value in (self.id, self.effect, self.target):
            text(value)


@dataclass(frozen=True, slots=True)
class Decision(Versioned):
    observation_hash: str
    offers_hash: str
    choice: ActionOffer
    adapter_id: str


@dataclass(frozen=True, slots=True)
class Candidate(Versioned):
    artifact_type: str
    content: bytes
    dependency_hash: str
    base_revision: int
    attempt_id: str

    def __post_init__(self):
        text(self.artifact_type)
        text(self.attempt_id)
        integer(self.base_revision)
        if type(self.content) is not bytes or not self.content or len(self.content) > MAX_VALUE_BYTES:
            raise ValueError("candidate bytes required within size limit")

    @property
    def identity(self):
        return digest([SCHEMA_VERSION, self.artifact_type, hashlib.sha256(self.content).hexdigest(),
                       self.dependency_hash, self.base_revision, self.attempt_id])


@dataclass(frozen=True, slots=True)
class CheckResult(Versioned):
    id: str
    status: str

    def __post_init__(self):
        text(self.id)
        if self.status not in ("pass", "fail", "unknown"):
            raise ValueError("invalid check status")


@dataclass(frozen=True, slots=True)
class Evidence(Versioned):
    candidate_hash: str
    contract_hash: str
    checker_id: str
    environment_hash: str
    checks: tuple[CheckResult, ...]

    def __post_init__(self):
        object.__setattr__(self, "checks", tuple(self.checks))
        if any(type(item) is not CheckResult for item in self.checks):
            raise TypeError("check records required")

    @property
    def identity(self):
        return digest([SCHEMA_VERSION, self.candidate_hash, self.contract_hash, self.checker_id,
                       self.environment_hash, [[x.id, x.status] for x in self.checks]])


@dataclass(frozen=True, slots=True)
class Permission(Versioned):
    """Operator input to the preview harness, not a bearer capability or signature."""
    id: str
    subject: str
    effects: tuple[str, ...]
    expires_at: float
    epoch: int = 0

    def __post_init__(self):
        text(self.id)
        text(self.subject)
        integer(self.epoch)
        object.__setattr__(self, "effects", tuple(self.effects))
        for effect in self.effects:
            text(effect)
        if len(set(self.effects)) != len(self.effects) or not self.effects:
            raise ValueError("unique nonempty permission effects required")
        if type(self.expires_at) not in (int, float) or not math.isfinite(self.expires_at):
            raise ValueError("finite expiry required")


@dataclass(frozen=True, slots=True)
class AcceptedState(Versioned):
    """Preview receipt only. Never a GrokCell artifact license or deployment grant."""
    revision: int
    candidate_hash: str
    evidence_hash: str
    dependency_hash: str
    assurance: str = "offline_preview"

    def __post_init__(self):
        integer(self.revision, positive=True)
        if self.assurance not in ("offline_preview", "isolated_contract_checked", "data_contract_checked"):
            raise ValueError("unsupported receipt assurance")


@dataclass(frozen=True, slots=True)
class Limits(Versioned):
    max_steps: int = 64
    max_calls: int = 4
    max_bytes: int = 65_536
    max_microusd: int = 1_000_000
    max_seconds: int = 30

    def __post_init__(self):
        for value in (self.max_steps, self.max_calls, self.max_bytes,
                      self.max_microusd, self.max_seconds):
            integer(value, positive=True)
