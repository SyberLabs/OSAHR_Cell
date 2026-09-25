"""The deployed status surface cannot run or expose the repair loop."""
from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from grokcell.repair_status_http import RepairStatusHandler


def test_status_surface_is_read_only() -> None:
    with ThreadingHTTPServer(("127.0.0.1", 0), RepairStatusHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/healthz") as response:
                assert json.load(response) == {"status": "ok"}
            with urlopen(base + "/preflight") as response:
                status = json.load(response)
                assert status["contract_count"] == 9
                assert status["paired_pilot_ready"] is False
                assert status["live_execution_enabled"] is False
                assert "qwen_credential" not in status
                assert "jev_credential" not in status
            for request, expected in ((base + "/live", 404),
                                      (Request(base + "/preflight", method="POST"), 405)):
                try:
                    urlopen(request)
                except HTTPError as exc:
                    assert exc.code == expected
                else:
                    raise AssertionError("mutation route unexpectedly reachable")
        finally:
            server.shutdown()
            thread.join(timeout=2)
