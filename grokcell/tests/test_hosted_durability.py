from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path

import pytest

from grokcell.construction import build_runtime, construction_model, licensed_assemble
from grokcell.hosted_replay import HostedStateCoordinator
from grokcell.hosted_store import PostgresHostedStore
from grokcell.hosted_types import IdempotencyConflict, ObjectRef, StaleFence


class MemoryVersionedObjects:
    """Test object store with immutable, exact-version reads."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}

    def write_version(self, key: str, value: bytes) -> str:
        version = uuid.uuid4().hex
        self.values[(key, version)] = bytes(value)
        return version

    def read_version(self, key: str, version_id: str) -> bytes:
        return self.values[(key, version_id)]


@pytest.fixture
def hosted(tmp_path: Path):
    dsn = os.environ.get("OSAHR_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("OSAHR_TEST_DATABASE_URL is not configured")
    pytest.importorskip("psycopg")
    store = PostgresHostedStore(dsn)
    store.migrate()
    owner = f"test-{uuid.uuid4()}"
    cell = f"cell-{uuid.uuid4()}"
    store.add_budget(owner, 100)
    objects = MemoryVersionedObjects()
    coordinator = HostedStateCoordinator(store, objects, scratch_dir=tmp_path)
    runtime = build_runtime()
    coordinator.initialize_cell(cell_id=cell, owner_id=owner, runtime=runtime)
    try:
        yield store, coordinator, objects, runtime, owner, cell
    finally:
        import psycopg

        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM grokcell_outbox WHERE attempt_id IN (SELECT attempt_id FROM grokcell_attempts WHERE owner_id=%s)", (owner,))
            cursor.execute("DELETE FROM grokcell_admission_segments WHERE cell_id=%s", (cell,))
            cursor.execute("DELETE FROM grokcell_attempts WHERE owner_id=%s", (owner,))
            cursor.execute("DELETE FROM grokcell_cell_heads WHERE cell_id=%s", (cell,))
            cursor.execute("DELETE FROM grokcell_owner_budgets WHERE owner_id=%s", (owner,))


def _begin(store, owner, cell, *, controller, fence, revision=0, key="request", reserve=5):
    return store.begin_dispatch(
        owner_id=owner,
        cell_id=cell,
        controller_id=controller,
        fence=fence,
        expected_revision=revision,
        idempotency_key=key,
        operation="assemble",
        request={"name": "core.api"},
        reserve_units=reserve,
    )


def test_postgres_admission_replay_and_lost_ack_returns_original_receipt(hosted):
    store, coordinator, _, runtime, owner, cell = hosted
    controller = "controller-a"
    fence = store.claim_cell(cell_id=cell, controller_id=controller)
    attempt = _begin(store, owner, cell, controller=controller, fence=fence)
    licensed_assemble(runtime, name="core.api", constraint="critical_module", seq=1)
    first = coordinator.commit_admission(
        attempt=attempt,
        controller_id=controller,
        fence=fence,
        candidate_runtime=runtime,
        actual_units=2,
        model=construction_model(),
    )

    restored = coordinator.restore(
        cell_id=cell, owner_id=owner, model=construction_model()
    )
    assert restored.runtime.state_hash == first.state_sha256
    assert restored.runtime.event_index == runtime.event_index

    second_attempt = _begin(
        store, owner, cell, controller=controller, fence=fence,
        revision=1, key="request-two",
    )
    second_runtime = restored.runtime
    licensed_assemble(second_runtime, name="app.ui", constraint="critical_module", seq=2)
    second = coordinator.commit_admission(
        attempt=second_attempt,
        controller_id=controller,
        fence=fence,
        candidate_runtime=second_runtime,
        actual_units=1,
        model=construction_model(),
    )
    assert second.revision == 2

    # A client retrying the first acknowledged request receives its original
    # receipt even though the live head has advanced.
    replayed = coordinator.commit_admission(
        attempt=attempt,
        controller_id=controller,
        fence=fence,
        candidate_runtime=runtime,
        actual_units=0,
        model=construction_model(),
    )
    assert replayed == first
    assert replayed.revision == 1


def test_idempotency_digest_covers_revision_and_reserved_units(hosted):
    store, _, _, _, owner, cell = hosted
    fence = store.claim_cell(cell_id=cell, controller_id="controller-a")
    original = _begin(store, owner, cell, controller="controller-a", fence=fence)
    assert not _begin(store, owner, cell, controller="controller-a", fence=fence).dispatch_allowed
    with pytest.raises(IdempotencyConflict):
        _begin(store, owner, cell, controller="controller-a", fence=fence, reserve=6)
    with pytest.raises(IdempotencyConflict):
        store.begin_dispatch(
            owner_id=owner, cell_id=cell, controller_id="controller-a", fence=fence,
            expected_revision=1, idempotency_key="request", operation="assemble",
            request={"name": "core.api"}, reserve_units=5,
        )
    with pytest.raises(IdempotencyConflict):
        store.begin_dispatch(
            owner_id=owner, cell_id=cell, controller_id="controller-a", fence=fence,
            expected_revision=0, idempotency_key="request", operation="assemble",
            request={"name": "different"}, reserve_units=5,
        )
    assert original.dispatch_allowed


def test_expired_lease_cannot_mutate_unknown_attempt_before_takeover(hosted):
    store, _, _, _, owner, cell = hosted
    controller = "controller-a"
    fence = store.claim_cell(cell_id=cell, controller_id=controller)
    attempt = _begin(store, owner, cell, controller=controller, fence=fence)
    import psycopg

    with psycopg.connect(store._dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE grokcell_cell_heads SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE cell_id=%s",
            (cell,),
        )
    with pytest.raises(StaleFence):
        store.mark_outcome_unknown(
            attempt_id=attempt.attempt_id, controller_id=controller, fence=fence
        )
    with pytest.raises(StaleFence):
        store.reconcile_unknown(
            attempt_id=attempt.attempt_id, controller_id=controller, fence=fence,
            resolution="no_admission", evidence_sha256="a" * 64, actual_units=0,
        )
    with pytest.raises(StaleFence):
        _begin(store, owner, cell, controller=controller, fence=fence, key="after-expiry")

    new_fence = store.claim_cell(cell_id=cell, controller_id="controller-b")
    assert new_fence == fence + 1
    with pytest.raises(StaleFence):
        store._commit_admission(
            attempt_id=attempt.attempt_id, controller_id=controller, fence=fence,
            pre_state_sha256="a" * 64, post_state_sha256="b" * 64,
            checkpoint=ObjectRef("k/a", "v1", "a" * 64),
            event_segment=ObjectRef("k/b", "v1", "b" * 64),
            manifest=ObjectRef("k/c", "v1", "c" * 64), first_event_index=1,
            last_event_index=1, previous_manifest_sha256="c" * 64, actual_units=0,
        )


def test_restore_rejects_correctly_hashed_untrusted_namespace_before_pickle(hosted, monkeypatch):
    store, coordinator, objects, _, owner, cell = hosted
    payload = b"this object has a valid digest but is quarantined and not controller-owned"
    sha = hashlib.sha256(payload).hexdigest()
    version = objects.write_version("quarantine/untrusted/checkpoint", payload)
    import psycopg

    with psycopg.connect(store._dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """UPDATE grokcell_cell_heads SET initial_checkpoint_key=%s,
                   initial_checkpoint_version=%s, initial_checkpoint_sha256=%s
               WHERE cell_id=%s""",
            ("quarantine/untrusted/checkpoint", version, sha, cell),
        )
    called = False

    def forbidden_loader(_value):
        nonlocal called
        called = True
        raise AssertionError("must reject provenance before deserialization")

    monkeypatch.setattr(coordinator, "_load_snapshot", forbidden_loader)
    from grokcell.hosted_types import HostedStoreError

    with pytest.raises(HostedStoreError, match="controller-owned"):
        coordinator.restore(cell_id=cell, owner_id=owner, model=construction_model())
    assert not called


def test_replay_segment_query_excludes_revisions_after_captured_head(hosted):
    store, coordinator, _, runtime, owner, cell = hosted
    controller = "controller-a"
    fence = store.claim_cell(cell_id=cell, controller_id=controller)
    first_attempt = _begin(store, owner, cell, controller=controller, fence=fence)
    licensed_assemble(runtime, name="core.api", constraint="critical_module", seq=1)
    coordinator.commit_admission(
        attempt=first_attempt, controller_id=controller, fence=fence,
        candidate_runtime=runtime, actual_units=1,
        model=construction_model(),
    )
    captured, segments = store.load_replay_records(cell_id=cell, owner_id=owner)
    assert captured.revision == 1 and len(segments) == 1
    second_attempt = _begin(
        store, owner, cell, controller=controller, fence=fence, revision=1, key="future"
    )
    import psycopg

    with psycopg.connect(store._dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO grokcell_admission_segments(
                   cell_id,revision,admission_id,first_event_index,last_event_index,
                   pre_state_sha256,post_state_sha256,checkpoint_key,checkpoint_version,
                   checkpoint_sha256,event_key,event_version,event_sha256,manifest_key,
                   manifest_version,manifest_sha256,previous_manifest_sha256)
               VALUES (%s,2,%s,3,3,%s,%s,'future/cp','v1',%s,'future/ev','v1',%s,
                       'future/manifest','v1',%s,%s)""",
            (cell, second_attempt.admission_id, "a"*64, "b"*64,
             "c"*64, "d"*64, "e"*64, segments[-1].manifest.sha256),
        )
    captured_again, capped_segments = store.load_replay_records(cell_id=cell, owner_id=owner)
    assert captured_again.revision == 1
    assert [item.revision for item in capped_segments] == [1]


def test_outbox_conflict_rolls_back_head_segment_attempt_and_budget(hosted):
    store, coordinator, _, runtime, owner, cell = hosted
    controller = "controller-a"
    fence = store.claim_cell(cell_id=cell, controller_id=controller)
    attempt = _begin(store, owner, cell, controller=controller, fence=fence)
    licensed_assemble(runtime, name="core.api", constraint="critical_module", seq=1)
    import psycopg

    with psycopg.connect(store._dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO grokcell_outbox(event_id,attempt_id,payload) VALUES (%s,%s,'{}')",
            (f"admission:{attempt.admission_id}", attempt.attempt_id),
        )
    with pytest.raises(psycopg.errors.UniqueViolation):
        coordinator.commit_admission(
            attempt=attempt, controller_id=controller, fence=fence,
            candidate_runtime=runtime, actual_units=2,
            model=construction_model(),
        )
    with psycopg.connect(store._dsn) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT revision FROM grokcell_cell_heads WHERE cell_id=%s", (cell,))
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT status FROM grokcell_attempts WHERE attempt_id=%s", (attempt.attempt_id,))
        assert cursor.fetchone()[0] == "dispatch_intent"
        cursor.execute("SELECT count(*) FROM grokcell_admission_segments WHERE cell_id=%s", (cell,))
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT available_units,reserved_units,spent_units FROM grokcell_owner_budgets WHERE owner_id=%s", (owner,))
        assert cursor.fetchone() == (95, 5, 0)


def test_lock_wait_is_bounded_and_expired_cell_can_be_taken_over(hosted):
    store, _, _, _, _, cell = hosted
    controller = "controller-a"
    fence = store.claim_cell(cell_id=cell, controller_id=controller, lease_seconds=1)
    import psycopg

    blocker = psycopg.connect(store._dsn)
    blocker.execute("SELECT cell_id FROM grokcell_cell_heads WHERE cell_id=%s FOR UPDATE", (cell,))
    time.sleep(1.1)
    started = time.monotonic()
    with pytest.raises(psycopg.errors.LockNotAvailable):
        store.claim_cell(cell_id=cell, controller_id="controller-b", lease_seconds=5)
    assert time.monotonic() - started < 5
    blocker.rollback()
    blocker.close()
    assert store.claim_cell(cell_id=cell, controller_id="controller-b") == fence + 1


def test_initialization_readback_failure_never_registers_head(hosted, tmp_path):
    store, _, _, _, owner, _ = hosted

    class CorruptReadback(MemoryVersionedObjects):
        def read_version(self, key: str, version_id: str) -> bytes:
            return super().read_version(key, version_id) + b"substituted"

    cell = f"cell-{uuid.uuid4()}"
    objects = CorruptReadback()
    coordinator = HostedStateCoordinator(store, objects, scratch_dir=tmp_path)
    from grokcell.hosted_types import HostedStoreError

    with pytest.raises(HostedStoreError, match="digest mismatch"):
        coordinator.initialize_cell(cell_id=cell, owner_id=owner, runtime=build_runtime())
    import psycopg

    with psycopg.connect(store._dsn) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM grokcell_cell_heads WHERE cell_id=%s", (cell,))
        assert cursor.fetchone() is None
