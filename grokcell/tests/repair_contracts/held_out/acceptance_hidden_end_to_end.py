import json

from availability_api import availability
from event_decoder import decode_event
from inventory_reducer import apply_event


def run_events(*events):
    state = {}
    for raw in events:
        state = apply_event(state, decode_event(json.dumps(raw)))
    return state


def test_upstream_reservation_changes_final_observable_availability():
    state = run_events(
        {"event_id": "e1", "sku": "SKU-A", "kind": "receive", "quantity": 8},
        {"event_id": "e2", "sku": "SKU-A", "kind": "reserve", "quantity": 3},
    )
    assert availability(state, "SKU-A") == {
        "sku": "SKU-A", "on_hand": 8, "reserved": 3, "available": 5
    }


def test_related_later_case_needs_fresh_evaluation():
    state = run_events(
        {"event_id": "later-1", "sku": "SKU-B", "kind": "receive", "quantity": 11},
        {"event_id": "later-2", "sku": "SKU-B", "kind": "reserve", "quantity": 4},
        {"event_id": "later-3", "sku": "SKU-B", "kind": "release", "quantity": 1},
    )
    assert availability(state, "SKU-B") == {
        "sku": "SKU-B", "on_hand": 11, "reserved": 3, "available": 8
    }


def test_similar_looking_decoy_requires_release_not_prior_reserve_fix():
    state = run_events(
        {"event_id": "decoy-1", "sku": "SKU-C", "kind": "receive", "quantity": 7},
        {"event_id": "decoy-2", "sku": "SKU-C", "kind": "reserve", "quantity": 5},
        {"event_id": "decoy-3", "sku": "SKU-C", "kind": "release", "quantity": 2},
    )
    assert availability(state, "SKU-C") == {
        "sku": "SKU-C", "on_hand": 7, "reserved": 3, "available": 4
    }
