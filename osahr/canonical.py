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


def validate_state_value(value: Any) -> None:
    """Reject state that cannot retain a stable JSON-shaped identity."""
    if isinstance(value, Mapping):
        if type(value) is not dict:
            raise TypeError("Authoritative state mappings must be plain dicts")
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Authoritative state mapping keys must be strings")
        for item in value.values():
            validate_state_value(item)
        return
    if isinstance(value, Set):
        if type(value) not in {set, frozenset}:
            raise TypeError("Authoritative state sets must be built-in sets")
        for item in value:
            validate_state_value(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if type(value) not in {list, tuple}:
            raise TypeError("Authoritative state sequences must be lists or tuples")
        for item in value:
            validate_state_value(item)
        return
    canonicalize(value)


def _type_name(value: Any) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def canonicalize(value: Any) -> Any:
    """Encode every value with an explicit type tag.

    Tags apply recursively, including to containers and primitives.  A value
    supplied by a caller therefore cannot impersonate an internal marker by
    constructing an ordinary dict or list with the same visible shape.
    """
    if value is None:
        return ["none"]
    if isinstance(value, EntityId):
        return ["entity_id", str(value)]
    if isinstance(value, Enum):
        return ["enum", _type_name(value), canonicalize(value.value)]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite floats cannot be canonicalized")
        return ["float", value.hex()]
    if isinstance(value, str):
        return ["str", value]
    if dataclasses.is_dataclass(value):
        return [
            "dataclass",
            _type_name(value),
            [
                [field.name, canonicalize(getattr(value, field.name))]
                for field in dataclasses.fields(value)
                if field.metadata.get("canonical", True)
            ],
        ]
    if isinstance(value, Mapping):
        if type(value) is not dict:
            raise TypeError("Canonical mappings must be plain dicts")
        keys = tuple(value)
        if all(isinstance(key, str) for key in keys):
            ordered = sorted(keys)
        elif all(isinstance(key, EntityId) for key in keys):
            ordered = sorted(keys)
        else:
            raise TypeError("Canonical mapping keys must be uniformly str or EntityId")
        return [
            "mapping",
            _type_name(value),
            [[canonicalize(key), canonicalize(value[key])] for key in ordered],
        ]
    if isinstance(value, Set):
        if type(value) not in {set, frozenset}:
            raise TypeError("Canonical sets must be built-in sets")
        items = sorted((canonicalize(item) for item in value), key=_sort_key)
        return ["set", _type_name(value), items]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        if type(value) not in {list, tuple}:
            raise TypeError("Canonical sequences must be lists or tuples")
        return [
            "sequence",
            _type_name(value),
            [canonicalize(item) for item in value],
        ]
    if hasattr(value, "to_canonical"):
        return ["canonical", _type_name(value), canonicalize(value.to_canonical())]
    raise TypeError(f"Unsupported canonical value: {type(value)!r}")


def canonical_equal(left: Any, right: Any) -> bool:
    """Compare authoritative values without Python's cross-type coercions."""
    return canonicalize(left) == canonicalize(right)


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
