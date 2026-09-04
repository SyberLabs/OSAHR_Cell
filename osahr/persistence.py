"""Checkpoint and audit-log persistence helpers.

Checkpoints use Python pickle and must only be loaded from trusted sources.
Audit exports are canonical JSON intended for inspection and hashing.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import pickle
from pathlib import Path
from typing import Iterable

from .canonical import canonical_json, stable_hash
from .events import EventRecord
from .model import Model, RuntimeConfig
from .pattern import Rule
from .runtime import Runtime, RuntimeSnapshot

_CHECKPOINT_MAGIC_V1 = b"OSAHR-PY-CHECKPOINT\x00\x01"
_CHECKPOINT_MAGIC = b"OSAHR-PY-CHECKPOINT\x00\x02"


def _legacy_checkpoint_digest(payload: bytes) -> str:
    """Reproduce the V1 digest for its string-valued payload hex exactly."""
    encoded = json.dumps(
        payload.hex(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def save_checkpoint(path: str | Path, snapshot: RuntimeSnapshot) -> str:
    payload = pickle.dumps(snapshot, protocol=5)
    digest = stable_hash(payload.hex())
    with gzip.open(Path(path), "wb") as handle:
        handle.write(_CHECKPOINT_MAGIC)
        handle.write(bytes.fromhex(digest))
        handle.write(payload)
    return digest


def load_checkpoint(
    path: str | Path,
    *,
    legacy_model: Model | None = None,
    legacy_config: RuntimeConfig | None = None,
) -> RuntimeSnapshot:
    with gzip.open(Path(path), "rb") as handle:
        magic = handle.read(len(_CHECKPOINT_MAGIC))
        if magic not in {_CHECKPOINT_MAGIC_V1, _CHECKPOINT_MAGIC}:
            raise ValueError("Not an OSAHR Python checkpoint")
        expected = handle.read(32).hex()
        payload = handle.read()
    actual = (
        _legacy_checkpoint_digest(payload)
        if magic == _CHECKPOINT_MAGIC_V1
        else stable_hash(payload.hex())
    )
    if actual != expected:
        raise ValueError("Checkpoint digest mismatch")
    value = pickle.loads(payload)  # noqa: S301 - trusted checkpoint contract
    if not isinstance(value, RuntimeSnapshot):
        raise TypeError("Checkpoint does not contain a RuntimeSnapshot")
    if magic == _CHECKPOINT_MAGIC_V1:
        if legacy_model is None:
            raise ValueError(
                "Version 1 checkpoints require legacy_model for trusted migration"
            )
        if legacy_config is None:
            raise ValueError(
                "Version 1 checkpoints require legacy_config for trusted migration"
            )
        config = legacy_config
        if config.scheduler_kind is not value.scheduler_kind:
            raise ValueError("Legacy checkpoint scheduler and config differ")
        if (
            value.graph.schema.to_canonical()
            != legacy_model.graph.schema.to_canonical()
        ):
            raise ValueError("Legacy checkpoint schema differs from legacy_model")
        if not isinstance(value.rules, dict) or any(
            not isinstance(rule_id, str)
            or not isinstance(rule, Rule)
            or rule_id != rule.rule_id
            for rule_id, rule in value.rules.items()
        ):
            raise ValueError("Legacy checkpoint rule map is invalid")
        # Rebind structural hashes to the collision-free V2 canonical format.
        # The old run ID remains provenance, but the migrated state is audit-only:
        # V1 derived event IDs cannot be continued under V2 hashing without
        # silently forking its identity lineage.
        value.graph.schema = copy.deepcopy(legacy_model.graph.schema)
        for rule in value.rules.values():
            object.__setattr__(rule, "hash", stable_hash(rule.to_canonical()))
        value.model_hash = legacy_model.hash
        value.config = copy.deepcopy(config)
        # V1 did not persist explosion-window history. Conservatively count the
        # latest event time up to the configured threshold so migration cannot
        # silently weaken the limiter.
        recent_count = min(
            max(value.event_index, 0),
            config.max_events_per_time_window,
        )
        value.recent_event_times = (value.last_event_time,) * recent_count
        value.continuation_allowed = False
        value.identity_version = 1
        value.format_version = 2
        value.pending_internal = None
        value.next_reaction_snapshot = None
        value.next_reaction_initialized = False
        value.seal()
    elif getattr(value, "format_version", None) != 2:
        raise ValueError("Checkpoint payload format version does not match its envelope")
    return value


def export_audit_log(path: str | Path, records: Iterable[EventRecord]) -> str:
    text = canonical_json(list(records))
    Path(path).write_text(text + "\n", encoding="utf-8")
    return stable_hash(text)
