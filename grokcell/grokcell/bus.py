"""Priority bus with vault constraints. Legality outranks priority."""
from __future__ import annotations

from .fidelity import FidelityStore
from .messages import DrainItem, Message
from .runner import current_suite_hash
from .vault import ConstraintVault


def classify(
    message: Message,
    *,
    components: list[str],
    owners: list[str],
    vault: ConstraintVault,
    fidelity: FidelityStore,
) -> tuple[str, str]:
    if message.kind == "oda.spawn":
        name = str(message.payload.get("bot_name") or "").strip()
        if not name:
            return "outcome_unknown", "missing_name"
        if name in owners:
            return "reject", "duplicate_owner"
        return "admit", "owner_registered"
    if message.kind == "oda.attach_skill":
        return "reject", "use_oda_attach_skill_tool"
    if message.kind != "forge.propose":
        return "outcome_unknown", "unsupported_kind"
    payload = message.payload
    constraint = str(payload.get("constraint") or "")
    if constraint not in vault.concepts:
        return "outcome_unknown", "unknown_constraint"
    concept = vault.concepts[constraint]
    name = str(payload.get("name") or "")
    if not name:
        return "outcome_unknown", "missing_name"
    if concept.requires_fidelity:
        ok, reason = fidelity.check(name, expected_hash=current_suite_hash(name))
        if not ok:
            return "reject", reason
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
