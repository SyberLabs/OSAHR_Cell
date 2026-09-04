"""File-backed fidelity records. Written by the runner, not by bots."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import protocol


@dataclass(frozen=True, slots=True)
class FidelityRecord:
    name: str
    passed: bool
    suite_hash: str
    exit_code: int

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "suite_hash": self.suite_hash,
            "exit_code": self.exit_code,
            "runner": "python_tests",
        }

    @classmethod
    def from_json(cls, payload: dict) -> "FidelityRecord":
        return cls(
            name=str(payload["name"]),
            passed=bool(payload["passed"]),
            suite_hash=str(payload["suite_hash"]),
            exit_code=int(payload["exit_code"]),
        )


class FidelityStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, root: Path | None = None) -> "FidelityStore":
        return cls(Path(root) if root is not None else protocol.FIDELITY_DIR)

    def path_for(self, name: str) -> Path:
        safe = name.replace("/", "_")
        return self.root / f"{safe}.json"

    def get(self, name: str) -> FidelityRecord | None:
        path = self.path_for(name)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return FidelityRecord.from_json(payload)

    def put(self, record: FidelityRecord) -> Path:
        path = self.path_for(record.name)
        path.write_text(json.dumps(record.to_json(), indent=2) + "\n", encoding="utf-8")
        return path

    def check(self, name: str, *, expected_hash: str | None) -> tuple[bool, str]:
        if not expected_hash:
            return False, "runner_absent"
        record = self.get(name)
        if record is None:
            return False, "runner_absent"
        if record.suite_hash != expected_hash:
            return False, "stale_fidelity"
        if not record.passed:
            return False, "runner_failed"
        return True, "runner_passed"
