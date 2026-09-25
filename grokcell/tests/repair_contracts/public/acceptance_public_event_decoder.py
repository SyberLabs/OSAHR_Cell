import json

import pytest

from service import decode_event


def test_receive_event_preserves_public_fields():
    raw = json.dumps({"event_id": "evt-1", "sku": "SKU-A", "kind": "receive", "quantity": 8})
    assert decode_event(raw) == {
        "event_id": "evt-1", "sku": "SKU-A", "kind": "receive", "quantity": 8
    }


def test_reserve_is_not_a_receive_event():
    raw = json.dumps({"event_id": "evt-2", "sku": "SKU-A", "kind": "reserve", "quantity": 3})
    assert decode_event(raw) == {
        "event_id": "evt-2", "sku": "SKU-A", "kind": "reserve", "quantity": 3
    }


@pytest.mark.parametrize("raw", ["not json", "[]", '{"event_id":"evt-1"}'])
def test_malformed_or_incomplete_event_is_rejected(raw):
    with pytest.raises(ValueError):
        decode_event(raw)
