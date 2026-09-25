"""Trusted-host adapter seams. Implementations never receive the runtime itself."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .records import ActionOffer, Candidate, CheckResult, JsonSnapshot, Observation, integer, text


@dataclass(frozen=True, slots=True)
class Reply:
    value: str | bytes
    actual_microusd: int | None = 0

    def __post_init__(self):
        if type(self.value) not in (str, bytes):
            raise TypeError("adapter reply must be text or bytes")
        if self.actual_microusd is not None:
            integer(self.actual_microusd)


class DecisionAdapter(Protocol):
    id: str
    mode: str

    def choose(self, observation: Observation, offers: tuple[ActionOffer, ...]) -> Reply: ...


class WorkerAdapter(Protocol):
    id: str
    mode: str

    def propose(self, request: JsonSnapshot) -> Reply: ...


@dataclass(frozen=True, slots=True)
class CheckContract:
    id: str
    checker_id: str
    environment_hash: str
    required: tuple[str, ...]

    def __post_init__(self):
        for value in (self.id, self.checker_id, self.environment_hash):
            text(value)
        object.__setattr__(self, "required", tuple(self.required))
        if not self.required or len(set(self.required)) != len(self.required):
            raise ValueError("nonempty unique mandatory checks required")
        for name in self.required:
            text(name)


class Verifier(Protocol):
    contract: CheckContract
    mode: str

    def verify(self, candidate: Candidate) -> tuple[CheckResult, ...]: ...
