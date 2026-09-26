"""Two clients of the same runtime; source identity pins replay semantics."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .examples import FixtureChooser, FixtureWorker, RepairFixtureVerifier
from .ports import CheckContract
from .records import ActionOffer, CheckResult, JsonSnapshot, canonical, digest

REPAIRED_COMPONENT = b'''def available(on_hand, reserved):
    if type(on_hand) is not int or type(reserved) is not int:
        raise ValueError("integer counts required")
    if on_hand < 0 or reserved < 0 or reserved > on_hand:
        raise ValueError("invalid counts")
    return on_hand - reserved
'''
REPAIR_OBSERVATION = JsonSnapshot.capture({
    "component": "available", "source": "def available(on_hand, reserved): return on_hand + reserved",
    "public_diagnostic": "available(10,4) returned 14; expected 6",
    "public_contract": "Accept non-Boolean nonnegative integer counts; reserved must not exceed on_hand. "
                       "Return on_hand minus reserved. Raise ValueError for invalid inputs. Do not mutate inputs."})
DEPENDENCY_OBSERVATION = JsonSnapshot.capture({
    "dependency": "inventory-client", "from_version": "1.4", "to_version": "2.0",
    "changes": ["reserve() result changes from a scalar to an object"],
    "compatibility": "not_established"})


class RepairBytesVerifier(RepairFixtureVerifier):
    """Offline plumbing only; choose IsolatedRepairVerifier to execute behavior."""
    contract = CheckContract("inventory-fixture-v1", "exact-fixture-bytes-v1", "offline-python", ("expected_bytes",))

    def verify(self, candidate):
        return (CheckResult("expected_bytes", "pass" if candidate.content == REPAIRED_COMPONENT else "fail"),)


def workflow_identity(name):
    return name + ":" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def assessment_bytes(source=DEPENDENCY_OBSERVATION):
    data = source.value()
    return canonical({"dependency": data["dependency"], "from_version": data["from_version"],
                      "to_version": data["to_version"], "source_hash": source.identity,
                      "compatibility": "not_established", "review_required": True, "upgrade_authorized": False})


def checked_proposal(runtime, observation, decision, request, artifact_type, *, prefix=""):
    """Composition shares the caller's authority, limits and journal; no new budget."""
    candidate = runtime.call(prefix + "proposal", observation, decision, request, artifact_type=artifact_type)
    evidence = runtime.check(prefix + "verification", candidate)
    return runtime.admit(prefix + "admission", candidate, evidence)


def repair(runtime, source=REPAIR_OBSERVATION):
    observation = runtime.read("input", source)
    decision = runtime.decide("route", observation, (
        ActionOffer("repair", "generate", "repair the demonstrated availability arithmetic defect"),
        ActionOffer("review", "yield", "request maintainer review if the contract or evidence is insufficient")))
    if decision.choice.effect == "yield":
        return runtime.yield_("review", "maintainer_review_required")
    request = JsonSnapshot.capture({"task": "repair the supplied component", **source.value(),
                                   "output": "JSON object containing exactly module: complete Python source",
                                   "language": "One available(on_hand, reserved) function only. No imports, attributes, helper functions, "
                                               "loops, defaults, decorators, I/O, or top-level effects. Use arithmetic, "
                                               "comparisons, if, return, type(x), and raise ValueError(text)."})
    return checked_proposal(runtime, observation, decision, request, "python_component")


def dependency(runtime, source=DEPENDENCY_OBSERVATION):
    observation = runtime.read("input", source)
    decision = runtime.decide("route", observation, (
        ActionOffer("assess", "generate", "draft an evidence-scoped dependency assessment for human review"),
        ActionOffer("review", "yield", "stop for a maintainer when observations are insufficient")))
    if decision.choice.effect == "yield":
        return runtime.yield_("review", "compatibility_not_established")
    request = JsonSnapshot.capture({"task": "produce a dependency assessment, not an upgrade authorization",
                                   "observations": source.value(), "source_hash": source.identity,
                                   "required_json_fields": json_assessment_shape(source)})
    return checked_proposal(runtime, observation, decision, request, "dependency_assessment")


def json_assessment_shape(source):
    """Public requirements; no hidden compatibility or semantic claims are inserted."""
    import json
    return json.loads(assessment_bytes(source))
