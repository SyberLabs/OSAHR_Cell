"""Operator-owned acceptance tests. Independent authorship, not host isolation."""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .artifact import Artifact, MODULE_NAME, stage_artifact
from .messages import validate_component_name
from .mutant import kill_mutant
from .runner import RunOutcome, pytest_suite, suite_hash

ACCEPTANCE_DIR_ENV = "GROKCELL_ACCEPTANCE_DIR"
ACCEPTANCE_TEST = "test_acceptance.py"
ACCEPTANCE_PIN = "test_acceptance.sha256"


@dataclass(frozen=True, slots=True)
class AcceptanceSuite:
    tests: str
    digest: str


def load_acceptance(name: str) -> AcceptanceSuite:
    """Read a pinned snapshot from operator configuration, never the payload."""
    configured = os.environ.get(ACCEPTANCE_DIR_ENV)
    if not configured:
        raise ValueError("acceptance_suite_missing")
    try:
        root = Path(configured).resolve()
        directory = root / validate_component_name(name)
        tests_path = directory / ACCEPTANCE_TEST
        pin_path = directory / ACCEPTANCE_PIN
        if (
            directory.is_symlink()
            or tests_path.is_symlink()
            or pin_path.is_symlink()
            or not directory.resolve().is_relative_to(root)
        ):
            raise ValueError("acceptance_suite_invalid")
        raw = tests_path.read_bytes()
        pin = pin_path.read_text(encoding="ascii").strip()
        tests = raw.decode("utf-8")
    except FileNotFoundError:
        raise ValueError("acceptance_suite_missing") from None
    except (OSError, UnicodeError, RuntimeError):
        raise ValueError("acceptance_suite_invalid") from None
    if not tests.strip() or re.fullmatch(r"[0-9a-f]{64}", pin) is None:
        raise ValueError("acceptance_suite_invalid")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != pin:
        raise ValueError("acceptance_suite_changed")
    return AcceptanceSuite(tests=tests, digest=digest)


def evaluate_acceptance(artifact: Artifact, suite: AcceptanceSuite) -> tuple[bool, str]:
    """Test exact module bytes without executing the candidate's test file."""
    evaluation = Artifact(
        name=artifact.name,
        files={MODULE_NAME: artifact.files[MODULE_NAME], ACCEPTANCE_TEST: suite.tests},
        source="acceptance",
    )
    with tempfile.TemporaryDirectory(prefix="grokcell-acceptance-") as raw:
        staged = stage_artifact(evaluation, Path(raw))
        expected_hash = evaluation.digest()
        if suite_hash(staged) != expected_hash:
            return False, "acceptance_stage_mismatch"
        outcome = pytest_suite(staged, untrusted=True).outcome
        if outcome is not RunOutcome.PASS:
            return False, {
                RunOutcome.TESTS_FAILED: "acceptance_failed",
                RunOutcome.TIMEOUT: "acceptance_timeout",
                RunOutcome.INFRA_ERROR: "acceptance_infrastructure",
                RunOutcome.SANDBOX_REQUIRED: "runner_sandbox_required",
            }[outcome]
        if suite_hash(staged) != expected_hash:
            return False, "acceptance_modified_artifact"
        killed, reason = kill_mutant(staged, untrusted=True)
        if not killed:
            return False, f"acceptance_{reason}"
    return True, "acceptance_passed"
