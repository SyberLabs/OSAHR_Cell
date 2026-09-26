"""Typed data shared by the hosted PostgreSQL store and restore verifier."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping

from osahr.canonical import stable_hash

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HostedStoreError(RuntimeError):
    """Base error for rejected hosted state transitions."""


class StaleFence(HostedStoreError):
    pass


class IdempotencyConflict(HostedStoreError):
    pass


class AttemptBlocked(HostedStoreError):
    pass


class BudgetExceeded(HostedStoreError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectRef:
    key: str
    version_id: str
    sha256: str

    def validate(self) -> None:
        path = PurePosixPath(self.key)
        if (
            not self.key
            or "\\" in self.key
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or not self.version_id
            or self.version_id == "null"
            or not _SHA256.fullmatch(self.sha256)
        ):
            raise ValueError("invalid immutable object reference")


@dataclass(frozen=True, slots=True)
class Attempt:
    admission_id: uuid.UUID
    attempt_id: uuid.UUID
    owner_id: str
    cell_id: str
    idempotency_key: str
    request_sha256: str
    expected_revision: int
    fence: int
    reserved_units: int
    status: str
    dispatch_allowed: bool


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    admission_id: uuid.UUID
    attempt_id: uuid.UUID
    cell_id: str
    revision: int
    state_sha256: str
    manifest: ObjectRef


@dataclass(frozen=True, slots=True)
class CellHead:
    cell_id: str
    owner_id: str
    revision: int
    fence: int
    lease_owner: str | None
    admitted_state_sha256: str
    initial_event_index: int
    last_event_index: int
    initial_checkpoint: ObjectRef
    checkpoint: ObjectRef
    initial_manifest: ObjectRef
    manifest: ObjectRef


@dataclass(frozen=True, slots=True)
class AdmissionSegment:
    revision: int
    admission_id: uuid.UUID
    first_event_index: int
    last_event_index: int
    pre_state_sha256: str
    post_state_sha256: str
    checkpoint: ObjectRef
    event_segment: ObjectRef
    manifest: ObjectRef
    previous_manifest_sha256: str


def request_digest(
    *, owner_id: str, cell_id: str, operation: str, expected_revision: int,
    reserve_units: int, request: Mapping[str, Any],
) -> str:
    """Hash every request value that changes authorization or charged work."""
    return stable_hash(
        {
            "owner_id": owner_id,
            "cell_id": cell_id,
            "operation": operation,
            "expected_revision": expected_revision,
            "reserve_units": reserve_units,
            "request": dict(request),
        }
    )
