"""Canonical repair attempt records in GrokCell state."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")


def _digest(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class AttemptStore:
    def __init__(self, state_root: Path) -> None:
        self.root = Path(state_root) / "repair_attempts"
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, record_id: str) -> Path:
        if not _ID.fullmatch(record_id):
            raise ValueError("invalid attempt id")
        return self.root / f"{record_id}.json"

    def read(self, record_id: str) -> dict:
        value = json.loads(self.path_for(record_id).read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("id") != record_id:
            raise ValueError("invalid attempt record")
        return value

    def write(self, record: dict, *, expected_status: str | None = None) -> str:
        record_id = record.get("id")
        path = self.path_for(record_id)
        if expected_status is None and path.exists():
            raise ValueError("attempt already exists")
        if expected_status is not None and self.read(record_id).get("status") != expected_status:
            raise ValueError("attempt transition changed")
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            import os
            os.fsync(handle.fileno())
        temporary.replace(path)
        return _digest(record)

    def all(self) -> list[dict]:
        return [self.read(path.stem) for path in sorted(self.root.glob("*.json"))]

    def unfinished(self) -> list[dict]:
        return [item for item in self.all() if item.get("status") in {
            "started", "proposal_ready"}]
