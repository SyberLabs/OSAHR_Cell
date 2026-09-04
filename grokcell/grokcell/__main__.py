"""Run the GrokCell surface once. Prototype, not confirmatory."""
from __future__ import annotations

import json

from grokcell.surface import GrokCellSurface
from grokcell.tools import ToolRegistry


def main() -> None:
    surface = GrokCellSurface.open()
    tools = ToolRegistry(surface)
    tools.call(
        "bus.post",
        {
            "source_owner": "MOUTH",
            "kind": "forge.propose",
            "priority": 1,
            "payload": {
                "name": "core.api",
                "constraint": "critical_module",
                "verified": True,
                "depends_on": [],
            },
        },
    )
    drained = tools.call("bus.drain", {})
    inspect = tools.call("surface.inspect", {})
    print(json.dumps({"drain": drained, "inspect": inspect}, indent=2))


if __name__ == "__main__":
    main()
