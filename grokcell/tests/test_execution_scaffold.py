"""Offline contract tests. No model, sandbox, or production evidence is implied."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace

import pytest

from grokcell.execution import (ActionOffer, CheckContract, CheckResult, Evidence,
                               ExecutionBlocked, JsonSnapshot, Limits, OutcomeUnknown,
                               Permission, PreviewRuntime, Reply)
from grokcell.execution.examples import (REPAIR, FixtureChooser, FixtureWorker,
                                        RepairFixtureVerifier, demo_runtime,
                                        dependency_workflow, repair_workflow)


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


def make_runtime(*, chooser=None, worker=None, verifier=None, limits=Limits(), effects=None):
    clock = Clock()
    permission = Permission("grant", "operator", effects or (
        "read", "decide", "generate", "check", "admit", "yield"), 150.0)
    runtime = PreviewRuntime(permission=permission, dependencies=JsonSnapshot.capture({"fixture": 1}),
                             chooser=chooser or FixtureChooser("repair"),
                             workers={"generate": worker or FixtureWorker(REPAIR)},
                             verifier=verifier or RepairFixtureVerifier(), limits=limits, clock=clock)
    return runtime, clock


def prepared(runtime):
    observation = runtime.read("input", JsonSnapshot.capture({"failure": "wrong sum"}))
    decision = runtime.decide("route", observation, (ActionOffer("repair", "generate", "add"),))
    return observation, decision


def candidate_for(runtime):
    observation, decision = prepared(runtime)
    return runtime.call("proposal", observation, decision, JsonSnapshot.capture({"task": "repair"}),
                        artifact_type="python_component")


def test_snapshot_owns_nested_values_and_canonical_bytes():
    source = {"a": [{"b": 1}]}
    value = JsonSnapshot.capture(source)
    source["a"][0]["b"] = 2
    value.value()["a"].append(3)
    assert value.value() == {"a": [{"b": 1}]}
    assert value == JsonSnapshot.capture({"a": [{"b": 1}]})
    with pytest.raises(FrozenInstanceError):
        value.raw = b"null"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1: "x"}, {"x": object()}, (1, 2)])
def test_unsupported_json_refused(value):
    with pytest.raises((ValueError, TypeError)):
        JsonSnapshot.capture(value)


@pytest.mark.parametrize("raw", [b'{"b":2, "a":1}', b'{"a":1,"a":2}', b'NaN', b'bad'])
def test_noncanonical_snapshots_refused(raw):
    with pytest.raises(ValueError):
        JsonSnapshot(raw)


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_resource_limits_are_positive_integers(value):
    with pytest.raises(ValueError):
        Limits(max_calls=value)


def test_free_reply_allowed_but_invalid_cost_refused():
    assert Reply("repair", 0).actual_microusd == 0
    for cost in (-1, True, 0.5, float("nan")):
        with pytest.raises(ValueError):
            Reply("repair", cost)


def test_permission_copies_effects_and_rejects_bad_expiry():
    effects = ["read"]
    permission = Permission("p", "owner", effects, 150)
    effects.append("admit")
    assert permission.effects == ("read",)
    with pytest.raises(ValueError):
        replace(permission, expires_at=float("nan"))


@pytest.mark.parametrize("name,workflow", [("repair", repair_workflow), ("dependency", dependency_workflow)])
def test_two_workflows_replay_without_new_calls_or_admissions(name, workflow, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network forbidden"))
    runtime = demo_runtime(name)
    first = workflow(runtime)
    second = workflow(runtime)
    assert first == second
    audit = runtime.audit()
    assert audit["revision"] == 1 and audit["calls"] == 2
    assert audit["durable"] is False and audit["live_execution_enabled"] is False
    assert first.assurance == "offline_preview"


def test_replay_rejects_changed_inputs():
    runtime, _ = make_runtime()
    runtime.read("read", JsonSnapshot.capture({"n": 1}))
    with pytest.raises(ExecutionBlocked, match="replay input"):
        runtime.read("read", JsonSnapshot.capture({"n": 2}))


def test_arbitrary_decision_cannot_expand_authority():
    runtime, _ = make_runtime(chooser=FixtureChooser("deploy"))
    with pytest.raises(ExecutionBlocked, match="outside permitted"):
        prepared(runtime)
    assert runtime.audit()["revision"] == 0


def test_offer_must_fit_permission():
    runtime, _ = make_runtime()
    observation = runtime.read("input", JsonSnapshot.capture({}))
    with pytest.raises(ExecutionBlocked, match="exceeds permission"):
        runtime.decide("route", observation, (ActionOffer("deploy", "deploy", "production"),))


def test_live_adapters_are_not_enabled_by_environment(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "not-a-real-key")
    class Live(FixtureChooser):
        mode = "live"
    with pytest.raises(ExecutionBlocked, match="live adapters"):
        make_runtime(chooser=Live("repair"))


def test_forged_evidence_cannot_admit():
    runtime, _ = make_runtime()
    candidate = candidate_for(runtime)
    forged = Evidence(candidate.identity, "forged", "verifier", "env", (CheckResult("x", "pass"),))
    with pytest.raises(ExecutionBlocked, match="not issued"):
        runtime.admit("admit", candidate, forged)
    evidence = runtime.check("check", candidate)
    with pytest.raises(ExecutionBlocked, match="not issued"):
        runtime.admit("admit", candidate, replace(evidence, environment_hash="different"))
    assert runtime.audit()["revision"] == 0


@pytest.mark.parametrize("results", [(), (CheckResult("other", "pass"),),
                                    (CheckResult("expected_bytes", "pass"),) * 2])
def test_missing_extra_duplicate_checks_do_not_issue_evidence(results):
    class BadVerifier(RepairFixtureVerifier):
        def verify(self, candidate):
            return results
    runtime, _ = make_runtime(verifier=BadVerifier())
    with pytest.raises(ExecutionBlocked, match="mandatory checks"):
        runtime.check("check", candidate_for(runtime))


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_nonpassing_mandatory_checks_refuse_admission(status):
    class Nonpassing(RepairFixtureVerifier):
        def verify(self, candidate):
            return (CheckResult("expected_bytes", status),)
    runtime, _ = make_runtime(verifier=Nonpassing())
    candidate = candidate_for(runtime)
    evidence = runtime.check("check", candidate)
    with pytest.raises(ExecutionBlocked, match="did not pass"):
        runtime.admit("admit", candidate, evidence)


def test_empty_contract_rejected():
    with pytest.raises(ValueError):
        CheckContract("c", "v", "e", ())


def test_dependency_fixture_change_invalidates_existing_evidence():
    runtime, _ = make_runtime()
    candidate = candidate_for(runtime)
    evidence = runtime.check("check", candidate)
    runtime.replace_dependencies(JsonSnapshot.capture({"fixture": 2, "data.csv": "changed"}))
    with pytest.raises(ExecutionBlocked, match="dependency snapshot"):
        runtime.admit("admit", candidate, evidence)


@pytest.mark.parametrize("action", ["cancel", "revoke", "expire"])
def test_current_authority_checked_at_admission(action):
    runtime, clock = make_runtime()
    candidate = candidate_for(runtime)
    evidence = runtime.check("check", candidate)
    if action == "expire":
        clock.now = 200
    else:
        getattr(runtime, action)()
    with pytest.raises(ExecutionBlocked):
        runtime.admit("admit", candidate, evidence)
    assert runtime.audit()["revision"] == 0


def test_second_admission_with_old_revision_refused():
    runtime, _ = make_runtime()
    candidate = candidate_for(runtime)
    evidence = runtime.check("check", candidate)
    first = runtime.admit("admit", candidate, evidence)
    assert runtime.admit("admit", candidate, evidence) == first
    with pytest.raises(ExecutionBlocked, match="stale"):
        runtime.admit("another-admit", candidate, evidence)


def test_interrupted_request_retains_reservation_and_never_resends():
    class Crash(BaseException):
        pass
    class Interrupted(FixtureWorker):
        def propose(self, request):
            raise Crash()
    runtime, _ = make_runtime(worker=Interrupted(REPAIR))
    observation, decision = prepared(runtime)
    kwargs = dict(artifact_type="python_component", reserve_microusd=100)
    with pytest.raises(Crash):
        runtime.call("proposal", observation, decision, JsonSnapshot.capture({}), **kwargs)
    with pytest.raises(OutcomeUnknown):
        runtime.call("proposal", observation, decision, JsonSnapshot.capture({}), **kwargs)
    assert runtime.audit()["calls"] == 2
    assert runtime.audit()["liability_microusd"] == 100


def test_unknown_but_bounded_cost_does_not_reset_budget():
    class MissingUsage(FixtureWorker):
        def propose(self, request):
            return Reply(REPAIR, None)
    runtime, _ = make_runtime(worker=MissingUsage(REPAIR), limits=Limits(max_microusd=100))
    observation, decision = prepared(runtime)
    runtime.call("one", observation, decision, JsonSnapshot.capture({}),
                 artifact_type="python_component", reserve_microusd=70)
    with pytest.raises(ExecutionBlocked, match="budget"):
        runtime.call("two", observation, decision, JsonSnapshot.capture({}),
                     artifact_type="python_component", reserve_microusd=31)
    runtime.call("two", observation, decision, JsonSnapshot.capture({}),
                 artifact_type="python_component", reserve_microusd=30)
    assert runtime.audit()["liability_microusd"] == 100


def test_over_reservation_charge_blocks_further_effects():
    class Overcharged(FixtureWorker):
        def propose(self, request):
            return Reply(REPAIR, 101)
    runtime, _ = make_runtime(worker=Overcharged(REPAIR))
    observation, decision = prepared(runtime)
    with pytest.raises(ExecutionBlocked, match="bound breached"):
        runtime.call("proposal", observation, decision, JsonSnapshot.capture({}),
                     artifact_type="python_component", reserve_microusd=100)
    assert runtime.audit()["liability_microusd"] == 101
    with pytest.raises(ExecutionBlocked):
        runtime.read("more", JsonSnapshot.capture({}))


def test_late_result_kept_for_audit_but_cannot_admit():
    runtime, _ = make_runtime()
    class Canceling(FixtureWorker):
        def propose(self, request):
            runtime.cancel()
            return Reply(REPAIR)
    runtime._workers["generate"] = Canceling(REPAIR)
    observation, decision = prepared(runtime)
    with pytest.raises(ExecutionBlocked, match="canceled"):
        runtime.call("proposal", observation, decision, JsonSnapshot.capture({}),
                     artifact_type="python_component")
    assert runtime.audit()["journal"][-1]["status"] == "complete"
    assert runtime.audit()["revision"] == 0


def test_steps_and_calls_and_bytes_have_separate_limits():
    runtime, _ = make_runtime(limits=Limits(max_steps=1))
    runtime.read("one", JsonSnapshot.capture({}))
    with pytest.raises(ExecutionBlocked, match="step limit"):
        runtime.read("two", JsonSnapshot.capture({}))
    runtime, _ = make_runtime(limits=Limits(max_calls=1))
    observation, decision = prepared(runtime)
    with pytest.raises(ExecutionBlocked, match="call limit"):
        runtime.call("proposal", observation, decision, JsonSnapshot.capture({}), artifact_type="python")
    runtime, _ = make_runtime(limits=Limits(max_bytes=2))
    with pytest.raises(ExecutionBlocked, match="byte limit"):
        runtime.read("one", JsonSnapshot.capture({"long": "value"}))


def test_yield_requires_explicit_same_process_resume():
    runtime, _ = make_runtime()
    runtime.yield_("pause", "operator review")
    with pytest.raises(ExecutionBlocked, match="yielded"):
        runtime.read("read", JsonSnapshot.capture({}))
    runtime.resume()
    runtime.read("read", JsonSnapshot.capture({}))
    runtime.cancel()
    runtime.resume()
    with pytest.raises(ExecutionBlocked, match="canceled"):
        runtime.read("new", JsonSnapshot.capture({}))


def test_contract_change_refuses_admission():
    verifier = RepairFixtureVerifier()
    runtime, _ = make_runtime(verifier=verifier)
    candidate = candidate_for(runtime)
    evidence = runtime.check("check", candidate)
    verifier.contract = replace(verifier.contract, id="weakened-contract")
    with pytest.raises(ExecutionBlocked, match="contract changed"):
        runtime.admit("admit", candidate, evidence)


def test_offline_cli_and_lazy_parent_import():
    result = subprocess.run([sys.executable, "-m", "grokcell.execution", "dependency", "--replay"],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["calls"] == 2
    import grokcell
    assert "GrokCellSurface" in dir(grokcell)
    with pytest.raises(AttributeError):
        getattr(grokcell, "not_an_export")


def test_legacy_exports_when_full_repository_is_present():
    pytest.importorskip("osahr", reason="local sparse checkout lacks kernel; CI uses full repository")
    import grokcell
    for name in grokcell.__all__:
        assert getattr(grokcell, name) is not None
    assert grokcell.GrokCellSurface is importlib.import_module("grokcell.surface").GrokCellSurface


def test_changed_reservation_is_a_replay_mismatch():
    runtime, _ = make_runtime()
    observation = runtime.read("input", JsonSnapshot.capture({}))
    offers = (ActionOffer("repair", "generate", "add"),)
    runtime.decide("route", observation, offers, reserve_microusd=10)
    with pytest.raises(ExecutionBlocked, match="replay input"):
        runtime.decide("route", observation, offers, reserve_microusd=20)


@pytest.mark.parametrize("now", [99.0, float("nan"), float("inf")])
def test_clock_regression_or_nonfinite_time_fails_closed(now):
    runtime, clock = make_runtime()
    clock.now = now
    with pytest.raises(ExecutionBlocked):
        runtime.read("read", JsonSnapshot.capture({}))


def test_wrong_candidate_cannot_use_edited_passing_evidence():
    runtime, _ = make_runtime(worker=FixtureWorker(b"def add(a, b): return 0"))
    candidate = candidate_for(runtime)
    evidence = runtime.check("check", candidate)
    with pytest.raises(ExecutionBlocked, match="did not pass"):
        runtime.admit("admit", candidate, evidence)
    forged = replace(evidence, checks=(CheckResult("expected_bytes", "pass"),))
    with pytest.raises(ExecutionBlocked, match="not issued"):
        runtime.admit("admit", candidate, forged)
