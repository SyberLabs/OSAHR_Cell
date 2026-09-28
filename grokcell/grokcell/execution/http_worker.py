"""Trusted bounded HTTP transport child. Not an arbitrary-code execution facility."""
from __future__ import annotations

import json
import sys

from .providers import ProviderConfig, _post_http, _strict_json


def main():
    try:
        raw = sys.stdin.buffer.read(131_073)
        if len(raw) > 131_072:
            raise ValueError("input envelope too large")
        data = _strict_json(raw)
        if type(data) is not dict or set(data) != {"configuration", "payload"}:
            raise ValueError("invalid input envelope")
        configuration = ProviderConfig(**data["configuration"])
        result, request_id, elapsed = _post_http(configuration, data["payload"])
        print(json.dumps({"response": result, "request_id": request_id, "elapsed_ms": elapsed}, allow_nan=False))
        return 0
    except Exception:
        # Upstream exception text or response bodies can contain secrets.
        print("provider_transport_failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
