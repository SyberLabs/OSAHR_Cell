from service import availability


def test_available_is_not_the_on_hand_count():
    state = {"SKU-B": {"on_hand": 11, "reserved": 4}}
    assert availability(state, "SKU-B") == {
        "sku": "SKU-B", "on_hand": 11, "reserved": 4, "available": 7
    }


def test_query_is_scoped_to_requested_sku():
    state = {
        "SKU-A": {"on_hand": 100, "reserved": 99},
        "SKU-C": {"on_hand": 7, "reserved": 3},
    }
    assert availability(state, "SKU-C") == {
        "sku": "SKU-C", "on_hand": 7, "reserved": 3, "available": 4
    }
    assert state["SKU-C"] == {"on_hand": 7, "reserved": 3}
