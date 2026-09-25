"""Deterministic limits and concrete next-action choices for the repair probe."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

ACTIONS = {"INVESTIGATE", "REPAIR_COMPONENT", "REIMPLEMENT_COMPONENT",
           "RETRIEVE_EVIDENCE", "ESCALATE"}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Candidate:
    id: str
    action: str
    target: str
    operation: str
    evidence_ids: tuple[str, ...]
    model_calls: int
    output_tokens: int
    state_hash: str

    def to_choice(self) -> dict:
        return {"id": self.id, "description": (
            f"{self.action} {self.target}: {self.operation}; evidence={list(self.evidence_ids)}; "
            f"reserve {self.model_calls} model call(s), {self.output_tokens} output tokens")}


@dataclass(frozen=True)
class DecisionState:
    manifest: dict[str, str]
    observations: tuple[dict, ...]
    attempts: tuple[dict, ...]
    evidence_ids: tuple[str, ...]
    remaining_calls: int
    remaining_output_tokens: int
    remaining_attempts: int
    remaining_retrievals: int
    infrastructure_ready: bool
    routing_calls: int = 0
    routing_tokens: int = 0
    retrieval_enabled: bool = False

    def fingerprint(self) -> str:
        return digest(asdict(self))


def legal_candidates(state: DecisionState) -> list[Candidate]:
    stamp = state.fingerprint()
    specs: list[tuple[str, str, str, int, int]] = []
    if not state.infrastructure_ready or state.remaining_attempts <= 0:
        specs.append(("ESCALATE", "task", "record infrastructure or limit blocker", 0, 0))
    else:
        failing = sorted({str(item.get("component")) for item in state.observations
                          if item.get("status") == "tests_failed" and item.get("component")})
        uncertain = any(item.get("status") in {"unknown", "contradictory"}
                        for item in state.observations)
        if uncertain or not failing:
            specs.append(("INVESTIGATE", "task", "run bounded public diagnostic", 0, 0))
        if (not uncertain and state.remaining_calls >= 1 + state.routing_calls
                and state.remaining_output_tokens >= 2048 + state.routing_tokens):
            for target in failing:
                prior = [item for item in state.attempts if item.get("target") == target
                         and item.get("action") in {"REPAIR_COMPONENT", "REIMPLEMENT_COMPONENT"}]
                if len(prior) < 2:
                    action = "REIMPLEMENT_COMPONENT" if prior else "REPAIR_COMPONENT"
                    specs.append((action, target, "propose service.py and public candidate tests", 1, 2048))
        if (state.retrieval_enabled and failing and state.evidence_ids
                and state.remaining_retrievals > 0):
            specs.append(("RETRIEVE_EVIDENCE", "task", "read bounded canonical prior attempts", 0, 0))
        specs.append(("ESCALATE", "task", "stop with observed evidence", 0, 0))
    return [Candidate(f"a{index}", action, target, operation, state.evidence_ids[:5],
                      calls, tokens, stamp)
            for index, (action, target, operation, calls, tokens) in enumerate(specs)]


def validate_choice(state: DecisionState, chosen: Candidate) -> bool:
    if chosen.action not in ACTIONS or chosen.state_hash != state.fingerprint():
        return False
    return chosen in legal_candidates(state)


def deterministic_choice(candidates: list[Candidate]) -> Candidate:
    for action in ("REPAIR_COMPONENT", "REIMPLEMENT_COMPONENT", "INVESTIGATE",
                   "RETRIEVE_EVIDENCE", "ESCALATE"):
        for candidate in candidates:
            if candidate.action == action:
                return candidate
    raise ValueError("no legal action")


def select_action(state: DecisionState, policy: str, chooser=None) -> tuple[Candidate, dict]:
    candidates = legal_candidates(state)
    fallback = deterministic_choice(candidates)
    if policy == "deterministic":
        return fallback, {"source": "deterministic", "fallback": False}
    productive = [item for item in candidates if item.action != "ESCALATE"]
    if len(productive) <= 1:
        return fallback, {"source": "deterministic", "fallback": False,
                          "reason": ("single_productive_action" if productive
                                     else "no_productive_action")}
    if policy not in {"jev", "qwen"} or chooser is None:
        raise ValueError("invalid routing policy")
    reply = None
    try:
        reply = chooser.choose(
            state={"manifest": state.manifest, "observations": state.observations[-4:],
                   "attempts": state.attempts[-3:], "remaining_calls": state.remaining_calls,
                   "remaining_output_tokens": state.remaining_output_tokens},
            candidates=[item.to_choice() for item in candidates],
        )
        choice = next(item for item in candidates if item.id == reply.value)
        if policy == "jev" and reply.confidence < chooser.min_confidence:
            raise ValueError("jev_low_confidence")
        if not validate_choice(state, choice):
            raise ValueError("stale_or_invalid_choice")
        return choice, {"source": policy, "fallback": False,
                        **_reply_evidence(reply)}
    except (RuntimeError, ValueError, StopIteration, TypeError) as exc:
        return fallback, {"source": policy, "fallback": True, "reason": str(exc),
                          **(_reply_evidence(reply) if reply is not None else {})}


def _reply_evidence(reply) -> dict:
    return {"model": reply.model, "usage": reply.usage,
            "elapsed_ms": reply.elapsed_ms, "request_id": reply.request_id,
            "revision": getattr(reply, "revision", None),
            "confidence": reply.confidence,
            "probabilities": reply.probabilities}
