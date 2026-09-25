"""Canonical repair attempts in GrokCell state; optional rebuildable retrieval."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import time
from pathlib import Path

JEV_MEM_COMMIT = "81574eb23f3fd8d1a6c4d54a1e7d6f2dd539e9bb"
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


class JevMemRetrieval:
    """Uses Jev-Mem's real build/query API, then resolves IDs to GrokCell records."""
    def __init__(self, store: AttemptStore, cache_dir: Path) -> None:
        distribution = importlib.metadata.distribution("jev-mem")
        direct = distribution.read_text("direct_url.json")
        info = json.loads(direct) if direct else {}
        if info.get("vcs_info", {}).get("commit_id") != JEV_MEM_COMMIT:
            raise RuntimeError("jev_mem_revision_unverified")
        from jev_mem import JevMemConfig, JevMemSystem
        config = JevMemConfig(write_enabled=True, read_enabled=True,
                              admission_enabled=False, jev_mock=False,
                              max_retries=0, maximum_jev_calls=4,
                              candidate_top_k=5, anchor_count=5,
                              answer_top_k=5, maximum_nodes=20,
                              maximum_edges=100, max_latency_seconds=10.0)
        self.system = JevMemSystem(cache_dir=str(cache_dir), jev_config=config)
        self.store = store

    def build(self, records: list[dict]) -> dict:
        observations = []
        for record in records:
            if record.get("status") != "finished":
                continue
            observations.append({
                "content": f"component={record.get('target')} contract={record.get('contract_hash')} "
                           f"failure={str(record.get('failure_signature', ''))[:500]} "
                           f"observed_outcome={record.get('observed_outcome')}",
                "metadata": {"record_id": record["id"], "record_hash": _digest(record)},
            })
        started = time.monotonic()
        result = self.system.build_memory_from_conversation(observations)
        self.system.save_memory()
        return {"records": len(observations), "result": result,
                "elapsed_ms": int((time.monotonic() - started) * 1000)}

    def retrieve(self, *, component: str, signature: str, limit: int = 5) -> tuple[list[dict], dict]:
        question = f"component={component} public_failure={signature[:500]}"
        started = time.monotonic()
        context, _ = self.system.query_engine.query(question, top_k=min(limit, 5))
        found = []
        for node in context.anchor_nodes:
            record_id, expected = node.attributes.get("record_id"), node.attributes.get("record_hash")
            try:
                record = self.store.read(record_id)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if _digest(record) != expected or record.get("status") != "finished":
                continue
            found.append(dict(record, record_hash=expected,
                              applicability="related_requires_retest"))
        return found[:limit], {"elapsed_ms": int((time.monotonic() - started) * 1000),
                               "trace": context.metadata}
