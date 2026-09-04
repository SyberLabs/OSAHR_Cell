from service import render


def test_render_returns_markup():
    assert render() == "<ok>"
