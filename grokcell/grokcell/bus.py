"""Priority bus with vault constraints. Legality outranks priority."""
from __future__ import annotations

from .messages import DrainItem, Message
from .vault import ConstraintVault


def classify(
    message: Message,
    *,
    components: list[str],
    vault: ConstraintVault,
) -> tuple[str, str]:
    if message.kind == "oda.spawn":
        return "reject", "oda_spawn_lock"
    if message.kind == "oda.attach_skill":
        return "reject", "use_oda_attach_skill_tool"
    if message.kind != "forge.propose":
        return "outcome_unknown", "unsupported_kind"
    payload = message.payload
    constraint = str(payload.get("constraint") or "")
    if constraint not in vault.concepts:
        return "outcome_unknown", "unknown_constraint"
    concept = vault.concepts[constraint]
    verified = bool(payload.get("verified", False))
    if concept.requires_fidelity and not verified:
        return "reject", "unverified_critical"
    if "unverified" in concept.excludes and not verified:
        return "reject", "unverified_excluded"
    name = str(payload.get("name") or "")
    if not name:
        return "outcome_unknown", "missing_name"
    if name in components:
        return "reject", "duplicate_component"
    missing = [
        str(dep)
        for dep in (payload.get("depends_on") or [])
        if str(dep) not in components
    ]
    if missing:
        return "hold_unresolved", "missing_dependency"
    return "admit", "vault_legal"


def drain_order(messages: list[Message]) -> list[Message]:
    return sorted(messages, key=lambda item: (-int(item.priority), int(item.seq)))


def as_item(message: Message, status: str, reason: str) -> DrainItem:
    return DrainItem(
        message_id=message.message_id,
        kind=message.kind,
        status=status,
        reason=reason,
        priority=message.priority,
    )
