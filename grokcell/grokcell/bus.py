"""Priority bus with vault constraints. Legality outranks priority."""
from __future__ import annotations

import tempfile
from pathlib import Path

from .artifact import Artifact, resolve_artifact, stage_artifact
from .fidelity import FidelityStore
from .messages import DrainItem, Message
from .mutant import kill_mutant
from .runner import RunOutcome, pytest_suite, run_path, suite_hash
from .vault import ConstraintVault


def classify(
    message: Message,
    *,
    components: list[str],
    owners: list[str],
    vault: ConstraintVault,
    fidelity: FidelityStore,
) -> tuple[str, str, Artifact | None]:
    if str(message.source_owner or "").strip() not in owners:
        return "reject", "unknown_owner", None
    if message.kind == "oda.spawn":
        name = str(message.payload.get("bot_name") or "").strip()
        if not name:
            return "outcome_unknown", "missing_name", None
        if name in owners:
            return "reject", "duplicate_owner", None
        return "admit", "owner_registered", None
    if message.kind == "oda.attach_skill":
        return "reject", "use_oda_attach_skill_tool", None
    if message.kind != "forge.propose":
        return "outcome_unknown", "unsupported_kind", None
    payload = message.payload
    constraint = str(payload.get("constraint") or "")
    if constraint not in vault.concepts:
        return "outcome_unknown", "unknown_constraint", None
    concept = vault.concepts[constraint]
    name = str(payload.get("name") or "")
    if not name:
        return "outcome_unknown", "missing_name", None
    artifact = resolve_artifact(payload)
    if artifact is None:
        return "outcome_unknown", "missing_artifact", None
    if name in components:
        return "reject", "duplicate_component", None
    missing = [
        str(dep)
        for dep in (payload.get("depends_on") or [])
        if str(dep) not in components
    ]
    if missing:
        return "hold_unresolved", "missing_dependency", None
    expected_hash = artifact.digest()
    with tempfile.TemporaryDirectory(prefix="grokcell-stage-") as raw:
        staged = stage_artifact(artifact, Path(raw))
        if suite_hash(staged) != expected_hash:
            return "reject", "artifact_stage_mismatch", None
        if artifact.source == "payload":
            record = run_path(name, staged, store=fidelity, untrusted=True)
            baseline_outcome = RunOutcome(record.outcome)
        else:
            baseline_outcome = pytest_suite(staged).outcome
        if baseline_outcome is RunOutcome.SANDBOX_REQUIRED:
            return "reject", "runner_sandbox_required", None
        if baseline_outcome is RunOutcome.TIMEOUT:
            return "reject", "runner_timeout", None
        if baseline_outcome is RunOutcome.INFRA_ERROR:
            return "reject", "runner_infrastructure", None
        if baseline_outcome is not RunOutcome.PASS:
            return "reject", "runner_failed", None
        if suite_hash(staged) != expected_hash:
            return "reject", "runner_modified_artifact", None
        if concept.requires_fidelity:
            ok, reason = fidelity.check(name, expected_hash=expected_hash)
            if not ok:
                return "reject", reason, None
        killed, mutant_reason = kill_mutant(
            staged,
            untrusted=artifact.source == "payload",
        )
        if not killed:
            return "reject", mutant_reason, None
    return "admit", "vault_legal", artifact


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
