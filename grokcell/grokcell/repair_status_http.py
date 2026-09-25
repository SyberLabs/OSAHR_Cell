"""Read-only HTTP status for the GrokCell repair probe."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .repair_experiment import ARMS, PAIRED_PILOT_READY, VARIANTS, verify_contracts


class RepairStatusHandler(BaseHTTPRequestHandler):
    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path not in ("/healthz", "/preflight"):
            self._reply(404, {"error": "not_found"})
            return
        try:
            contracts = verify_contracts()
        except (OSError, ValueError):
            self._reply(503, {"status": "frozen_contract_invalid"})
            return
        if self.path == "/healthz":
            self._reply(200, {"status": "ok"})
        else:
            self._reply(200, {
                "status": "offline_preflight_only",
                "contract_count": len(contracts),
                "variants": list(VARIANTS),
                "arms": list(ARMS),
                "paired_pilot_ready": PAIRED_PILOT_READY,
                "live_execution_enabled": False,
            })

    def do_POST(self) -> None:
        self._reply(405, {"error": "method_not_allowed"})


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    with ThreadingHTTPServer(("0.0.0.0", port), RepairStatusHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
