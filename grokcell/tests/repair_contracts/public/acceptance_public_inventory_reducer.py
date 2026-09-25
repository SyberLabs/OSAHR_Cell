import pytest

from service import apply_event


def event(kind, quantity, sku="SKU-A", event_id="evt-1"):
    return {"event_id": event_id, "sku": sku, "kind": kind, "quantity": quantity}


def test_receive_adds_stock_without_mutating_input():
    before = {}
    after = apply_event(before, event("receive", 8))
    assert before == {}
    assert after == {"SKU-A": {"on_hand": 8, "reserved": 0}}


def test_reserve_changes_reserved_not_on_hand():
    before = {"SKU-A": {"on_hand": 8, "reserved": 0}}
    after = apply_event(before, event("reserve", 3))
    assert before == {"SKU-A": {"on_hand": 8, "reserved": 0}}
    assert after == {"SKU-A": {"on_hand": 8, "reserved": 3}}


def test_cannot_reserve_more_than_available():
    before = {"SKU-A": {"on_hand": 8, "reserved": 3}}
    with pytest.raises(ValueError):
        apply_event(before, event("reserve", 6))
    assert before == {"SKU-A": {"on_hand": 8, "reserved": 3}}
