import json

import pytest

from service import decode_event


def test_later_related_reservation_uses_same_semantics_for_another_sku():
    raw = json.dumps({"event_id": "later-7", "sku": "SKU-B", "kind": "reserve", "quantity": 4})
    assert decode_event(raw) == {
        "event_id": "later-7", "sku": "SKU-B", "kind": "reserve", "quantity": 4
    }


def test_release_is_distinct_from_reserve_and_receive():
    raw = json.dumps({"event_id": "decoy-2", "sku": "SKU-C", "kind": "release", "quantity": 2})
    assert decode_event(raw) == {
        "event_id": "decoy-2", "sku": "SKU-C", "kind": "release", "quantity": 2
    }


@pytest.mark.parametrize("quantity", [0, -1, True, "2"])
def test_nonpositive_or_noninteger_quantity_is_rejected(quantity):
    raw = json.dumps({"event_id": "bad-quantity", "sku": "SKU-A", "kind": "receive", "quantity": quantity})
    with pytest.raises(ValueError):
        decode_event(raw)


@pytest.mark.parametrize("change", [{"sku": ""}, {"kind": "return"}, {"unexpected": 1}])
def test_invalid_identity_kind_or_extra_field_is_rejected(change):
    data = {"event_id": "bad-field", "sku": "SKU-A", "kind": "receive", "quantity": 1}
    data.update(change)
    with pytest.raises(ValueError):
        decode_event(json.dumps(data))
