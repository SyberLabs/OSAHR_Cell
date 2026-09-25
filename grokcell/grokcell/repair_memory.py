"""Canonical repair attempts in GrokCell state and bounded lexical retrieval."""
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


def simple_retrieve(store: AttemptStore, *, component: str, signature: str,
                    contract_hash: str, base_hash: str,
                    dependency_manifest: dict[str, str], environment_hash: str,
                    limit: int = 5) -> list[dict]:
    words = set(re.findall(r"[a-z0-9_]+", signature.lower()))
    scored = []
    for record in store.all():
        if record.get("status") != "finished" or not record.get("observed_outcome"):
            continue
        same_contract = record.get("contract_hash") == contract_hash
        same_component = record.get("target") == component
        prior_words = set(re.findall(r"[a-z0-9_]+", str(record.get("failure_signature", "")).lower()))
        score = 8 * same_contract + 4 * same_component + min(3, len(words & prior_words))
        if score:
            scored.append((score, record["id"], record))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [dict(record, record_hash=_digest(record),
                 applicability=("exact_context" if same_context(
                     record, component, contract_hash, base_hash,
                     dependency_manifest, environment_hash)
                                else "related_requires_retest"))
            for _, _, record in scored[:limit]]


def same_context(record: dict, component: str, contract_hash: str,
                 base_hash: str, dependency_manifest: dict[str, str],
                 environment_hash: str) -> bool:
    return (record.get("target") == component
            and record.get("contract_hash") == contract_hash
            and record.get("base_hash") == base_hash
            and record.get("dependency_manifest") == dependency_manifest
            and record.get("environment_hash") == environment_hash)
