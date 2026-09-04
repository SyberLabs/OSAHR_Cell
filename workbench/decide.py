"""CLI: mint or replay a licensed decision packet."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workbench.packet import (
    REPO,
    WorkbenchError,
    build_packet,
    render_html,
    replay_packet,
)

DEFAULT_ANALYSIS = REPO / "liquid-osahr-experiment-06" / "artifacts" / "analysis.json"
DEFAULT_FREEZE = REPO / "liquid-osahr-experiment-06" / "artifacts" / "FROZEN.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="workbench",
        description="Mint or replay an OSAHR decision packet from the frozen 06 corpus.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    decide_p = sub.add_parser("decide", help="validate a scenario and emit JSON+HTML")
    decide_p.add_argument("scenario")
    decide_p.add_argument("--out", required=True)
    decide_p.add_argument("--analysis", default=str(DEFAULT_ANALYSIS))
    decide_p.add_argument("--freeze", default=str(DEFAULT_FREEZE))
    replay_p = sub.add_parser("replay", help="recompute licenses from the frozen corpus")
    replay_p.add_argument("packet")
    replay_p.add_argument("--analysis", default=str(DEFAULT_ANALYSIS))
    replay_p.add_argument("--freeze", default=str(DEFAULT_FREEZE))
    args = parser.parse_args(argv)
    try:
        if args.cmd == "decide":
            scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
            packet = build_packet(scenario, args.analysis, args.freeze)
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "decision.json").write_text(
                json.dumps(packet, indent=2) + "\n", encoding="utf-8"
            )
            (out / "decision.html").write_text(render_html(packet), encoding="utf-8")
            print(json.dumps({
                "checksum": packet["checksum"],
                "action": packet["recommendation"]["action"],
                "claim_license": packet["licenses"]["claim"]["granted"],
                "html": str(out / "decision.html"),
            }))
            return 0
        packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
        replayed = replay_packet(packet, args.analysis, args.freeze)
        print(json.dumps({"replay": "ok", "checksum": replayed["checksum"]}))
        return 0
    except WorkbenchError as exc:
        print(f"workbench: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
