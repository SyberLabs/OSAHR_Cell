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
    _validate_dependency_source(source)
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
    _validate_repair_source(source)
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
    _validate_dependency_source(source)
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


def _validate_repair_source(source):
    if type(source) is not JsonSnapshot:
        raise TypeError("repair input must be a JSON snapshot")
    value = source.value()
    fields = {"component", "source", "public_diagnostic", "public_contract"}
    if type(value) is not dict or set(value) != fields:
        raise ValueError("repair input fields do not match the bounded schema")
    if any(type(value[key]) is not str or not value[key].strip() or len(value[key]) > 4096 for key in fields):
        raise ValueError("repair input values must be nonempty text within 4096 characters")
    if value["component"] != "available":
        raise ValueError("repair component must be available")


def _validate_dependency_source(source):
    if type(source) is not JsonSnapshot:
        raise TypeError("dependency input must be a JSON snapshot")
    value = source.value()
    fields = {"dependency", "from_version", "to_version", "changes", "compatibility"}
    if type(value) is not dict or set(value) != fields:
        raise ValueError("dependency input fields do not match the bounded schema")
    for key in ("dependency", "from_version", "to_version"):
        if type(value[key]) is not str or not value[key].strip() or len(value[key]) > 128:
            raise ValueError("dependency identity and versions must be nonempty text within 128 characters")
    if (type(value["changes"]) is not list or not value["changes"]
            or len(value["changes"]) > 16
            or any(type(item) is not str or not item.strip() or len(item) > 512 for item in value["changes"])):
        raise ValueError("dependency changes must be 1-16 text facts within 512 characters each")
    if value["compatibility"] != "not_established":
        raise ValueError("compatibility must remain not_established")
