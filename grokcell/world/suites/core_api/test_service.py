from service import ping


def test_ping_returns_pong():
    assert ping() == "pong"
