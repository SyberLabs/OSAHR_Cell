"""Checkpoint and audit-log persistence helpers.

Checkpoints use Python pickle and must only be loaded from trusted sources.
Audit exports are canonical JSON intended for inspection and hashing.
"""

from __future__ import annotations

import gzip
import pickle
from pathlib import Path
from typing import Iterable

from .canonical import canonical_json, stable_hash
from .events import EventRecord
from .runtime import RuntimeSnapshot

_CHECKPOINT_MAGIC = b"OSAHR-PY-CHECKPOINT\x00\x01"


def save_checkpoint(path: str | Path, snapshot: RuntimeSnapshot) -> str:
    payload = pickle.dumps(snapshot, protocol=5)
    digest = stable_hash(payload.hex())
    with gzip.open(Path(path), "wb") as handle:
        handle.write(_CHECKPOINT_MAGIC)
        handle.write(bytes.fromhex(digest))
        handle.write(payload)
    return digest


def load_checkpoint(path: str | Path) -> RuntimeSnapshot:
    with gzip.open(Path(path), "rb") as handle:
        magic = handle.read(len(_CHECKPOINT_MAGIC))
        if magic != _CHECKPOINT_MAGIC:
            raise ValueError("Not an OSAHR Python checkpoint")
        expected = handle.read(32).hex()
        payload = handle.read()
    actual = stable_hash(payload.hex())
    if actual != expected:
        raise ValueError("Checkpoint digest mismatch")
    value = pickle.loads(payload)  # noqa: S301 - trusted checkpoint contract
    if not isinstance(value, RuntimeSnapshot):
        raise TypeError("Checkpoint does not contain a RuntimeSnapshot")
    return value


def export_audit_log(path: str | Path, records: Iterable[EventRecord]) -> str:
    text = canonical_json(list(records))
    Path(path).write_text(text + "\n", encoding="utf-8")
    return stable_hash(text)
