"""Real local filesystem/process tests, not live-provider or sandbox evidence."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from grokcell.execution.codec import decode, encode
from grokcell.execution.durable import DurableRuntime, control, inspect_state
from grokcell.execution.examples import (FixtureChooser, FixtureWorker, REPAIR,
                                        RepairFixtureVerifier, repair_workflow)
from grokcell.execution.records import ActionOffer, JsonSnapshot, Limits, Permission
from grokcell.execution.runtime import ExecutionBlocked, OutcomeUnknown
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
