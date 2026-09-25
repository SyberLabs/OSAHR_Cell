from service import availability


def test_reports_available_stock_after_reservation():
    state = {"SKU-A": {"on_hand": 8, "reserved": 3}}
    assert availability(state, "SKU-A") == {
        "sku": "SKU-A", "on_hand": 8, "reserved": 3, "available": 5
    }
    assert state == {"SKU-A": {"on_hand": 8, "reserved": 3}}


def test_unknown_sku_has_zero_counts():
    assert availability({}, "SKU-MISSING") == {
        "sku": "SKU-MISSING", "on_hand": 0, "reserved": 0, "available": 0
    }
