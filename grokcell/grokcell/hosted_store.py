"""PostgreSQL authority for hosted GrokCell attempts and cell heads.

This module never calls a model or executor. Callers must derive ``owner_id``
from authenticated server identity and use a database role unavailable to the
public API for controller operations.
"""
from __future__ import annotations

import uuid
from importlib.resources import files
from typing import Any, Mapping

from .hosted_types import (
    AdmissionReceipt,
    AdmissionSegment,
    Attempt,
    AttemptBlocked,
    BudgetExceeded,
    CellHead,
    HostedStoreError,
    IdempotencyConflict,
    ObjectRef,
    StaleFence,
    _SHA256,
    request_digest,
)

_MAX_LEASE_SECONDS = 300


def _row_attempt(row: Mapping[str, Any], *, dispatch_allowed: bool) -> Attempt:
    return Attempt(
        admission_id=row["admission_id"],
        attempt_id=row["attempt_id"],
        owner_id=row["owner_id"],
        cell_id=row["cell_id"],
        idempotency_key=row["idempotency_key"],
        request_sha256=row["request_sha256"],
        expected_revision=row["expected_revision"],
        fence=row["fence"],
        reserved_units=row["reserved_units"],
        status=row["status"],
        dispatch_allowed=dispatch_allowed,
    )


def _object_ref(row: Mapping[str, Any], prefix: str) -> ObjectRef:
    return ObjectRef(
        row[f"{prefix}_key"], row[f"{prefix}_version"], row[f"{prefix}_sha256"]
    )


class PostgresHostedStore:
    """Small transactional store; SQL transaction boundaries are the authority."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError("hosted PostgreSQL DSN is required")
        self._dsn = dsn

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "install grokcell-surface[hosted] to use PostgreSQL hosting"
            ) from exc
        return psycopg.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=5,
            options=(
                "-c statement_timeout=5000 "
                "-c lock_timeout=2000 "
                "-c idle_in_transaction_session_timeout=5000"
            ),
        )

    def migrate(self) -> None:
        schema = (
            files("grokcell")
            .joinpath("resources", "sql", "001_hosted_durability.sql")
            .read_text(encoding="utf-8")
        )
        with self._connect() as connection:
            connection.execute(schema, prepare=False)

    def add_budget(self, owner_id: str, units: int) -> None:
        """Add controller-provisioned work units; never called from job input."""
        if not owner_id or units <= 0:
            raise ValueError("owner and positive budget units are required")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO grokcell_owner_budgets(owner_id, available_units)
                   VALUES (%s, %s)
                   ON CONFLICT (owner_id) DO UPDATE
                   SET available_units = grokcell_owner_budgets.available_units + EXCLUDED.available_units""",
                (owner_id, units),
            )

    def _create_cell(
        self,
        *,
        cell_id: str,
        owner_id: str,
        initial_state_sha256: str,
        initial_event_index: int,
        checkpoint: ObjectRef,
        root_manifest: ObjectRef,
    ) -> None:
        checkpoint.validate()
        root_manifest.validate()
        if (
            not cell_id
            or not owner_id
            or not _SHA256.fullmatch(initial_state_sha256)
            or initial_event_index < 0
        ):
            raise ValueError("invalid initial hosted cell state")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO grokcell_cell_heads(
                       cell_id, owner_id, admitted_state_sha256,
                       initial_event_index, last_event_index,
                       initial_checkpoint_key, initial_checkpoint_version,
                       initial_checkpoint_sha256, initial_manifest_key,
                       initial_manifest_version, initial_manifest_sha256,
                       checkpoint_key,
                       checkpoint_version, checkpoint_sha256, manifest_key,
                       manifest_version, manifest_sha256)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    cell_id,
                    owner_id,
                    initial_state_sha256,
                    initial_event_index,
                    initial_event_index,
                    checkpoint.key,
                    checkpoint.version_id,
                    checkpoint.sha256,
                    root_manifest.key,
                    root_manifest.version_id,
                    root_manifest.sha256,
                    checkpoint.key,
                    checkpoint.version_id,
                    checkpoint.sha256,
                    root_manifest.key,
                    root_manifest.version_id,
                    root_manifest.sha256,
                ),
            )

    def claim_cell(
        self, *, cell_id: str, controller_id: str, lease_seconds: int = 30
    ) -> int:
        if not controller_id or not 1 <= lease_seconds <= _MAX_LEASE_SECONDS:
            raise ValueError("invalid controller lease")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE grokcell_cell_heads
                   SET fence = fence + 1, lease_owner = %s,
                       lease_expires_at = clock_timestamp() + (%s * interval '1 second'),
                       updated_at = clock_timestamp()
                   WHERE cell_id = %s
                     AND (lease_expires_at IS NULL OR lease_expires_at <= clock_timestamp())
                   RETURNING fence""",
                (controller_id, lease_seconds, cell_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise StaleFence("cell is leased or does not exist")
            fence = row["fence"]
            cursor.execute(
                """UPDATE grokcell_attempts
                   SET status = 'outcome_unknown', updated_at = clock_timestamp()
                   WHERE cell_id = %s AND status = 'dispatch_intent' AND fence < %s""",
                (cell_id, fence),
            )
            return fence

    def renew_lease(
        self, *, cell_id: str, controller_id: str, fence: int, lease_seconds: int = 30
    ) -> None:
        if not 1 <= lease_seconds <= _MAX_LEASE_SECONDS:
            raise ValueError("invalid controller lease")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE grokcell_cell_heads
                   SET lease_expires_at = clock_timestamp() + (%s * interval '1 second'),
                       updated_at = clock_timestamp()
                   WHERE cell_id = %s AND lease_owner = %s AND fence = %s
                     AND lease_expires_at > clock_timestamp()""",
                (lease_seconds, cell_id, controller_id, fence),
            )
            if cursor.rowcount != 1:
                raise StaleFence("cell lease expired or changed")

    def begin_dispatch(
        self,
        *,
        owner_id: str,
        cell_id: str,
        controller_id: str,
        fence: int,
        expected_revision: int,
        idempotency_key: str,
        operation: str,
        request: Mapping[str, Any],
        reserve_units: int,
    ) -> Attempt:
        """Commit budget reservation and dispatch intent before external work.

        Only a newly inserted result has ``dispatch_allowed=True``. Replays
        return the original attempt with dispatch disabled, even if the original
        transaction's acknowledgement was lost.
        """
        if (
            not owner_id
            or not idempotency_key
            or len(idempotency_key) > 200
            or not operation
            or reserve_units <= 0
        ):
            raise ValueError("invalid hosted attempt request")
        request_sha256 = request_digest(
            owner_id=owner_id,
            cell_id=cell_id,
            operation=operation,
            expected_revision=expected_revision,
            reserve_units=reserve_units,
            request=request,
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT *, (lease_expires_at > clock_timestamp()) AS lease_valid
                   FROM grokcell_cell_heads WHERE cell_id=%s FOR UPDATE""",
                (cell_id,),
            )
            head = cursor.fetchone()
            if head is None or head["owner_id"] != owner_id:
                raise HostedStoreError("cell is unavailable")
            cursor.execute(
                """SELECT * FROM grokcell_attempts
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (owner_id, idempotency_key),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    raise IdempotencyConflict("idempotency key reused with different request")
                return _row_attempt(existing, dispatch_allowed=False)
            self._assert_lease(head, controller_id, fence)
            if head["revision"] != expected_revision:
                raise StaleFence("cell revision changed")
            cursor.execute(
                """SELECT 1 FROM grokcell_attempts
                   WHERE cell_id=%s AND status IN ('dispatch_intent','outcome_unknown')""",
                (cell_id,),
            )
            if cursor.fetchone() is not None:
                raise AttemptBlocked("cell has an unresolved attempt")
            cursor.execute(
                "SELECT available_units FROM grokcell_owner_budgets WHERE owner_id=%s FOR UPDATE",
                (owner_id,),
            )
            budget = cursor.fetchone()
            if budget is None or budget["available_units"] < reserve_units:
                raise BudgetExceeded("insufficient hosted budget")
            admission_id = uuid.uuid4()
            attempt_id = uuid.uuid4()
            cursor.execute(
                """INSERT INTO grokcell_attempts(
                       attempt_id, admission_id, owner_id, cell_id,
                       idempotency_key, request_sha256, expected_revision,
                       fence, reserved_units, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'dispatch_intent')
                   ON CONFLICT (owner_id, idempotency_key) DO NOTHING
                   RETURNING *""",
                (
                    attempt_id,
                    admission_id,
                    owner_id,
                    cell_id,
                    idempotency_key,
                    request_sha256,
                    expected_revision,
                    fence,
                    reserve_units,
                ),
            )
            inserted = cursor.fetchone()
            if inserted is None:
                cursor.execute(
                    """SELECT * FROM grokcell_attempts
                       WHERE owner_id=%s AND idempotency_key=%s""",
                    (owner_id, idempotency_key),
                )
                existing = cursor.fetchone()
                if existing is None or existing["request_sha256"] != request_sha256:
                    raise IdempotencyConflict("idempotency key reused with different request")
                return _row_attempt(existing, dispatch_allowed=False)
            cursor.execute(
                """UPDATE grokcell_cell_heads SET updated_at=clock_timestamp()
                   WHERE cell_id=%s AND lease_owner=%s AND fence=%s
                     AND lease_expires_at > clock_timestamp()""",
                (cell_id, controller_id, fence),
            )
            if cursor.rowcount != 1:
                raise StaleFence("cell lease expired before dispatch authorization")
            cursor.execute(
                """UPDATE grokcell_owner_budgets
                   SET available_units = available_units - %s,
                       reserved_units = reserved_units + %s
                   WHERE owner_id = %s""",
                (reserve_units, reserve_units, owner_id),
            )
            return _row_attempt(inserted, dispatch_allowed=True)

    def find_committed_receipt(
        self, *, attempt_id: uuid.UUID, owner_id: str, request_sha256: str
    ) -> AdmissionReceipt | None:
        """Return an attempt's immutable original result for a safe lost-ack retry."""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT a.admission_id, a.attempt_id, a.cell_id,
                          a.request_sha256, a.status, a.result_revision,
                          a.result_sha256, s.manifest_key, s.manifest_version,
                          s.manifest_sha256
                   FROM grokcell_attempts AS a
                   JOIN grokcell_admission_segments AS s
                     ON s.cell_id=a.cell_id AND s.revision=a.result_revision
                   WHERE a.attempt_id=%s AND a.owner_id=%s""",
                (attempt_id, owner_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            if row["request_sha256"] != request_sha256:
                raise IdempotencyConflict("attempt does not match the original request")
            if row["status"] != "admitted" or row["result_revision"] is None:
                return None
            return AdmissionReceipt(
                row["admission_id"], row["attempt_id"], row["cell_id"],
                row["result_revision"], row["result_sha256"],
                _object_ref(row, "manifest"),
            )

    def _commit_admission(
        self,
        *,
        attempt_id: uuid.UUID,
        controller_id: str,
        fence: int,
        pre_state_sha256: str,
        post_state_sha256: str,
        checkpoint: ObjectRef,
        event_segment: ObjectRef,
        manifest: ObjectRef,
        first_event_index: int,
        last_event_index: int,
        previous_manifest_sha256: str,
        actual_units: int,
    ) -> AdmissionReceipt:
        for ref in (checkpoint, event_segment, manifest):
            ref.validate()
        if (
            not _SHA256.fullmatch(pre_state_sha256)
            or not _SHA256.fullmatch(post_state_sha256)
            or not _SHA256.fullmatch(previous_manifest_sha256)
            or first_event_index <= 0
            or last_event_index < first_event_index
            or actual_units < 0
        ):
            raise ValueError("invalid hosted admission evidence")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT cell_id FROM grokcell_attempts WHERE attempt_id=%s",
                (attempt_id,),
            )
            locator = cursor.fetchone()
            if locator is None:
                raise HostedStoreError("attempt is unavailable")
            cursor.execute(
                """SELECT *, (lease_expires_at > clock_timestamp()) AS lease_valid
                   FROM grokcell_cell_heads WHERE cell_id=%s FOR UPDATE""",
                (locator["cell_id"],),
            )
            head = cursor.fetchone()
            if head is None:
                raise HostedStoreError("cell is unavailable")
            cursor.execute(
                """SELECT * FROM grokcell_attempts WHERE attempt_id=%s FOR UPDATE""",
                (attempt_id,),
            )
            attempt = cursor.fetchone()
            if attempt is None:
                raise HostedStoreError("attempt is unavailable")
            if attempt["status"] == "admitted":
                cursor.execute(
                    """SELECT manifest_key, manifest_version, manifest_sha256
                       FROM grokcell_admission_segments
                       WHERE cell_id=%s AND revision=%s""",
                    (attempt["cell_id"], attempt["result_revision"]),
                )
                committed = cursor.fetchone()
                if committed is None:
                    raise HostedStoreError("committed admission receipt is missing")
                return AdmissionReceipt(
                    attempt["admission_id"], attempt_id, attempt["cell_id"],
                    attempt["result_revision"], attempt["result_sha256"],
                    _object_ref(committed, "manifest"),
                )
            self._assert_lease(head, controller_id, fence)
            if (
                attempt["status"] != "dispatch_intent"
                or attempt["fence"] != fence
                or attempt["owner_id"] != head["owner_id"]
                or attempt["expected_revision"] != head["revision"]
                or pre_state_sha256 != head["admitted_state_sha256"]
                or previous_manifest_sha256 != head["manifest_sha256"]
                or first_event_index != head["last_event_index"] + 1
                or actual_units > attempt["reserved_units"]
            ):
                raise StaleFence("attempt no longer matches the authoritative cell head")
            revision = head["revision"] + 1
            cursor.execute(
                """INSERT INTO grokcell_admission_segments(
                       cell_id, revision, admission_id, first_event_index,
                       last_event_index, pre_state_sha256, post_state_sha256,
                       checkpoint_key, checkpoint_version, checkpoint_sha256,
                       event_key, event_version, event_sha256,
                       manifest_key, manifest_version, manifest_sha256,
                       previous_manifest_sha256)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    head["cell_id"], revision, attempt["admission_id"],
                    first_event_index, last_event_index, pre_state_sha256,
                    post_state_sha256, checkpoint.key, checkpoint.version_id,
                    checkpoint.sha256, event_segment.key, event_segment.version_id,
                    event_segment.sha256, manifest.key, manifest.version_id,
                    manifest.sha256, previous_manifest_sha256,
                ),
            )
            cursor.execute(
                """UPDATE grokcell_cell_heads SET
                       revision=%s, admitted_state_sha256=%s,
                       last_event_index=%s, checkpoint_key=%s,
                       checkpoint_version=%s, checkpoint_sha256=%s,
                       manifest_key=%s, manifest_version=%s, manifest_sha256=%s,
                       updated_at=clock_timestamp()
                   WHERE cell_id=%s AND revision=%s AND fence=%s
                     AND lease_owner=%s AND lease_expires_at > clock_timestamp()""",
                (
                    revision, post_state_sha256, last_event_index,
                    checkpoint.key, checkpoint.version_id, checkpoint.sha256,
                    manifest.key, manifest.version_id, manifest.sha256,
                    head["cell_id"], attempt["expected_revision"], fence,
                    controller_id,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleFence("cell head compare-and-swap failed")
            cursor.execute(
                """UPDATE grokcell_attempts SET status='admitted',
                       actual_units=%s, result_sha256=%s, result_revision=%s,
                       updated_at=clock_timestamp()
                   WHERE attempt_id=%s AND status='dispatch_intent' AND fence=%s""",
                (actual_units, post_state_sha256, revision, attempt_id, fence),
            )
            if cursor.rowcount != 1:
                raise StaleFence("attempt completion compare-and-swap failed")
            self._settle_budget(cursor, attempt["owner_id"], attempt["reserved_units"], actual_units)
            event_id = f"admission:{attempt['admission_id']}"
            cursor.execute(
                """INSERT INTO grokcell_outbox(event_id, attempt_id, payload)
                   VALUES (%s,%s,jsonb_build_object('cell_id',%s::text,'revision',%s::bigint,
                     'admission_id',%s::text,'state_sha256',%s::text))""",
                (event_id, attempt_id, head["cell_id"], revision,
                 str(attempt["admission_id"]), post_state_sha256),
            )
            return AdmissionReceipt(
                attempt["admission_id"], attempt_id, head["cell_id"],
                revision, post_state_sha256, manifest,
            )

    def mark_outcome_unknown(
        self, *, attempt_id: uuid.UUID, controller_id: str, fence: int
    ) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT cell_id FROM grokcell_attempts WHERE attempt_id=%s""",
                (attempt_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise HostedStoreError("attempt is unavailable")
            cursor.execute(
                """SELECT *, (lease_expires_at > clock_timestamp()) AS lease_valid
                   FROM grokcell_cell_heads WHERE cell_id=%s FOR UPDATE""",
                (row["cell_id"],),
            )
            head = cursor.fetchone()
            if head is None:
                raise HostedStoreError("cell is unavailable")
            self._assert_lease(head, controller_id, fence)
            cursor.execute(
                """UPDATE grokcell_attempts SET status='outcome_unknown',
                       updated_at=clock_timestamp()
                   WHERE attempt_id=%s AND status='dispatch_intent' AND fence=%s""",
                (attempt_id, fence),
            )
            if cursor.rowcount != 1:
                raise StaleFence("attempt is no longer owned by this fence")
            cursor.execute(
                """UPDATE grokcell_cell_heads SET updated_at=clock_timestamp()
                   WHERE cell_id=%s AND lease_owner=%s AND fence=%s
                     AND lease_expires_at > clock_timestamp()""",
                (row["cell_id"], controller_id, fence),
            )
            if cursor.rowcount != 1:
                raise StaleFence("cell lease expired before outcome update")

    def reconcile_unknown(
        self,
        *,
        attempt_id: uuid.UUID,
        controller_id: str,
        fence: int,
        resolution: str,
        evidence_sha256: str,
        actual_units: int,
    ) -> None:
        """Explicitly release an unknown attempt; never retries it."""
        if (
            resolution != "no_admission"
            or not _SHA256.fullmatch(evidence_sha256)
            or actual_units < 0
        ):
            raise ValueError("unknown outcomes require explicit no-admission evidence")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT cell_id FROM grokcell_attempts WHERE attempt_id=%s",
                (attempt_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise HostedStoreError("attempt is unavailable")
            cursor.execute(
                """SELECT *, (lease_expires_at > clock_timestamp()) AS lease_valid
                   FROM grokcell_cell_heads WHERE cell_id=%s FOR UPDATE""",
                (row["cell_id"],),
            )
            head = cursor.fetchone()
            if head is None:
                raise HostedStoreError("cell is unavailable")
            self._assert_lease(head, controller_id, fence)
            cursor.execute(
                "SELECT * FROM grokcell_attempts WHERE attempt_id=%s FOR UPDATE",
                (attempt_id,),
            )
            attempt = cursor.fetchone()
            if attempt["status"] != "outcome_unknown":
                raise HostedStoreError("attempt is not unresolved")
            if actual_units > attempt["reserved_units"]:
                raise BudgetExceeded("resolved cost exceeds its reservation")
            cursor.execute(
                """UPDATE grokcell_attempts SET status='reconciled_unknown',
                       actual_units=%s, result_sha256=%s,
                       updated_at=clock_timestamp()
                   WHERE attempt_id=%s AND status='outcome_unknown'""",
                (actual_units, evidence_sha256, attempt_id),
            )
            self._settle_budget(cursor, attempt["owner_id"], attempt["reserved_units"], actual_units)
            cursor.execute(
                """UPDATE grokcell_cell_heads SET updated_at=clock_timestamp()
                   WHERE cell_id=%s AND lease_owner=%s AND fence=%s
                     AND lease_expires_at > clock_timestamp()""",
                (row["cell_id"], controller_id, fence),
            )
            if cursor.rowcount != 1:
                raise StaleFence("cell lease expired before reconciliation")

    def load_replay_records(
        self, *, cell_id: str, owner_id: str
    ) -> tuple[CellHead, list[AdmissionSegment]]:
        """Return only committed refs; object reads must use exact versions."""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM grokcell_cell_heads WHERE cell_id=%s AND owner_id=%s",
                (cell_id, owner_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise HostedStoreError("cell is unavailable")
            cursor.execute(
                """SELECT * FROM grokcell_admission_segments
                   WHERE cell_id=%s AND revision <= %s ORDER BY revision ASC""",
                (cell_id, row["revision"]),
            )
            segments = [
                AdmissionSegment(
                    revision=item["revision"],
                    admission_id=item["admission_id"],
                    first_event_index=item["first_event_index"],
                    last_event_index=item["last_event_index"],
                    pre_state_sha256=item["pre_state_sha256"],
                    post_state_sha256=item["post_state_sha256"],
                    checkpoint=_object_ref(item, "checkpoint"),
                    event_segment=_object_ref(item, "event"),
                    manifest=_object_ref(item, "manifest"),
                    previous_manifest_sha256=item["previous_manifest_sha256"],
                )
                for item in cursor.fetchall()
            ]
            return self._head_from_row(row), segments

    @staticmethod
    def _assert_lease(head: Mapping[str, Any], controller_id: str, fence: int) -> None:
        if (
            head["lease_owner"] != controller_id
            or head["fence"] != fence
            or not head["lease_valid"]
        ):
            raise StaleFence("controller does not own the current cell fence")

    @staticmethod
    def _settle_budget(cursor, owner_id: str, reserved: int, actual: int) -> None:
        if actual > reserved:
            raise BudgetExceeded("actual work exceeds its reservation")
        cursor.execute(
            """UPDATE grokcell_owner_budgets
               SET reserved_units=reserved_units-%s,
                   available_units=available_units+%s,
                   spent_units=spent_units+%s
               WHERE owner_id=%s AND reserved_units >= %s""",
            (reserved, reserved - actual, actual, owner_id, reserved),
        )
        if cursor.rowcount != 1:
            raise HostedStoreError("budget reservation was lost")

    @staticmethod
    def _head_from_row(row: Mapping[str, Any]) -> CellHead:
        return CellHead(
            cell_id=row["cell_id"],
            owner_id=row["owner_id"],
            revision=row["revision"],
            fence=row["fence"],
            lease_owner=row["lease_owner"],
            admitted_state_sha256=row["admitted_state_sha256"],
            initial_event_index=row["initial_event_index"],
            last_event_index=row["last_event_index"],
            initial_checkpoint=_object_ref(row, "initial_checkpoint"),
            checkpoint=_object_ref(row, "checkpoint"),
            initial_manifest=_object_ref(row, "initial_manifest"),
            manifest=_object_ref(row, "manifest"),
        )
