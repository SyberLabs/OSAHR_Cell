"""Controller-only, head-bound checkpoint loading and admission replay.

The object reader must fetch an immutable object version. It is injected by the
trusted controller and is never selected by request payloads. This code verifies
integrity and replay; deployment IAM must still restrict who can create versions.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from osahr import Runtime, RuntimeConfig, load_checkpoint, save_checkpoint
from osahr.events import EventRecord
from osahr.model import Model
from osahr.runtime_state import RuntimeSnapshot

from .hosted_store import PostgresHostedStore
from .hosted_types import (
    AdmissionReceipt,
    Attempt,
    CellHead,
    HostedStoreError,
    ObjectRef,
)

MANIFEST_VERSION = 1


class ControllerObjectStore(Protocol):
    """Controller-only immutable storage capability.

    The deployment role must deny these methods to API, executor, and candidate
    roles. The coordinator creates every key; request payloads never select one.
    """

    def write_version(self, key: str, value: bytes) -> str: ...

    def read_version(self, key: str, version_id: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class VerifiedReplay:
    head: CellHead
    runtime: Runtime
    initial_snapshot: RuntimeSnapshot
    event_records: tuple[EventRecord, ...]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _ref_json(ref: ObjectRef) -> dict[str, str]:
    return {"key": ref.key, "version_id": ref.version_id, "sha256": ref.sha256}


def root_manifest_bytes(
    *, cell_id: str, state_sha256: str, event_index: int, checkpoint: ObjectRef
) -> bytes:
    return _json_bytes({
        "kind": "grokcell-cell-root",
        "version": MANIFEST_VERSION,
        "cell_id": cell_id,
        "state_sha256": state_sha256,
        "event_index": event_index,
        "checkpoint": _ref_json(checkpoint),
    })


def admission_manifest_bytes(
    *, cell_id: str, revision: int, admission_id: uuid.UUID,
    previous_manifest_sha256: str, pre_state_sha256: str,
    post_state_sha256: str, first_event_index: int, last_event_index: int,
    checkpoint: ObjectRef, event_segment: ObjectRef,
) -> bytes:
    return _json_bytes({
        "kind": "grokcell-admission",
        "version": MANIFEST_VERSION,
        "cell_id": cell_id,
        "revision": revision,
        "admission_id": str(admission_id),
        "previous_manifest_sha256": previous_manifest_sha256,
        "pre_state_sha256": pre_state_sha256,
        "post_state_sha256": post_state_sha256,
        "first_event_index": first_event_index,
        "last_event_index": last_event_index,
        "checkpoint": _ref_json(checkpoint),
        "event_segment": _ref_json(event_segment),
    })


class HostedStateCoordinator:
    """The only supported path from controller state to a hosted cell head."""

    def __init__(
        self,
        store: PostgresHostedStore,
        objects: ControllerObjectStore,
        *,
        scratch_dir: Path,
    ) -> None:
        self._store = store
        self._objects = objects
        self._scratch_dir = Path(scratch_dir).resolve()
        self._scratch_dir.mkdir(parents=True, exist_ok=True)

    def initialize_cell(
        self,
        *,
        cell_id: str,
        owner_id: str,
        runtime: Runtime,
    ) -> CellHead:
        if not isinstance(runtime, Runtime):
            raise HostedStoreError("initial state must be a controller Runtime")
        checkpoint_bytes = self._dump_snapshot(runtime.snapshot())
        checkpoint = self._write(owner_id, cell_id, "checkpoint", checkpoint_bytes)
        manifest_bytes = root_manifest_bytes(
            cell_id=cell_id,
            state_sha256=runtime.state_hash,
            event_index=runtime.event_index,
            checkpoint=checkpoint,
        )
        root_manifest = self._write(owner_id, cell_id, "manifest", manifest_bytes)
        self._expect_bytes(owner_id, cell_id, checkpoint, checkpoint_bytes)
        self._expect_bytes(owner_id, cell_id, root_manifest, manifest_bytes)
        self._store._create_cell(
            cell_id=cell_id,
            owner_id=owner_id,
            initial_state_sha256=runtime.state_hash,
            initial_event_index=runtime.event_index,
            checkpoint=checkpoint,
            root_manifest=root_manifest,
        )
        head, segments = self._store.load_replay_records(
            cell_id=cell_id, owner_id=owner_id
        )
        if segments:
            raise HostedStoreError("new cell unexpectedly has admission history")
        return head

    def restore(
        self,
        *,
        cell_id: str,
        owner_id: str,
        model: Model,
        config: RuntimeConfig | None = None,
    ) -> VerifiedReplay:
        """Restore exact head-bound objects and replay admissions without inference."""
        head, segments = self._store.load_replay_records(
            cell_id=cell_id, owner_id=owner_id
        )
        initial_bytes = self._read(owner_id, cell_id, head.initial_checkpoint)
        initial_snapshot = self._load_snapshot(initial_bytes)
        initial_runtime = Runtime.from_snapshot(model, initial_snapshot, config=config)
        self._verify_manifest_root(head, initial_runtime)

        all_events: list[EventRecord] = []
        previous_manifest = head.initial_manifest.sha256
        previous_state = initial_runtime.state_hash
        previous_index = head.initial_event_index
        if initial_runtime.event_index != previous_index:
            raise HostedStoreError("initial checkpoint event index mismatch")
        if len(segments) != head.revision:
            raise HostedStoreError("admission history is incomplete")
        latest_checkpoint = head.initial_checkpoint
        latest_manifest = head.initial_manifest

        for expected_revision, segment in enumerate(segments, start=1):
            if (
                segment.revision != expected_revision
                or segment.previous_manifest_sha256 != previous_manifest
                or segment.pre_state_sha256 != previous_state
                or segment.first_event_index != previous_index + 1
            ):
                raise HostedStoreError("admission history chain is discontinuous")
            event_bytes = self._read(owner_id, cell_id, segment.event_segment)
            checkpoint_bytes = self._read(owner_id, cell_id, segment.checkpoint)
            manifest_bytes = admission_manifest_bytes(
                cell_id=cell_id,
                revision=segment.revision,
                admission_id=segment.admission_id,
                previous_manifest_sha256=segment.previous_manifest_sha256,
                pre_state_sha256=segment.pre_state_sha256,
                post_state_sha256=segment.post_state_sha256,
                first_event_index=segment.first_event_index,
                last_event_index=segment.last_event_index,
                checkpoint=segment.checkpoint,
                event_segment=segment.event_segment,
            )
            self._expect_bytes(owner_id, cell_id, segment.manifest, manifest_bytes)
            events = self._decode_events(event_bytes)
            expected_count = segment.last_event_index - segment.first_event_index + 1
            if len(events) != expected_count or not events:
                raise HostedStoreError("admission event segment length mismatch")
            if (
                events[0].event_index != segment.first_event_index
                or events[-1].event_index != segment.last_event_index
                or events[0].pre_state_hash != segment.pre_state_sha256
                or events[-1].post_state_hash != segment.post_state_sha256
            ):
                raise HostedStoreError("admission event segment does not match manifest")
            all_events.extend(events)
            previous_state = segment.post_state_sha256
            previous_index = segment.last_event_index
            previous_manifest = segment.manifest.sha256
            latest_checkpoint = segment.checkpoint
            latest_manifest = segment.manifest
            # Hash-check every stored checkpoint; deserialize only the exact
            # current head checkpoint below after replay validates the history.
            _ = checkpoint_bytes

        if (
            latest_checkpoint != head.checkpoint
            or latest_manifest != head.manifest
            or previous_manifest != head.manifest.sha256
            or previous_state != head.admitted_state_sha256
            or previous_index != head.last_event_index
        ):
            raise HostedStoreError("database head does not match committed manifests")
        runtime = Runtime.replay_deltas(
            model, initial_snapshot, all_events, config=config
        )
        if runtime.state_hash != head.admitted_state_sha256:
            raise HostedStoreError("admission-only replay does not match canonical head")
        if runtime.event_index != head.last_event_index:
            raise HostedStoreError("admission-only replay event index mismatch")
        head_checkpoint = self._load_snapshot(self._read(owner_id, cell_id, head.checkpoint))
        checkpoint_runtime = Runtime.from_snapshot(model, head_checkpoint, config=config)
        if checkpoint_runtime.state_hash != runtime.state_hash:
            raise HostedStoreError("head checkpoint differs from replayed admitted state")
        # Admission replay is audit-only by kernel contract. Continue execution
        # only from the independently verified, native checkpoint.
        return VerifiedReplay(head, checkpoint_runtime, initial_snapshot, tuple(all_events))

    def commit_admission(
        self,
        *,
        attempt: Attempt,
        controller_id: str,
        fence: int,
        candidate_runtime: Runtime,
        actual_units: int,
        model: Model,
        config: RuntimeConfig | None = None,
    ) -> AdmissionReceipt:
        """Replay accepted events, serialize them in-controller, then CAS the head.

        The caller supplies a controller Runtime, never serialized bytes,
        event records, or object refs. Accepted records come from its kernel log.
        """
        receipt = self._store.find_committed_receipt(
            attempt_id=attempt.attempt_id,
            owner_id=attempt.owner_id,
            request_sha256=attempt.request_sha256,
        )
        if receipt is not None:
            return receipt
        if not attempt.dispatch_allowed or attempt.status != "dispatch_intent":
            raise HostedStoreError("only a newly authorized attempt can be committed")
        current = self.restore(
            cell_id=attempt.cell_id,
            owner_id=attempt.owner_id,
            model=model,
            config=config,
        )
        head = current.head
        if (
            head.fence != fence
            or head.lease_owner != controller_id
            or head.revision != attempt.expected_revision
        ):
            raise HostedStoreError("attempt no longer matches current cell head")
        if type(candidate_runtime) is not Runtime:
            raise HostedStoreError("admission requires a native controller Runtime")
        events = [
            record for record in candidate_runtime.event_log
            if record.event_index > head.last_event_index
        ]
        if not events or any(
            not isinstance(event, EventRecord) for event in events
        ):
            raise HostedStoreError("admission must contain at least one accepted event")
        if (
            events[0].event_index != head.last_event_index + 1
            or events[0].pre_state_hash != head.admitted_state_sha256
        ):
            raise HostedStoreError("new events do not continue the committed head")
        last_event_index = events[-1].event_index
        if last_event_index < events[0].event_index:
            raise HostedStoreError("new event range is invalid")
        replayed = Runtime.replay_deltas(
            model, current.initial_snapshot,
            (*current.event_records, *events), config=config,
        )
        if (
            candidate_runtime.state_hash != replayed.state_hash
            or candidate_runtime.event_index != last_event_index
        ):
            raise HostedStoreError("controller runtime differs from accepted event replay")
        checkpoint_bytes = self._dump_snapshot(candidate_runtime.snapshot())
        event_bytes = pickle.dumps(events, protocol=pickle.HIGHEST_PROTOCOL)
        checkpoint = self._write(attempt.owner_id, attempt.cell_id, "checkpoint", checkpoint_bytes)
        event_segment = self._write(attempt.owner_id, attempt.cell_id, "events", event_bytes)
        expected_manifest = admission_manifest_bytes(
            cell_id=head.cell_id,
            revision=head.revision + 1,
            admission_id=attempt.admission_id,
            previous_manifest_sha256=head.manifest.sha256,
            pre_state_sha256=head.admitted_state_sha256,
            post_state_sha256=replayed.state_hash,
            first_event_index=events[0].event_index,
            last_event_index=last_event_index,
            checkpoint=checkpoint,
            event_segment=event_segment,
        )
        manifest = self._write(attempt.owner_id, attempt.cell_id, "manifest", expected_manifest)
        # Read back exact versions and verify before recording their refs in SQL.
        self._expect_bytes(attempt.owner_id, attempt.cell_id, checkpoint, checkpoint_bytes)
        self._expect_bytes(attempt.owner_id, attempt.cell_id, event_segment, event_bytes)
        self._expect_bytes(attempt.owner_id, attempt.cell_id, manifest, expected_manifest)
        return self._store._commit_admission(
            attempt_id=attempt.attempt_id,
            controller_id=controller_id,
            fence=fence,
            pre_state_sha256=head.admitted_state_sha256,
            post_state_sha256=replayed.state_hash,
            checkpoint=checkpoint,
            event_segment=event_segment,
            manifest=manifest,
            first_event_index=events[0].event_index,
            last_event_index=last_event_index,
            previous_manifest_sha256=head.manifest.sha256,
            actual_units=actual_units,
        )

    def _verify_manifest_root(self, head: CellHead, runtime: Runtime) -> None:
        expected = root_manifest_bytes(
            cell_id=head.cell_id,
            state_sha256=runtime.state_hash,
            event_index=runtime.event_index,
            checkpoint=head.initial_checkpoint,
        )
        self._expect_bytes(head.owner_id, head.cell_id, head.initial_manifest, expected)

    @staticmethod
    def _prefix(owner_id: str, cell_id: str) -> str:
        owner = uuid.uuid5(uuid.NAMESPACE_URL, owner_id).hex
        cell = uuid.uuid5(uuid.NAMESPACE_URL, cell_id).hex
        return f"grokcell/controller/{owner}/{cell}/"

    def _write(self, owner_id: str, cell_id: str, kind: str, value: bytes) -> ObjectRef:
        key = self._prefix(owner_id, cell_id) + f"{kind}/{uuid.uuid4().hex}"
        version_id = self._objects.write_version(key, value)
        ref = ObjectRef(key, version_id, _sha256(value))
        ref.validate()
        self._assert_controller_ref(owner_id, cell_id, ref)
        return ref

    def _assert_controller_ref(self, owner_id: str, cell_id: str, ref: ObjectRef) -> None:
        ref.validate()
        if not ref.key.startswith(self._prefix(owner_id, cell_id)):
            raise HostedStoreError("object reference is outside controller-owned cell namespace")

    def _read(self, owner_id: str, cell_id: str, ref: ObjectRef) -> bytes:
        self._assert_controller_ref(owner_id, cell_id, ref)
        value = self._objects.read_version(ref.key, ref.version_id)
        if not isinstance(value, bytes) or _sha256(value) != ref.sha256:
            raise HostedStoreError("immutable object digest mismatch")
        return value

    def _expect_bytes(self, owner_id: str, cell_id: str, ref: ObjectRef, expected: bytes) -> None:
        actual = self._read(owner_id, cell_id, ref)
        if actual != expected:
            raise HostedStoreError("object content does not match committed manifest")

    def _load_snapshot(self, value: bytes) -> RuntimeSnapshot:
        with tempfile.TemporaryDirectory(dir=self._scratch_dir) as directory:
            path = Path(directory) / f"checkpoint-{uuid.uuid4().hex}.osahr.gz"
            path.write_bytes(value)
            return load_checkpoint(path)

    def _dump_snapshot(self, snapshot: RuntimeSnapshot) -> bytes:
        with tempfile.TemporaryDirectory(dir=self._scratch_dir) as directory:
            path = Path(directory) / f"checkpoint-{uuid.uuid4().hex}.osahr.gz"
            save_checkpoint(path, snapshot)
            return path.read_bytes()

    @staticmethod
    def _decode_events(value: bytes) -> list[EventRecord]:
        try:
            events = pickle.loads(value)
        except Exception as exc:
            raise HostedStoreError("admission event segment is invalid") from exc
        if not isinstance(events, list) or any(
            not isinstance(event, EventRecord) for event in events
        ):
            raise HostedStoreError("admission event segment has invalid event types")
        return events
