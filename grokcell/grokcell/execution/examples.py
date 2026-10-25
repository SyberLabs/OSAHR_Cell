"""Synthetic circuit clients. Fixtures exercise plumbing, not model capability."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import ClassVar

from .ports import CheckContract, Reply
from .records import (ActionOffer, Candidate, CheckResult, JsonSnapshot, Observation,
                      Permission, digest)
from .runtime import PreviewRuntime

REPAIR = b"def add(a, b):\n    return a + b\n"
ASSESSMENT = b'{"dependency":"example","review_required":true,"upgrade_authorized":false}'


@dataclass(frozen=True)
class FixtureChooser:
    choice: str
    id: str = "fixture-choice-v1"
    mode: ClassVar[str] = "offline"

    def choose(self, observation: Observation, offers: tuple[ActionOffer, ...]) -> Reply:
        return Reply(self.choice)


@dataclass(frozen=True)
class FixtureWorker:
    content: bytes
    id: str = "fixture-worker-v1"
    mode: ClassVar[str] = "offline"

    def propose(self, request: JsonSnapshot) -> Reply:
        return Reply(self.content)


class RepairFixtureVerifier:
    mode = "offline"
    contract = CheckContract("fixture-repair-v1", "exact-fixture-bytes-v1",
                             "offline-python", ("expected_bytes",))

    def verify(self, candidate: Candidate) -> tuple[CheckResult, ...]:
        # Deliberately no eval/exec/import: this is not a Python acceptance oracle.
        return (CheckResult("expected_bytes", "pass" if candidate.content == REPAIR else "fail"),)


class AssessmentFixtureVerifier:
    mode = "offline"
    contract = CheckContract("fixture-assessment-v1", "assessment-json-v1",
                             "offline-python", ("schema", "no_upgrade_authority"))

    def verify(self, candidate: Candidate) -> tuple[CheckResult, ...]:
        try:
            data = json.loads(candidate.content)
        except (ValueError, UnicodeError):
            data = None
        schema = (type(data) is dict and set(data) == {
            "dependency", "review_required", "upgrade_authorized"}
            and data["dependency"] == "example" and data["review_required"] is True)
        no_authority = type(data) is dict and data.get("upgrade_authorized") is False
        return (CheckResult("schema", "pass" if schema else "fail"),
                CheckResult("no_upgrade_authority", "pass" if no_authority else "fail"))


def checked_proposal(runtime, observation, decision, request, artifact_type):
    """A shared circuit. It inherits the caller's permission and remaining budget."""
    candidate = runtime.call("proposal", observation, decision, request,
                             artifact_type=artifact_type)
    evidence = runtime.check("verification", candidate)
    return runtime.admit("admission", candidate, evidence)


def repair_workflow(runtime: PreviewRuntime):
    observation = runtime.read("input", JsonSnapshot.capture({
        "component": "add", "public_failure": "add(2, 3) returned -1"}))
    decision = runtime.decide("route", observation, (
        ActionOffer("repair", "generate", "add"), ActionOffer("stop", "yield", "review")))
    if decision.choice.id == "stop":
        return runtime.yield_("stop", "maintainer_review_required")
    return checked_proposal(runtime, observation, decision,
                            JsonSnapshot.capture({"task": "repair add"}), "python_component")


def dependency_workflow(runtime: PreviewRuntime):
    observation = runtime.read("input", JsonSnapshot.capture({
        "dependency": "example", "old": "1", "proposed": "2", "compatibility": "unknown"}))
    decision = runtime.decide("route", observation, (
        ActionOffer("assess", "generate", "example"), ActionOffer("stop", "yield", "review")))
    if decision.choice.id == "stop":
        return runtime.yield_("stop", "compatibility_not_established")
    return checked_proposal(runtime, observation, decision,
                            JsonSnapshot.capture({"task": "draft assessment; do not authorize upgrade"}),
                            "dependency_assessment")


def demo_runtime(workflow: str) -> PreviewRuntime:
    configurations = {
        "repair": ("repair", REPAIR, RepairFixtureVerifier()),
        "dependency": ("assess", ASSESSMENT, AssessmentFixtureVerifier()),
    }
    choice, content, verifier = configurations[workflow]
    permission = Permission("demo", "local-operator",
                            ("read", "decide", "generate", "check", "admit", "yield"),
                            time.time() + 60)
    return PreviewRuntime(permission=permission,
                          dependencies=JsonSnapshot.capture({"fixture": digest(workflow)}),
                          chooser=FixtureChooser(choice), workers={"generate": FixtureWorker(content)},
                          verifier=verifier)
