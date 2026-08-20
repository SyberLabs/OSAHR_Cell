"""Canonical serialization and hashing.

Floats are encoded with ``float.hex`` to avoid locale and decimal-rendering
ambiguity. NaN and infinities are rejected throughout the authoritative state.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping, Sequence, Set
from enum import Enum
from typing import Any

from .ids import EntityId


def canonicalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite floats cannot be canonicalized")
        return {"__float_hex__": value.hex()}
    if isinstance(value, EntityId):
        return {"__entity_id__": str(value)}
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value):
        return {
            field.name: canonicalize(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if field.metadata.get("canonical", True)
        }
    if isinstance(value, Mapping):
        return {
            str(key): canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Set):
        items = [canonicalize(item) for item in value]
        return sorted(items, key=_sort_key)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [canonicalize(item) for item in value]
    if hasattr(value, "to_canonical"):
        return canonicalize(value.to_canonical())
    raise TypeError(f"Unsupported canonical value: {type(value)!r}")


def _sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
