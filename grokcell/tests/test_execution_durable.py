"""Real local filesystem/process tests, not live-provider or sandbox evidence."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from grokcell.execution.codec import decode, encode
from grokcell.execution import durable as durable_module
from grokcell.execution import runtime as runtime_module
from grokcell.execution.durable import DurableRuntime, configuration, control, inspect_state
from grokcell.execution.examples import (FixtureChooser, FixtureWorker, REPAIR,
                                        RepairFixtureVerifier, repair_workflow)
from grokcell.execution.ports import ObservedReplyError
from grokcell.execution.providers import ProviderConfig, _metadata
from grokcell.execution.records import ActionOffer, JsonSnapshot, Limits, Permission, digest
from grokcell.execution.runtime import ExecutionBlocked, OutcomeUnknown, PreviewRuntime
from grokcell import snapshot as grokcell_snapshot
from grokcell.snapshot import SnapshotStore

PERMISSION = Permission("durable-test", "operator", ("read", "decide", "generate", "check", "admit", "yield"), 2_000_000_000)


def open_run(path, **kwargs):
    values = dict(state_dir=path, run_id="run", workflow_id="repair-v1", permission=PERMISSION,
                  dependencies=JsonSnapshot.capture({"data.csv": "v1"}), chooser=FixtureChooser("repair"),
                  workers={"generate": FixtureWorker(REPAIR)}, verifier=RepairFixtureVerifier(),
                  limits=Limits(max_seconds=600))
    values.update(kwargs)
    return DurableRuntime(**values)


def prepare(runtime):
    observation = runtime.read("input", JsonSnapshot.capture({"failure": "sum wrong"}))
    decision = runtime.decide("route", observation, (ActionOffer("repair", "generate", "add"),))
    return observation, decision


def test_restart_replays_without_new_callbacks(tmp_path):
    with open_run(tmp_path) as runtime:
        first = repair_workflow(runtime)
    with open_run(tmp_path) as runtime:
        assert repair_workflow(runtime) == first
        assert runtime.audit()["calls"] == 2
        assert runtime.audit()["revision"] == 1
        assert runtime.audit()["durable"] is True
        assert [row["step"] for row in runtime.audit()["journal"]] == ["input", "route", "proposal", "verification", "admission"]


def test_codec_has_no_arbitrary_class_import():
    with pytest.raises(ValueError):
        decode({"$record": "os.system", "fields": {}})
    with pytest.raises(ValueError):
        decode({"$bytes": "!!!"})
    assert decode(encode(PERMISSION)) == PERMISSION


@pytest.mark.parametrize("change", [dict(workflow_id="changed"), dict(run_id="different"),
                                    dict(limits=Limits(max_seconds=601)),
                                    dict(permission=replace(PERMISSION, epoch=1))])
def test_configuration_change_cannot_reset_accounting(tmp_path, change):
    with open_run(tmp_path) as runtime:
        repair_workflow(runtime)
    with pytest.raises(ExecutionBlocked, match="configuration"):
        open_run(tmp_path, **change)


@pytest.mark.parametrize("changed_file", ["providers.py", "http_worker.py", "../snapshot.py",
                                           "workflows.py", "examples.py"])
def test_restart_identity_tracks_provider_and_snapshot_implementations(monkeypatch, changed_file):
    values = dict(run_id="run", workflow_id="repair-v1", permission=PERMISSION,
                  dependencies=JsonSnapshot.capture({"data.csv": "v1"}),
                  limits=Limits(max_seconds=600), chooser=FixtureChooser("repair"),
                  workers={"generate": FixtureWorker(REPAIR)}, verifier=RepairFixtureVerifier())
    before = configuration(**values)
    target = (Path(durable_module.__file__).parent / changed_file).resolve()
    original = Path.read_bytes

    def updated_bytes(path):
        raw = original(path)
        return raw + b"\n# simulated installed implementation update\n" if path.resolve() == target else raw

    monkeypatch.setattr(Path, "read_bytes", updated_bytes)
    after = configuration(**values)
    assert digest(after) != digest(before), f"Changed {changed_file} is invisible to restart identity"


def test_second_coordinator_cannot_enter(tmp_path):
    with open_run(tmp_path):
        with pytest.raises(RuntimeError, match="locked"):
            open_run(tmp_path)


@pytest.mark.parametrize("action", ["cancel", "revoke"])
def test_operator_control_survives_restart(tmp_path, action):
    with open_run(tmp_path) as runtime:
        prepare(runtime)
    control(tmp_path, action)
    with open_run(tmp_path) as runtime:
        with pytest.raises(ExecutionBlocked, match="canceled or revoked"):
            prepare(runtime)
        assert runtime.audit()["calls"] == 1


def test_cancel_while_callback_is_running_prevents_late_commit(tmp_path):
    class Canceling(FixtureWorker):
        def propose(self, request):
            control(tmp_path, "cancel")
            return super().propose(request)
    with open_run(tmp_path, workers={"generate": Canceling(REPAIR)}) as runtime:
        obs, choice = prepare(runtime)
        with pytest.raises(RuntimeError, match="changed since"):
            runtime.call("proposal", obs, choice, JsonSnapshot.capture({}),
                         artifact_type="python_component", reserve_microusd=30)
        assert runtime.audit()["faulted"]
    with open_run(tmp_path) as runtime:
        assert runtime.audit()["canceled"]
        assert runtime.audit()["revision"] == 0
        assert runtime.audit()["liability_microusd"] == 30


def test_unknown_liability_retained_on_restart(tmp_path):
    class Broken(FixtureWorker):
        def propose(self, request):
            raise TimeoutError("transport uncertain")
    with open_run(tmp_path, workers={"generate": Broken(REPAIR)}) as runtime:
        obs, choice = prepare(runtime)
        with pytest.raises(TimeoutError):
            runtime.call("proposal", obs, choice, JsonSnapshot.capture({}),
                         artifact_type="python_component", reserve_microusd=50)
    with open_run(tmp_path) as runtime:
        obs, choice = prepare(runtime)
        with pytest.raises(OutcomeUnknown):
            runtime.call("proposal", obs, choice, JsonSnapshot.capture({}),
                         artifact_type="python_component", reserve_microusd=50)
        assert runtime.audit()["liability_microusd"] == 50
        assert runtime.audit()["calls"] == 2


def test_invalid_huggingface_content_keeps_observed_billing_and_breach():
    config = ProviderConfig("hf", "org/model:novita", ("org/model",),
                            1_000_000, 1_000_000, 20, 10, 10)
    response = {"model": "org/model", "usage": {"prompt_tokens": 100, "completion_tokens": 100},
                "choices": [{"message": {"content": "not valid JSON"}}]}

    class MalformedHuggingFaceResponse:
        id = "offline-hf-malformed-response"
        mode = "offline"
        reservation_microusd = config.max_charge_microusd

        def propose(self, _request):
            # Model the adapter boundary after usage metadata is available. The
            # malformed body and billing estimate are entirely in memory.
            actual, metadata = _metadata(config, response, "audit-request", 1)
            try:
                json.loads(response["choices"][0]["message"]["content"])
            except (ValueError, UnicodeError):
                raise ObservedReplyError("invalid provider content", actual,
                                         JsonSnapshot.capture(metadata)) from None
            raise AssertionError("fixture content unexpectedly parsed")

    values = dict(permission=PERMISSION, dependencies=JsonSnapshot.capture({"data.csv": "v1"}),
                  chooser=FixtureChooser("repair"),
                  workers={"generate": MalformedHuggingFaceResponse()},
                  verifier=RepairFixtureVerifier(), limits=Limits(max_seconds=600), clock=lambda: 1)
    config_values = {key: value for key, value in values.items() if key != "clock"}

    class CheckpointRuntime(PreviewRuntime):
        def __init__(self):
            super().__init__(**values)
            self._config = configuration(run_id="run", workflow_id="repair-v1", **config_values)
            self._config_hash = digest(self._config)
            self.saved = None

        def _checkpoint(self, _stage):
            self.saved = copy.deepcopy(DurableRuntime._document(self))

    runtime = CheckpointRuntime()
    observation = runtime.read("input", JsonSnapshot.capture({"task": "fixture"}))
    decision = runtime.decide("route", observation,
                              (ActionOffer("repair", "generate", "fixture"),))
    with pytest.raises(ObservedReplyError):
        runtime.call("proposal", observation, decision, JsonSnapshot.capture({}),
                     artifact_type="python_component")
    restored = CheckpointRuntime()
    DurableRuntime._restore(restored, runtime.saved)
    audit = restored.audit()
    proposal = next(row for row in audit["journal"] if row["step"] == "proposal")
    assert audit["bound_breached"] is True
    assert audit["liability_microusd"] == 200
    assert proposal["status"] == "outcome_unknown"
    assert proposal["actual"] == 200
    assert proposal["provider"]["estimated_microusd"] == 200
    assert proposal["provider"]["limits_breached"] is True


def test_admission_and_local_checkpoint_are_atomic(monkeypatch):
    values = dict(permission=PERMISSION, dependencies=JsonSnapshot.capture({"data.csv": "v1"}),
                  chooser=FixtureChooser("repair"), workers={"generate": FixtureWorker(REPAIR)},
                  verifier=RepairFixtureVerifier(), limits=Limits(max_seconds=600), clock=lambda: 1)
    config_values = {key: value for key, value in values.items() if key != "clock"}
    operator_entered = threading.Event()
    dependency_checkpointed = threading.Event()

    class CheckpointRuntime(PreviewRuntime):
        def __init__(self):
            super().__init__(**values)
            self._config = configuration(run_id="run", workflow_id="repair-v1", **config_values)
            self._config_hash = digest(self._config)
            self.saved = None

        def _checkpoint(self, stage):
            self.saved = copy.deepcopy(DurableRuntime._document(self))
            if stage == "dependencies":
                dependency_checkpointed.set()

        def replace_dependencies(self, dependencies):
            if threading.current_thread().name == "operator-checkpoint":
                operator_entered.set()
            return super().replace_dependencies(dependencies)

    class ProcessCrash(BaseException):
        pass

    runtime = CheckpointRuntime()
    original_integer = runtime_module.integer
    operators = []
    interrupted = []

    def checkpoint_between_admission_and_receipt(value, **kwargs):
        original_integer(value, **kwargs)
        row = runtime._journal.get("admission", {})
        if value == 0 and runtime._revision == 1 and row.get("status") == "started" and not interrupted:
            interrupted.append(True)
            operator = threading.Thread(target=runtime.replace_dependencies,
                                        args=(runtime._dependencies,), name="operator-checkpoint")
            operators.append(operator)
            operator.start()
            assert operator_entered.wait(timeout=2)
            if dependency_checkpointed.wait(timeout=0.5):
                operator.join(timeout=2)
                assert not operator.is_alive()
                runtime._faulted = True
                raise ProcessCrash()

    monkeypatch.setattr(runtime_module, "integer", checkpoint_between_admission_and_receipt)
    try:
        repair_workflow(runtime)
    except ProcessCrash:
        pass
    for operator in operators:
        operator.join(timeout=2)
        assert not operator.is_alive()
    restored = CheckpointRuntime()
    DurableRuntime._restore(restored, runtime.saved)
    assert restored.audit()["revision"] == 1
    assert repair_workflow(restored) == restored._accepted[0]


def test_dependency_invalidation_is_persistent(tmp_path):
    with open_run(tmp_path) as runtime:
        repair_workflow(runtime)
        runtime.replace_dependencies(JsonSnapshot.capture({"data.csv": "v2"}))
    with open_run(tmp_path) as runtime:
        assert runtime.audit()["accepted"][0]["currently_applicable"] is False


def test_clock_deadline_does_not_restart(tmp_path):
    with open_run(tmp_path, clock=lambda: 100.0) as runtime:
        prepare(runtime)
    with open_run(tmp_path, clock=lambda: 701.0) as runtime:
        with pytest.raises(ExecutionBlocked, match="expired"):
            prepare(runtime)
    with open_run(tmp_path, clock=lambda: 99.0) as runtime:
        with pytest.raises(ExecutionBlocked, match="regressed"):
            prepare(runtime)


def test_checkpoint_tamper_missing_pointer_and_legacy_refused(tmp_path):
    with open_run(tmp_path) as runtime:
        prepare(runtime)
    manifest = json.loads((tmp_path / "CURRENT.json").read_text())
    file = tmp_path / manifest["execution"]
    original = file.read_bytes()
    file.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="checksum"):
        open_run(tmp_path)
    file.write_bytes(original)
    (tmp_path / "CURRENT.json").unlink()
    with pytest.raises(ValueError, match="missing CURRENT"):
        open_run(tmp_path)


def test_execution_root_cannot_be_opened_as_legacy_pair(tmp_path):
    with open_run(tmp_path):
        pass
    with pytest.raises(ValueError, match="incomplete"):
        SnapshotStore(tmp_path).load_pair()


def test_legacy_root_cannot_be_implicitly_converted(tmp_path):
    (tmp_path / "CURRENT.json").write_text('{"version":1}')
    with pytest.raises(ValueError, match="another format"):
        open_run(tmp_path)


@pytest.mark.parametrize("kernel_name,surface_name", [
    ("kernel.osahr.gz", "surface.json"),
    ("kernel-" + "0" * 32 + ".osahr.gz", "surface-" + "0" * 32 + ".json"),
])
def test_execution_root_rejects_legacy_snapshot_files(tmp_path, kernel_name, surface_name):
    store = SnapshotStore(tmp_path)
    assert store.load_execution() is None
    store.save_execution({"execution": "current"})
    (tmp_path / kernel_name).write_bytes(b"legacy kernel")
    (tmp_path / surface_name).write_text("{}")

    with pytest.raises(ValueError, match="mixed state formats"):
        store.load_execution()


def test_legacy_snapshot_save_syncs_written_files(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path)
    assert store.load_pair() is None

    def write_checkpoint(path, _runtime):
        path.write_bytes(b"trusted legacy checkpoint fixture")

    class Runtime:
        def snapshot(self):
            return {}

    monkeypatch.setattr(grokcell_snapshot, "save_checkpoint", write_checkpoint)
    surface = grokcell_snapshot.SurfaceSnapshot(0, 0, [], {})

    store.save(Runtime(), surface)

    assert store.current_path.is_file()


def test_stale_generation_compare_and_swap(tmp_path):
    a, b = SnapshotStore(tmp_path), SnapshotStore(tmp_path)
    assert a.load_execution() is None
    assert b.load_execution() is None
    a.save_execution({"counter": 1})
    with pytest.raises(RuntimeError, match="changed since"):
        b.save_execution({"counter": 2})
    assert a.load_execution() == {"counter": 1}


def test_shared_or_symlink_state_root_refused(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="0700"):
        open_run(shared)
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        open_run(link)


_CHILD = r'''
import os, sys
from pathlib import Path
from grokcell.execution.durable import DurableRuntime
from grokcell.execution.examples import FixtureChooser, FixtureWorker, RepairFixtureVerifier, REPAIR, repair_workflow
from grokcell.execution.records import JsonSnapshot, Limits, Permission
root, stage = Path(sys.argv[1]), sys.argv[2]
class Worker(FixtureWorker):
    def propose(self, request):
        with (root.parent / "dispatches.txt").open("a") as handle:
            handle.write("sent\n")
            handle.flush()
            os.fsync(handle.fileno())
        return super().propose(request)
class CrashRuntime(DurableRuntime):
    def _checkpoint(self, point):
        journal = self._journal
        proposal = journal.get("proposal", {})
        admission = journal.get("admission", {})
        if stage == "response_not_committed" and point == "complete" and proposal.get("status") == "complete":
            os._exit(73)
        if stage == "admission_not_committed" and point == "complete" and admission.get("status") == "complete":
            os._exit(73)
        super()._checkpoint(point)
        if stage == "intent_only" and point == "intent" and proposal.get("status") == "started":
            os._exit(73)
        if stage == "response_committed" and point == "complete" and proposal.get("status") == "complete":
            os._exit(73)
permission = Permission("durable-test", "operator", ("read","decide","generate","check","admit","yield"), 2000000000)
with CrashRuntime(state_dir=root,run_id="run",workflow_id="repair-v1",permission=permission,
    dependencies=JsonSnapshot.capture({"data.csv":"v1"}),chooser=FixtureChooser("repair"),
    workers={"generate":Worker(REPAIR)},verifier=RepairFixtureVerifier(),limits=Limits(max_seconds=600)) as rt:
    repair_workflow(rt)
'''


@pytest.mark.parametrize("stage,expected_calls,recoverable", [
    ("intent_only", 0, False), ("response_not_committed", 1, False),
    ("response_committed", 1, True), ("admission_not_committed", 1, True)])
def test_real_process_crash_windows(tmp_path, stage, expected_calls, recoverable):
    state = tmp_path / "state"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, "-c", _CHILD, str(state), stage],
                            env=env, capture_output=True, timeout=15)
    assert result.returncode == 73, result.stderr.decode()
    trace = tmp_path / "dispatches.txt"
    assert (len(trace.read_text().splitlines()) if trace.exists() else 0) == expected_calls
    with open_run(state) as runtime:
        if recoverable:
            assert repair_workflow(runtime).revision == 1
            assert runtime.audit()["calls"] == 2
        else:
            with pytest.raises(OutcomeUnknown):
                repair_workflow(runtime)
            assert runtime.audit()["revision"] == 0
    assert (len(trace.read_text().splitlines()) if trace.exists() else 0) == expected_calls
