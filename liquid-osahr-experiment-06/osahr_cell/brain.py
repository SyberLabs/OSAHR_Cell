"""v1 NetworkBrain: one deterministic mouth. No language-model import."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from osahr.runtime import EnabledOccurrence

from .claims_bridge import ClaimStatus
from .junction import is_junction, vault_legal_occurrences
from .protocol import BRAIN_VERSION, JUNCTION_RULE_ID
from .vault import SemanticVault

Action = Literal["kernel", "select", "withhold"]


class BrainAction(str, Enum):
    KERNEL = "kernel"
    SELECT = "select"
    WITHHOLD = "withhold"


@dataclass(frozen=True)
class BrainDecision:
    action: BrainAction
    status: ClaimStatus
    reason: str
    rule_id: str | None = None
    match_id: str | None = None
    load_penalty: float | None = None
    version: str = BRAIN_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "status": self.status,
            "reason": self.reason,
            "rule_id": self.rule_id,
            "match_id": self.match_id,
            "load_penalty": self.load_penalty,
            "version": self.version,
        }


def _load_penalty(occurrence: EnabledOccurrence) -> float:
    load = float(occurrence.match.bindings.get("load", 0))
    capacity = float(occurrence.match.bindings.get("capacity", 1) or 1)
    return load / max(capacity, 1.0)


def decide(
    status: ClaimStatus,
    occurrences: list[EnabledOccurrence],
    vault: SemanticVault,
    *,
    outage: bool,
    scenario: int | None = None,
) -> BrainDecision:
    """Junction law from Experiment 05.

    admit: kernel fires the (unique) legal match; Brain is idle.
    hold_unresolved: pick among vault-legal matches by frozen load penalty.
    reject / outcome_unknown: withhold. Park must refuse a commit.
    """
    legal = vault_legal_occurrences(occurrences, vault, outage=outage)
    if status == "admit":
        unique = legal[0] if len(legal) == 1 else None
        return BrainDecision(
            BrainAction.KERNEL,
            status,
            "admit: Brain idle; kernel fires the legal match",
            rule_id=JUNCTION_RULE_ID if unique is not None else None,
            match_id=None if unique is None else unique.match.match_id,
        )
    if status in ("reject", "outcome_unknown"):
        reason = f"{status}: withhold rewrite; record a claim note"
        if scenario is not None:
            vault.record_claim_note(scenario=scenario, status=status, reason=reason)
        return BrainDecision(BrainAction.WITHHOLD, status, reason)
    if status != "hold_unresolved":
        raise ValueError(f"unknown claim status {status!r}")
    if not legal:
        reason = "hold_unresolved but no vault-legal route-task match"
        if scenario is not None:
            vault.record_claim_note(scenario=scenario, status=status, reason=reason)
        return BrainDecision(BrainAction.WITHHOLD, status, reason)
    chosen = min(
        legal,
        key=lambda item: (_load_penalty(item), item.match.match_id),
    )
    return BrainDecision(
        BrainAction.SELECT,
        status,
        "hold_unresolved: select vault-legal match by load penalty",
        rule_id=chosen.rule.rule_id,
        match_id=chosen.match.match_id,
        load_penalty=_load_penalty(chosen),
    )


def assert_no_llm_import(source: str) -> None:
    forbidden = (
        "openai",
        "anthropic",
        "transformers",
        "langchain",
        "llama",
        "grok",
        "litellm",
    )
    lowered = source.lower()
    for name in forbidden:
        if f"import {name}" in lowered or f"from {name}" in lowered:
            raise AssertionError(f"v1 Brain must not import {name}")
