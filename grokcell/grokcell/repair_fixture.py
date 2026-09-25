"""Synthetic, public starting states. These are task inputs, never oracle results."""
from __future__ import annotations

from pathlib import Path

CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "tests" / "repair_contracts"
COMPONENTS = ("event_decoder", "inventory_reducer", "availability_api")
DEPENDENCIES = {"event_decoder": (), "inventory_reducer": ("event_decoder",),
                "availability_api": ("inventory_reducer",)}

DECODER = '''import json

def decode_event(raw: str) -> dict[str, object]:
    try:
        event = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(event, dict) or set(event) != {"event_id", "sku", "kind", "quantity"}:
        raise ValueError("invalid event fields")
    if not isinstance(event["event_id"], str) or not event["event_id"]:
        raise ValueError("invalid event id")
    if not isinstance(event["sku"], str) or not event["sku"]:
        raise ValueError("invalid SKU")
    if event["kind"] not in {"receive", "reserve", "release"}:
        raise ValueError("invalid kind")
    if type(event["quantity"]) is not int or event["quantity"] <= 0:
        raise ValueError("invalid quantity")
    return event
'''

REDUCER = '''def apply_event(state: dict[str, dict[str, int]], event: dict[str, object]) -> dict[str, dict[str, int]]:
    sku, kind, quantity = event["sku"], event["kind"], event["quantity"]
    result = {key: dict(value) for key, value in state.items()}
    current = result.get(sku, {"on_hand": 0, "reserved": 0})
    if kind == "receive":
        current["on_hand"] += quantity
    elif kind == "reserve":
        if quantity > current["on_hand"] - current["reserved"]:
            raise ValueError("insufficient availability")
        current["reserved"] += quantity
    elif kind == "release":
        if quantity > current["reserved"]:
            raise ValueError("insufficient reservation")
        current["reserved"] -= quantity
    else:
        raise ValueError("invalid kind")
    result[sku] = current
    return result
'''

API = '''def availability(state: dict[str, dict[str, int]], sku: str) -> dict[str, object]:
    counts = state.get(sku, {"on_hand": 0, "reserved": 0})
    on_hand, reserved = counts["on_hand"], counts["reserved"]
    return {"sku": sku, "on_hand": on_hand, "reserved": reserved,
            "available": on_hand - reserved}
'''

GOOD = {"event_decoder": DECODER, "inventory_reducer": REDUCER,
        "availability_api": API}

# The later case is a distinct reserve off-by-one defect. The release defect
# is a similar-looking decoy, so a retrieved repair still needs a new check.
VARIANTS = {
    "upstream_sku": {**GOOD, "event_decoder": DECODER.replace(
        '    return event\n', '    event["sku"] = event["sku"].lower()\n    return event\n')},
    "local_reserve": {**GOOD, "inventory_reducer": REDUCER.replace(
        'current["reserved"] += quantity', 'current["on_hand"] += quantity')},
    "plausible_bool": {**GOOD, "event_decoder": DECODER.replace(
        'type(event["quantity"]) is not int', 'not isinstance(event["quantity"], int)')},
    "later_related": {**GOOD, "inventory_reducer": REDUCER.replace(
        'current["reserved"] += quantity', 'current["reserved"] += quantity - 1')},
    "release_decoy": {**GOOD, "inventory_reducer": REDUCER.replace(
        'current["reserved"] -= quantity', 'current["on_hand"] -= quantity')},
}

# Construction-only prior task. It is never included in the scored pilot.
SEED_VARIANT = "seed_reserve"
SEED_SOURCES = {**GOOD, "inventory_reducer": REDUCER.replace(
    'current["reserved"] += quantity', 'current["reserved"] = current["reserved"] + quantity + 1')}

PUBLIC_END_TO_END = '''import json
from event_decoder import decode_event
from inventory_reducer import apply_event
from availability_api import availability

def test_public_application():
    state = {}
    for index, kind, quantity in ((1, "receive", 8), (2, "reserve", 3)):
        event = json.dumps({"event_id": str(index), "sku": "SKU-A", "kind": kind,
                            "quantity": quantity})
        state = apply_event(state, decode_event(event))
    assert availability(state, "SKU-A") == {
        "sku": "SKU-A", "on_hand": 8, "reserved": 3, "available": 5}
'''
