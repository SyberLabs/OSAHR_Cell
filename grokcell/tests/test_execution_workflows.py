"""Safe fixture coverage for the bounded public workflow clients."""
from __future__ import annotations

import json

import pytest

from grokcell.execution import JsonSnapshot, Limits, Permission, PreviewRuntime
from grokcell.execution.checking import DependencyVerifier
from grokcell.execution.examples import FixtureChooser, FixtureWorker
from grokcell.execution.workflows import (
    DEPENDENCY_OBSERVATION,
    REPAIRED_COMPONENT,
    REPAIR_OBSERVATION,
    RepairBytesVerifier,
    assessment_bytes,
    dependency,
    repair,
)
from evaluation.validate_results import summarize, validate_dataset, validate_record, validate_registry


class OfflineDependencyVerifier(DependencyVerifier):
    """Run the data contract locally; this says nothing about prose truth."""

    mode = "offline"


def runtime(*, chooser, worker, verifier, limits=Limits()):
    return PreviewRuntime(
        permission=Permission(
            "fixture", "local-test", ("read", "decide", "generate", "check", "admit", "yield"), 10_000
        ),
        dependencies=JsonSnapshot.capture({"fixture": "public-workflow"}),
        chooser=chooser,
        workers={"generate": worker},
        verifier=verifier,
        limits=limits,
        clock=lambda: 1,
    )


def test_repair_generates_only_the_bounded_component_fixture():
    rt = runtime(chooser=FixtureChooser("repair"), worker=FixtureWorker(REPAIRED_COMPONENT),
                 verifier=RepairBytesVerifier())

    result = repair(rt)

    assert result.assurance == "offline_preview"
    assert rt.audit()["revision"] == 1
    assert rt.audit()["calls"] == 2
    assert "reserved must not exceed on_hand" in REPAIR_OBSERVATION.value()["public_contract"]
    assert REPAIRED_COMPONENT.startswith(b"def available(on_hand, reserved):")
    assert result.candidate_hash


def test_repair_review_choice_yields_without_candidate_generation():
    rt = runtime(chooser=FixtureChooser("review"), worker=FixtureWorker(REPAIRED_COMPONENT),
                 verifier=RepairBytesVerifier())

    result = repair(rt)

    assert result.value() == {"reason": "maintainer_review_required"}
    assert rt.audit()["revision"] == 0
    assert rt.audit()["calls"] == 1


def test_dependency_assessment_preserves_unknowns_and_denies_upgrade_authority():
    source = DEPENDENCY_OBSERVATION
    verifier = OfflineDependencyVerifier(source)
    rt = runtime(chooser=FixtureChooser("assess"), worker=FixtureWorker(assessment_bytes(source)),
                 verifier=verifier)

    result = dependency(rt, source)

    assessment = json.loads(assessment_bytes(source))
    assert result.assurance == "offline_preview"
    assert assessment["source_hash"] == source.identity
    assert assessment["compatibility"] == "not_established"
    assert assessment["review_required"] is True
    assert assessment["upgrade_authorized"] is False
    assert rt.audit()["revision"] == 1
    assert rt.audit()["calls"] == 2


def test_dependency_review_choice_yields_when_maintainer_review_is_selected():
    source = DEPENDENCY_OBSERVATION
    rt = runtime(chooser=FixtureChooser("review"), worker=FixtureWorker(assessment_bytes(source)),
                 verifier=OfflineDependencyVerifier(source))

    result = dependency(rt, source)

    assert result.value() == {"reason": "compatibility_not_established"}
    assert rt.audit()["revision"] == 0
    assert rt.audit()["calls"] == 1


@pytest.mark.parametrize("workflow,source", [
    (repair, JsonSnapshot.capture({"component": "available", "source": "x", "extra": "ignored?"})),
    (dependency, JsonSnapshot.capture({"dependency": "x", "from_version": "1", "to_version": "2",
                                      "changes": ["API changed"], "compatibility": "compatible"})),
])
def test_workflows_reject_inputs_outside_the_explicit_schema_before_runtime_effects(workflow, source):
    rt = runtime(chooser=FixtureChooser("repair"), worker=FixtureWorker(REPAIRED_COMPONENT),
                 verifier=RepairBytesVerifier())

    with pytest.raises(ValueError, match="bounded schema|not_established"):
        workflow(rt, source)

    assert rt.audit()["steps"] == 0
    assert rt.audit()["calls"] == 0


def test_shared_circuit_cannot_mint_a_second_call_budget():
    rt = runtime(chooser=FixtureChooser("repair"), worker=FixtureWorker(REPAIRED_COMPONENT),
                 verifier=RepairBytesVerifier(), limits=Limits(max_calls=1))

    with pytest.raises(RuntimeError, match="call limit"):
        repair(rt)

    assert rt.audit()["calls"] == 1
    assert rt.audit()["revision"] == 0


def test_frozen_studies_require_complete_attempt_records_and_report_unknown_costs():
    record = {
        "study_id": "grokcell-controller-ablation",
        "protocol_version": "1.0.0",
        "split": "evaluation",
        "case_family": "sealed-family-a",
        "repository_id": "repo-a",
        "case_id": "case-a",
        "system_id": "system-a",
        "controller_id": "jev",
        "worker_id": "fixed-worker-v1",
        "verifier_contract_id": "checker-v1",
        "environment_id": "env-v1",
        "permission_profile_id": "permission-v1",
        "resource_limits_profile_id": "limits-v1",
        "acceptance_owner_id": "independent-owner",
        "sealed_case_commitment": "a" * 64,
        "uncertainty_notes": ["provider invoice pending"],
        "attempts": [{
            "attempt_id": "attempt-1",
            "outcome": "failed",
            "provider_cost_microusd": None,
            "cost_source": "unknown",
            "billing_reconciled": False,
            "latency_ms": 1200,
            "required_checks": 4,
            "passed_checks": 2,
            "human_rescue": True,
            "evidence_refs": ["private-record:attempt-1"],
        }],
    }
    registry = {
        "acceptance_owner_id": "independent-owner",
        "sealed_case_commitment": "a" * 64,
        "cases": [{"case_id": "case-a", "case_family": "sealed-family-a",
                   "repository_id": "repo-a", "split": "evaluation"}],
    }
    rows = [validate_record({**record, "controller_id": arm, "system_id": "system-" + arm}, "A", registry)
            for arm in ("fixed", "jev", "inexpensive_alternative")]
    validate_dataset(rows, "A")
    summary = summarize(rows, "A")["jev"]
    assert summary["failed_attempts"] == 1
    assert summary["human_rescue_attempts"] == 1
    assert summary["unknown_cost_attempts"] == 1
    assert summary["unreconciled_cost_attempts"] == 1
    assert summary["check_coverage"] == 0.5
    with pytest.raises(ValueError, match="sealed evaluation"):
        validate_record({**record, "split": "development"}, "A", registry)
    with pytest.raises(ValueError, match="unregistered controller"):
        validate_record({**record, "controller_id": "unregistered"}, "A", registry)
    with pytest.raises(ValueError, match="all pre-registered"):
        validate_dataset(rows[:2], "A")
    with pytest.raises(ValueError, match="do not share"):
        validate_dataset([rows[0], rows[1], {**rows[2], "resource_limits_profile_id": "different"}], "A")
    split_collision = {**registry, "cases": [
        registry["cases"][0], {"case_id": "case-b", "case_family": "sealed-family-a",
                               "repository_id": "repo-b", "split": "retrieval"}]}
    with pytest.raises(ValueError, match="disjoint across splits"):
        validate_registry(split_collision)
    system_record = {**record, "study_id": "grokcell-complete-systems", "controller_id": None,
                     "system_id": "complete-system-x"}
    system_validated = validate_record(system_record, "B", registry)
    validate_dataset([system_validated], "B")
    assert summarize([system_validated], "B")["complete-system-x"]["episodes"] == 1
