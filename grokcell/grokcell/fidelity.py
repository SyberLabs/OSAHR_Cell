"""File-backed fidelity records. Written by the runner, not by bots."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import protocol
from .messages import validate_component_name


@dataclass(frozen=True, slots=True)
class FidelityRecord:
    name: str
    passed: bool
    suite_hash: str
    exit_code: int
    outcome: str = ""

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "suite_hash": self.suite_hash,
            "exit_code": self.exit_code,
            "outcome": self.outcome or ("pass" if self.passed else "tests_failed"),
            "runner": "python_tests",
        }

    @classmethod
    def from_json(cls, payload: dict) -> "FidelityRecord":
        passed = payload["passed"]
        exit_code = payload["exit_code"]
        if (
            not isinstance(payload.get("name"), str)
            or not isinstance(passed, bool)
            or not isinstance(payload.get("suite_hash"), str)
            or not isinstance(exit_code, int)
            or isinstance(exit_code, bool)
            or payload.get("runner") != "python_tests"
        ):
            raise ValueError("invalid_fidelity")
        outcome = str(
            payload.get("outcome") or ("pass" if passed else "tests_failed")
        )
        if outcome not in {
            "pass",
            "tests_failed",
            "infra_error",
            "timeout",
            "sandbox_required",
        }:
            raise ValueError("invalid_fidelity")
        return cls(
            name=payload["name"],
            passed=passed,
            suite_hash=payload["suite_hash"],
            exit_code=exit_code,
            outcome=outcome,
        )


class FidelityStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, root: Path | None = None) -> "FidelityStore":
        if root is not None:
            return cls(Path(root))
        env = os.environ.get("GROKCELL_FIDELITY_DIR")
        return cls(Path(env) if env else protocol.FIDELITY_DIR)

    def path_for(self, name: str) -> Path:
        exact = validate_component_name(name)
        path = self.root / f"{exact}.json"
        if path.resolve().parent != self.root.resolve():
            raise ValueError("invalid_component_name")
        return path

    def get(self, name: str) -> FidelityRecord | None:
        path = self.path_for(name)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        record = FidelityRecord.from_json(payload)
        if record.name != name:
            raise ValueError("fidelity_name_mismatch")
        return record

    def put(self, record: FidelityRecord) -> Path:
        path = self.path_for(record.name)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(record.to_json(), indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    def check(self, name: str, *, expected_hash: str | None) -> tuple[bool, str]:
        if not expected_hash:
            return False, "runner_absent"
        try:
            record = self.get(name)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return False, "invalid_fidelity"
        if record is None:
            return False, "runner_absent"
        if record.suite_hash != expected_hash:
            return False, "stale_fidelity"
        if not record.passed or record.outcome != "pass" or record.exit_code != 0:
            return False, "runner_failed"
        return True, "runner_passed"
