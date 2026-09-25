import pytest

from service import apply_event


def event(kind, quantity, sku="SKU-B", event_id="held-1"):
    return {"event_id": event_id, "sku": sku, "kind": kind, "quantity": quantity}


def test_later_reservation_preserves_other_sku_and_input():
    before = {
        "SKU-A": {"on_hand": 5, "reserved": 1},
        "SKU-B": {"on_hand": 11, "reserved": 0},
    }
    after = apply_event(before, event("reserve", 4))
    assert after == {
        "SKU-A": {"on_hand": 5, "reserved": 1},
        "SKU-B": {"on_hand": 11, "reserved": 4},
    }
    assert before["SKU-B"] == {"on_hand": 11, "reserved": 0}


def test_release_is_a_distinct_downstream_operation():
    before = {"SKU-C": {"on_hand": 7, "reserved": 5}}
    after = apply_event(before, event("release", 2, "SKU-C"))
    assert after == {"SKU-C": {"on_hand": 7, "reserved": 3}}
    assert before == {"SKU-C": {"on_hand": 7, "reserved": 5}}


def test_cannot_release_unreserved_stock():
    before = {"SKU-C": {"on_hand": 7, "reserved": 1}}
    with pytest.raises(ValueError):
        apply_event(before, event("release", 2, "SKU-C"))
    assert before == {"SKU-C": {"on_hand": 7, "reserved": 1}}
