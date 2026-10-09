"""Explicit checkpoint codec. Never load pickle or caller-selected Python classes."""
from __future__ import annotations

import base64
from dataclasses import fields

from . import records

_TYPES = {kind.__name__: kind for kind in (
    records.JsonSnapshot, records.Observation, records.ActionOffer, records.Decision,
    records.Candidate, records.CheckResult, records.Evidence, records.Permission,
    records.AcceptedState, records.Limits)}


def encode(value):
    if type(value) in _TYPES.values():
        return {"$record": type(value).__name__, "fields": {
            field.name: encode(getattr(value, field.name)) for field in fields(value)}}
    if type(value) is bytes:
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if type(value) is tuple:
        return {"$tuple": [encode(item) for item in value]}
    if type(value) is list:
        return [encode(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str or key.startswith("$") for key in value):
            raise ValueError("reserved checkpoint key")
        return {key: encode(item) for key, item in value.items()}
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise TypeError("unsupported checkpoint value")


def decode(value, depth=0):
    if depth > 64:
        raise ValueError("checkpoint nesting limit")
    if type(value) is list:
        return [decode(item, depth + 1) for item in value]
    if type(value) is dict:
        if "$bytes" in value:
            if set(value) != {"$bytes"} or type(value["$bytes"]) is not str:
                raise ValueError("invalid byte encoding")
            return base64.b64decode(value["$bytes"], validate=True)
        if "$tuple" in value:
            if set(value) != {"$tuple"} or type(value["$tuple"]) is not list:
                raise ValueError("invalid tuple encoding")
            return tuple(decode(item, depth + 1) for item in value["$tuple"])
        if "$record" in value:
            if set(value) != {"$record", "fields"} or value["$record"] not in _TYPES:
                raise ValueError("unsupported checkpoint record")
            kind = _TYPES[value["$record"]]
            data = value["fields"]
            if type(data) is not dict or set(data) != {field.name for field in fields(kind)}:
                raise ValueError("checkpoint record fields mismatch")
            return kind(**{key: decode(item, depth + 1) for key, item in data.items()})
        if any(key.startswith("$") for key in value):
            raise ValueError("unsupported checkpoint tag")
        return {key: decode(item, depth + 1) for key, item in value.items()}
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError("unsupported checkpoint value")
