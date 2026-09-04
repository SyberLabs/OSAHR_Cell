from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from osahr import save_checkpoint

from grokcell.artifact import Artifact, ArtifactStore
from grokcell.construction import build_runtime
from grokcell.fidelity import FidelityStore
from grokcell.messages import Message
from grokcell.runner import RunOutcome, pytest_suite, suite_hash
from grokcell.snapshot import SnapshotStore, SurfaceSnapshot
from grokcell.surface import GrokCellSurface
from grokcell.tools import MUTATING_TOOLS, ToolRegistry
from grokcell.vault import ConstraintVault

from support import scored_surface


def isolated_surface(tmp_path: Path) -> GrokCellSurface:
    source = ConstraintVault.load()
    vault = ConstraintVault(source.concepts, root=tmp_path / "vault")
    return GrokCellSurface.open(
        vault=vault,
        fidelity=FidelityStore(tmp_path / "fidelity"),
        state=tmp_path / "state",
    )


def propose(tools: ToolRegistry, *, name: str, tests: str) -> dict:
    return tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {
                "name": name,
                "constraint": "unverified",
                "depends_on": [],
                "module": "def ping():\n    return 'pong'\n",
                "tests": tests,
            },
        },
    )


def test_payload_and_inspection_cannot_mutate_a_held_message(tmp_path: Path):
    surface = scored_surface("app.ui", root=tmp_path)
    tools = ToolRegistry(surface)
    dependencies = ["core.api"]
    payload = {
        "name": "app.ui",
        "constraint": "critical_module",
        "depends_on": dependencies,
    }
    posted = tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": payload,
        },
    )
    dependencies.clear()
    assert tools.call("bus.drain", {})["results"][0]["status"] == "hold_unresolved"

    inspected = tools.call("surface.inspect", {})
    inspected["held"][0]["payload"]["depends_on"].clear()
    refused = tools.call(
        "park.request",
        {"status": "hold_unresolved", "message_id": posted["message_id"]},
    )
    assert refused["decision"] == "refused"
    assert refused["reason"] == "dependency"
    assert tools.call("surface.inspect", {})["held"][0]["payload"]["depends_on"] == [
        "core.api"
    ]


@pytest.mark.parametrize(
    "name",
    ["", "../escape", "..\\escape", "a/b", "Upper", "trailing.", "con"],
)
def test_invalid_component_names_are_rejected_before_queueing(tmp_path: Path, name: str):
    tools = ToolRegistry(isolated_surface(tmp_path))
    result = tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {
                "name": name,
                "constraint": "unverified",
                "depends_on": [],
            },
        },
    )
    assert result == {"queued": False, "message_id": "", "reason": "invalid_payload"}
    assert tools.call("surface.inspect", {})["queued"] == 0


def test_partial_payload_artifact_is_rejected_before_queueing(tmp_path: Path):
    tools = ToolRegistry(isolated_surface(tmp_path))
    result = tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {
                "name": "edge.partial",
                "constraint": "unverified",
                "depends_on": [],
                "module": "pass\n",
            },
        },
    )
    assert result["queued"] is False
    assert result["reason"] == "invalid_payload"


def test_unverified_broken_baseline_cannot_be_admitted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GROKCELL_ALLOW_UNSANDBOXED_RUNNER", "1")
    tools = ToolRegistry(isolated_surface(tmp_path))
    assert propose(tools, name="edge.broken", tests="def test_nope():\n    assert False\n")[
        "queued"
    ]
    result = tools.call("bus.drain", {})["results"][0]
    assert result["status"] == "reject"
    assert result["reason"] == "runner_failed"
    assert tools.call("surface.inspect", {})["components"] == []


def test_collection_failure_is_not_a_killed_mutant(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GROKCELL_ALLOW_UNSANDBOXED_RUNNER", "1")
    tools = ToolRegistry(isolated_surface(tmp_path))
    propose(tools, name="edge.invalid", tests="def broken(:\n")
    result = tools.call("bus.drain", {})["results"][0]
    assert result["status"] == "reject"
    assert result["reason"] == "runner_infrastructure"


def test_runner_reports_missing_pytest_and_timeout(tmp_path: Path, monkeypatch):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_wait.py").write_text(
        "import time\n\ndef test_wait():\n    time.sleep(10)\n",
        encoding="utf-8",
    )
    timeout = pytest_suite(suite, timeout=0.01)
    assert timeout.outcome is RunOutcome.TIMEOUT

    monkeypatch.setattr("grokcell.runner._pytest_root", lambda: None)
    missing = pytest_suite(suite)
    assert missing.outcome is RunOutcome.INFRA_ERROR


def test_unbound_registry_cannot_call_any_mutator(tmp_path: Path):
    surface = isolated_surface(tmp_path)
    surface.post(
        Message(
            source_owner="MOUTH",
            kind="oda.spawn",
            priority=1,
            payload={"bot_name": "queued-owner"},
        )
    )
    tools = ToolRegistry(surface, bound_owner=None)
    before = surface.inspect()
    arguments = {
        "bus.post": {},
        "bus.drain": {},
        "park.request": {"act": "sign", "name": "core.api"},
        "oda.spawn": {"bot_name": "new-owner"},
        "oda.attach_skill": {"owner": "MOUTH", "skill": "x", "rail": "y"},
    }
    for name in MUTATING_TOOLS:
        assert tools.call(name, arguments[name])["reason"] == "unbound_session"
    assert surface.inspect() == before


def test_vault_notes_stay_under_the_configured_root(tmp_path: Path):
    first = ConstraintVault({}, root=tmp_path / "one")
    second = ConstraintVault({}, root=tmp_path / "two")
    first_path = first.record_note(status="reject", reason="one", message_id="m-0001")
    second_path = second.record_note(status="reject", reason="two", message_id="m-0001")
    assert first_path.parent == first.root / "claims"
    assert second_path.parent == second.root / "claims"
    assert first_path.read_text(encoding="utf-8").endswith("one\n")
    assert second_path.read_text(encoding="utf-8").endswith("two\n")


def test_storage_rejects_aliases_partial_artifacts_and_tampering(tmp_path: Path):
    fidelity = FidelityStore(tmp_path / "fidelity")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="invalid_component_name"):
        fidelity.path_for("..\\escaped")
    with pytest.raises(ValueError, match="invalid_component_name"):
        artifacts.path_for("a/b")

    partial = artifacts.root / "partial"
    partial.mkdir(parents=True)
    (partial / "service.py").write_text("pass\n", encoding="utf-8")
    assert artifacts.list() == []

    artifact = Artifact(
        name="edge.clean",
        files={"service.py": "def value():\n    return 1\n", "test_service.py": ""},
        source="payload",
    )
    dest = artifacts.materialize(artifact)
    (dest / "service.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    refused = artifacts.act(act="publish", name=artifact.name)
    assert refused["decision"] == "refused"
    assert refused["reason"] == "artifact_modified"


def test_artifact_paths_and_hashes_are_platform_independent(tmp_path: Path):
    source = "VALUE = 1\n"
    artifact = Artifact(
        name="edge.nested",
        files={"pkg\\nested.py": source},
        source="test",
    )
    assert artifact.files == {"pkg/nested.py": source}

    store = ArtifactStore(tmp_path / "artifacts")
    destination = store.materialize(artifact)
    assert (destination / "pkg" / "nested.py").read_text(encoding="utf-8") == source
    assert store._current_digest(destination) == artifact.digest()
    assert suite_hash(destination) == artifact.digest()


def test_invalid_utf8_artifact_is_reported_as_modified(tmp_path: Path):
    artifact = Artifact(
        name="edge.bytes",
        files={"service.py": "VALUE = 1\n"},
        source="test",
    )
    store = ArtifactStore(tmp_path / "artifacts")
    destination = store.materialize(artifact)
    (destination / "service.py").write_bytes(b"\xff")

    refused = store.act(act="publish", name=artifact.name)
    assert refused["decision"] == "refused"
    assert refused["reason"] == "artifact_modified"


def test_generated_python_requires_explicit_unsafe_opt_in(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GROKCELL_ALLOW_UNSANDBOXED_RUNNER", raising=False)
    tools = ToolRegistry(isolated_surface(tmp_path))
    propose(
        tools,
        name="edge.generated",
        tests="from service import ping\n\ndef test_ping():\n    assert ping() == 'pong'\n",
    )
    result = tools.call("bus.drain", {})["results"][0]
    assert result["status"] == "reject"
    assert result["reason"] == "runner_sandbox_required"


def test_runner_cannot_validate_different_bytes_than_are_committed(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("GROKCELL_ALLOW_UNSANDBOXED_RUNNER", "1")
    tools = ToolRegistry(isolated_surface(tmp_path))
    propose(
        tools,
        name="edge.rewriter",
        tests=(
            "from pathlib import Path\n\n"
            "def test_rewrite_source():\n"
            "    Path('service.py').write_text(\"def ping():\\n    return 'other'\\n\")\n"
        ),
    )
    result = tools.call("bus.drain", {})["results"][0]
    assert result["status"] == "reject"
    assert result["reason"] == "runner_modified_artifact"
    assert tools.call("surface.inspect", {})["components"] == []


def test_invalid_module_is_a_rejection_not_a_poisoned_queue(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GROKCELL_ALLOW_UNSANDBOXED_RUNNER", "1")
    tools = ToolRegistry(isolated_surface(tmp_path))
    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {
                "name": "edge.syntax",
                "constraint": "unverified",
                "depends_on": [],
                "module": "def broken(:\n",
                "tests": "def test_unrelated():\n    assert True\n",
            },
        },
    )
    result = tools.call("bus.drain", {})["results"][0]
    assert result["status"] == "reject"
    assert result["reason"] == "mutant_untestable"
    assert tools.call("surface.inspect", {})["queued"] == 0


def test_unresolved_dependency_does_not_execute_payload(tmp_path: Path, monkeypatch):
    tools = ToolRegistry(isolated_surface(tmp_path))
    monkeypatch.setattr(
        "grokcell.bus.run_path",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("runner called")),
    )
    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {
                "name": "edge.waiting",
                "constraint": "unverified",
                "depends_on": ["core.api"],
                "module": "def ping():\n    return 'pong'\n",
                "tests": "def test_placeholder():\n    assert True\n",
            },
        },
    )
    result = tools.call("bus.drain", {})["results"][0]
    assert result["status"] == "hold_unresolved"


def test_surface_snapshot_rejects_duplicate_or_inconsistent_message_ids():
    message = Message(
        source_owner="MOUTH",
        kind="oda.spawn",
        priority=1,
        payload={"bot_name": "edge-one"},
    ).with_identity("m-0001", 1)
    payload = SurfaceSnapshot(1, 0, [message], {message.message_id: message}).to_json()
    with pytest.raises(ValueError, match="message identities"):
        SurfaceSnapshot.from_json(payload)

    payload = SurfaceSnapshot(0, 0, [message], {}).to_json()
    with pytest.raises(ValueError, match="message identities"):
        SurfaceSnapshot.from_json(payload)


def test_spawn_owner_requires_an_exact_identifier(tmp_path: Path):
    surface = isolated_surface(tmp_path)
    refused = surface.spawn_owner(bot_name=" edge ")
    assert refused["decision"] == "refused"
    assert refused["reason"] == "invalid_owner_name"
    assert surface.owners() == ["MOUTH"]


def test_failed_persist_rolls_back_runtime_queue_audit_and_artifact(
    tmp_path: Path,
    monkeypatch,
):
    surface = scored_surface("core.api", "app.ui", root=tmp_path)
    tools = ToolRegistry(surface)
    for name in ("core.api", "app.ui"):
        tools.call(
            "bus.post",
            {
                "source_owner": "MOUTH",
                "kind": "forge.propose",
                "priority": 1,
                "payload": {
                    "name": name,
                    "constraint": "critical_module",
                    "depends_on": [],
                },
            },
        )
        if name == "core.api":
            assert tools.call("bus.drain", {})["results"][0]["status"] == "admit"

    before = surface.inspect()
    event_log = copy.deepcopy(surface.runtime.event_log)
    monkeypatch.setattr(
        surface.snapshots,
        "save",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError, match="disk full"):
        surface.drain()

    assert surface.inspect() == before
    assert surface.runtime.event_log == event_log
    assert not (tmp_path / "state" / "artifacts" / "app.ui").exists()


def test_multiple_admits_preserve_prior_audit_events(tmp_path: Path):
    surface = scored_surface("core.api", "app.ui", root=tmp_path)
    tools = ToolRegistry(surface)
    prior = []
    for name in ("core.api", "app.ui"):
        tools.call(
            "bus.post",
            {
                "source_owner": "MOUTH",
                "kind": "forge.propose",
                "priority": 1,
                "payload": {
                    "name": name,
                    "constraint": "critical_module",
                    "depends_on": [],
                },
            },
        )
        assert tools.call("bus.drain", {})["results"][0]["status"] == "admit"
        assert surface.runtime.event_log[: len(prior)] == prior
        prior = copy.deepcopy(surface.runtime.event_log)
    assert [record.event_index for record in prior] == [1, 2, 3, 4]


def test_snapshot_manifest_detects_tampering_and_prunes_old_generations(tmp_path: Path):
    surface = isolated_surface(tmp_path)
    for name in ("edge-one", "edge-two", "edge-three"):
        assert surface.spawn_owner(bot_name=name)["decision"] == "accepted"
    state = tmp_path / "state"
    assert len(list(state.glob("kernel-*.osahr.gz"))) == 2
    assert len(list(state.glob("surface-*.json"))) == 2

    manifest = json.loads((state / "CURRENT.json").read_text(encoding="utf-8"))
    saved_surface = state / manifest["surface"]
    saved_surface.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        GrokCellSurface.open(
            vault=surface.vault,
            fidelity=surface.fidelity,
            state=state,
        )


def test_snapshot_manifest_rejects_non_uuid_generation(tmp_path: Path):
    store = SnapshotStore(tmp_path / "state")
    store.current_path.write_text(
        json.dumps(
            {
                "version": 1,
                "generation": "../outside",
                "kernel": "kernel-../outside.osahr.gz",
                "surface": "surface-../outside.json",
                "kernel_sha256": "0" * 64,
                "surface_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="incomplete"):
        store.load_pair()


def test_snapshot_store_rejects_concurrent_lock_holder(tmp_path: Path):
    first = SnapshotStore(tmp_path / "state")
    second = SnapshotStore(tmp_path / "state")
    with first.locked():
        with pytest.raises(RuntimeError, match="locked by another writer"):
            with second.locked():
                pass


def test_snapshot_store_rejects_stale_writer(tmp_path: Path):
    first = SnapshotStore(tmp_path / "state")
    second = SnapshotStore(tmp_path / "state")
    assert first.load_pair() is None
    assert second.load_pair() is None
    runtime = build_runtime()
    surface = SurfaceSnapshot(seq=0, inject_seq=0, queued=[], held={})

    first.save(runtime, surface)
    with pytest.raises(RuntimeError, match="changed since it was loaded"):
        second.save(runtime, surface)


def test_missing_current_never_falls_back_after_generation_save(tmp_path: Path):
    store = SnapshotStore(tmp_path / "state")
    assert store.load_pair() is None
    store.save(
        build_runtime(),
        SurfaceSnapshot(seq=0, inject_seq=0, queued=[], held={}),
    )
    assert not store.kernel_path.exists()
    assert not store.surface_path.exists()

    store.current_path.unlink()
    with pytest.raises(ValueError, match="incomplete"):
        SnapshotStore(store.root).load_pair()


def test_complete_legacy_pair_survives_orphaned_migration_generation(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "state")
    store.root.mkdir(parents=True, exist_ok=True)
    runtime = build_runtime()
    saved = SurfaceSnapshot(seq=0, inject_seq=0, queued=[], held={})
    save_checkpoint(store.kernel_path, runtime.snapshot())
    store.surface_path.write_text(
        json.dumps(saved.to_json()) + "\n",
        encoding="utf-8",
    )
    (store.root / f"kernel-{'a' * 32}.osahr.gz").write_bytes(b"partial")

    pair = store.load_pair()
    assert pair is not None
    store.save(runtime, saved)
    assert store.current_path.is_file()
    assert not store.kernel_path.exists()
    assert not store.surface_path.exists()
    assert not (store.root / f"kernel-{'a' * 32}.osahr.gz").exists()


def test_same_surface_concurrent_owner_registration_is_atomic(tmp_path: Path):
    surface = isolated_surface(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _: surface.spawn_owner(bot_name="edge-concurrent"),
                range(8),
            )
        )

    assert sum(result["decision"] == "accepted" for result in results) == 1
    assert surface.owners().count("edge-concurrent") == 1


def test_same_surface_concurrent_skill_updates_do_not_get_lost(tmp_path: Path):
    surface = isolated_surface(tmp_path)
    assert surface.spawn_owner(bot_name="edge-skills")["decision"] == "accepted"
    names = [f"skill-{index}" for index in range(8)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda name: surface.attach_skill(
                    owner="edge-skills",
                    skill=name,
                    rail="test",
                ),
                names,
            )
        )

    assert all(result["decision"] == "accepted" for result in results)
    assert set(surface.runtime.memory["skills"]["edge-skills"]) == set(names)
