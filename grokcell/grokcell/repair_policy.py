"""Deterministic legal actions for the repair probe."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

ACTIONS = {"REPAIR_COMPONENT", "ESCALATE"}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Candidate:
    action: str
    target: str
    state_hash: str


@dataclass(frozen=True)
class DecisionState:
    manifest: dict[str, str]
    observations: tuple[dict, ...]
    attempts: tuple[dict, ...]
    remaining_calls: int
    remaining_output_tokens: int
    remaining_attempts: int
    infrastructure_ready: bool

    def fingerprint(self) -> str:
        return digest(asdict(self))


def legal_candidates(state: DecisionState) -> list[Candidate]:
    stamp = state.fingerprint()
    candidates = []
    if state.infrastructure_ready and state.remaining_attempts > 0:
        failing = sorted({str(item.get("component")) for item in state.observations
                          if item.get("status") == "tests_failed" and item.get("component")})
        uncertain = any(item.get("status") in {"unknown", "contradictory"}
                        for item in state.observations)
        if (not uncertain and state.remaining_calls >= 1
                and state.remaining_output_tokens >= 2048):
            for target in failing:
                prior = [item for item in state.attempts if item.get("target") == target
                         and item.get("action") == "REPAIR_COMPONENT"]
                if len(prior) < 2:
                    candidates.append(Candidate("REPAIR_COMPONENT", target, stamp))
    candidates.append(Candidate("ESCALATE", "task", stamp))
    return candidates


def validate_choice(state: DecisionState, chosen: Candidate) -> bool:
    if chosen.action not in ACTIONS or chosen.state_hash != state.fingerprint():
        return False
    return chosen in legal_candidates(state)


def deterministic_choice(candidates: list[Candidate]) -> Candidate:
    for action in ("REPAIR_COMPONENT", "ESCALATE"):
        for candidate in candidates:
            if candidate.action == action:
                return candidate
    raise ValueError("no legal action")
