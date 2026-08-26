"""Checksum freeze for vault files, junction grammar, and AnLF versions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .protocol import (
    ANLF_LOAD_VERSION,
    ANLF_OUTAGE_VERSION,
    ART,
    BRAIN_VERSION,
    CLAIM_GRAMMAR_VERSION,
    CONCEPTS_DIR,
    CONFIRMATORY_SEED,
    FROZEN_PATH,
    GRAMMAR_FILES,
    HORIZON,
    HYPOTHESES,
    JUNCTION_GRAMMAR_VERSION,
    MCP_SCHEMA_VERSION,
    N_SCENARIOS,
    REPLICATES,
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def grammar_checksum(files: tuple[Path, ...] = GRAMMAR_FILES) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def vault_checksum(concepts_dir: Path = CONCEPTS_DIR) -> str:
    digest = hashlib.sha256()
    for path in sorted(concepts_dir.glob("*.md")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def freeze_payload() -> dict[str, Any]:
    return {
        "protocol_status": (
            f"FROZEN before confirmatory root seed {CONFIRMATORY_SEED} was executed"
        ),
        "claim_grammar_version": CLAIM_GRAMMAR_VERSION,
        "junction_grammar_version": JUNCTION_GRAMMAR_VERSION,
        "anlf_load_version": ANLF_LOAD_VERSION,
        "anlf_outage_version": ANLF_OUTAGE_VERSION,
        "brain_version": BRAIN_VERSION,
        "mcp_schema_version": MCP_SCHEMA_VERSION,
        "confirmatory_seed_declared": CONFIRMATORY_SEED,
        "horizon": HORIZON,
        "grid": list(HYPOTHESES),
        "n_scenarios": N_SCENARIOS,
        "replicates": REPLICATES,
        "vault_files": [str(path) for path in sorted(CONCEPTS_DIR.glob("*.md"))],
        "vault_sha256": vault_checksum(),
        "grammar_files": [str(path) for path in GRAMMAR_FILES],
        "grammar_sha256": grammar_checksum(),
        "selects_alpha": False,
        "llm_in_confirmatory": False,
    }


def write_freeze(path: Path = FROZEN_PATH) -> dict[str, Any]:
    ART.mkdir(parents=True, exist_ok=True)
    payload = freeze_payload()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def require_freeze(path: Path = FROZEN_PATH) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit("refusing confirmatory: artifacts/FROZEN.json missing")
    freeze = json.loads(path.read_text(encoding="utf-8"))
    if freeze["grammar_sha256"] != grammar_checksum():
        raise SystemExit("grammar changed after freeze")
    if freeze["vault_sha256"] != vault_checksum():
        raise SystemExit("vault notes changed after freeze")
    if freeze["confirmatory_seed_declared"] != CONFIRMATORY_SEED:
        raise SystemExit("confirmatory seed drifted from freeze")
    if freeze["horizon"] != HORIZON:
        raise SystemExit("horizon drifted from freeze")
    if freeze.get("llm_in_confirmatory") is True:
        raise SystemExit("confirmatory must not include an LLM")
    return freeze
