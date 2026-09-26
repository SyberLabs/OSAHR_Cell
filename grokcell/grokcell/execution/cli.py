"""Bounded local demo and operator CLI. Never silently falls back from live mode."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .checking import DependencyVerifier, IsolatedRepairVerifier
from .codec import decode
from .durable import DurableRuntime, control, inspect_state
from .examples import FixtureChooser, FixtureWorker
from .journal import read_json
from .providers import HuggingFaceWorker, JevAdapter, ProviderConfig, preflight
from .records import JsonSnapshot, Limits, Permission
from .report import write_report
from .runtime import ExecutionBlocked
from . import workflows

_EFFECTS = ("read", "decide", "generate", "check", "admit", "yield")
_DESCRIPTIONS = {
    "repair": "A candidate corrects inventory availability arithmetic. The report identifies whether checks used fixture bytes or isolated behavior.",
    "dependency": "A structured assessment records a dependency change, preserves unknown compatibility, and explicitly withholds upgrade authority."}


def _live_configuration(path):
    if path is None:
        raise ExecutionBlocked("live mode requires an explicit operator configuration")
    data = read_json(Path(path), 64_000)
    if (set(data) != {"authorized", "budget_scope", "limits", "jev", "hf"}
            or data["authorized"] is not True or data["budget_scope"] != "dedicated_credentials_operator_reviewed_bounds"):
        raise ExecutionBlocked("explicit authorization and reviewed account scope required")
    limits = Limits(**data["limits"])
    jev, hf = ProviderConfig(**data["jev"]), ProviderConfig(**data["hf"])
    if jev.provider != "jev" or hf.provider != "hf":
        raise ValueError("provider configuration mismatch")
    if jev.max_charge_microusd + hf.max_charge_microusd > limits.max_microusd:
        raise ExecutionBlocked("insufficient authorized workflow budget")
    status = preflight()
    if not status["typesafe_credential_present"] or not status["hf_credential_present"]:
        raise ExecutionBlocked("live provider credentials are missing; no fallback or call made")
    return limits, jev, hf


def execute(name, state_dir, *, mode="offline", config_path=None, resume=False):
    state_dir = Path(state_dir)
    source = workflows.REPAIR_OBSERVATION if name == "repair" else workflows.DEPENDENCY_OBSERVATION
    worker_content = workflows.REPAIRED_COMPONENT if name == "repair" else workflows.assessment_bytes(source)
    verifier = workflows.RepairBytesVerifier() if name == "repair" else DependencyVerifier(source)
    limits = Limits(max_steps=128, max_calls=8, max_seconds=600)
    chooser = FixtureChooser("repair" if name == "repair" else "assess")
    workers = {"generate": FixtureWorker(worker_content)}
    if mode == "live":
        limits, jev, hf = _live_configuration(config_path)
        chooser = JevAdapter(jev)
        workers = {"generate": HuggingFaceWorker(hf, output_key="module" if name == "repair" else None)}
    if mode in ("isolated", "live") and name == "repair":
        verifier = IsolatedRepairVerifier(os.environ.get("GROKCELL_SANDBOX_IMAGE", ""))
    deps = JsonSnapshot.capture({"input_snapshot": source.identity, "workflow": workflows.workflow_identity(name)})
    permission = Permission("local-demo-grant", "operator", _EFFECTS, time.time() + limits.max_seconds)
    existing = state_dir / "CURRENT.json"
    if existing.exists() or existing.is_symlink():
        doc = inspect_state(state_dir)
        permission = decode(doc["configuration"]["permission"])
    elif resume:
        raise ExecutionBlocked("run does not exist; resume cannot create or reset a run")
    with DurableRuntime(state_dir=state_dir, run_id=name, workflow_id=workflows.workflow_identity(name),
                        permission=permission, dependencies=deps, chooser=chooser, workers=workers,
                        verifier=verifier, limits=limits, allow_live=mode == "live") as runtime:
        if resume and runtime.audit()["paused"]:
            runtime.resume()
        result = getattr(workflows, name)(runtime, source)
        audit = runtime.audit()
        candidate = ""
        if runtime._accepted:
            candidate = runtime._candidates[runtime._accepted[-1].candidate_hash].content.decode("utf-8")
        return {"workflow": name, "description": _DESCRIPTIONS[name], "audit": audit,
                "candidate": candidate, "result": asdict(result) if not isinstance(result, JsonSnapshot) else result.value()}


def _child(name, state, mode, *, resume=False):
    command = [sys.executable, "-m", "grokcell.execution", "run", "--workflow", name,
               "--state", str(state), "--mode", mode]
    if resume:
        command += ["--resume"]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if proc.returncode:
        raise ExecutionBlocked("demo child failed: " + proc.stderr[:1000])
    return json.loads(proc.stdout)


def demo(output, mode="offline"):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    runs = []
    for name in ("repair", "dependency"):
        first = _child(name, output / (name + "-state"), mode)
        replay = _child(name, output / (name + "-state"), mode, resume=True)
        equal = (first["result"] == replay["result"]
                 and first["audit"]["calls"] == replay["audit"]["calls"] == 2
                 and first["audit"]["revision"] == replay["audit"]["revision"] == 1)
        if not equal:
            raise ExecutionBlocked("process replay invariant failed")
        replay["replay_equal"] = True
        runs.append(replay)
        with (output / (name + ".json")).open("x", encoding="utf-8") as handle:
            json.dump(replay, handle, indent=2)
        with (output / (name + (".py.txt" if name == "repair" else ".candidate.json"))).open("x", encoding="utf-8") as handle:
            handle.write(replay["candidate"])
    write_report(output / "index.html", runs)
    with (output / "README.txt").open("x", encoding="utf-8") as handle:
        handle.write("Open index.html. Reports are recorded evidence, not live provider execution.\n"
                     "State folders contain operator-owned journals; do not publish them with private inputs.\n"
                     "No deployment permission or performance claim is granted.\n")
    return {"report": str(output / "index.html"), "mode": mode, "process_restart_replay": True,
            "workflows": [item["workflow"] for item in runs], "live_provider_calls": 0}


def release_check(output):
    """Local entrypoint rollback drill; preserves state and never rewinds its ledger."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    state = output / "state"
    first = _child("dependency", state, "offline")
    bad = output / "bad.py"
    good = output / "good.py"
    bad.write_text("raise SystemExit(42)\n", encoding="utf-8")
    good.write_text("from grokcell.execution.cli import main\nraise SystemExit(main())\n", encoding="utf-8")
    current = output / "current.py"
    current.symlink_to(bad.name)
    failed = subprocess.run([sys.executable, str(current)], capture_output=True, timeout=20)
    if failed.returncode != 42:
        raise ExecutionBlocked("failure injection did not run")
    replacement = output / ".current-next"
    replacement.symlink_to(good.name)
    os.replace(replacement, current)
    replay = subprocess.run([sys.executable, str(current), "run", "--workflow", "dependency",
                             "--state", str(state), "--resume"], capture_output=True, text=True, timeout=30)
    if replay.returncode:
        raise ExecutionBlocked("rollback smoke failed: " + replay.stderr[:1000])
    after = json.loads(replay.stdout)
    if first["result"] != after["result"] or after["audit"]["calls"] != 2:
        raise ExecutionBlocked("rollback reset state or repeated effects")
    result = {"scope": "local_entrypoint_failure_and_rollback_not_production_release",
              "failure_exit_code": failed.returncode, "rollback_verified": True,
              "adapter_calls_after_rollback": after["audit"]["calls"], "accepted_revision": after["audit"]["revision"]}
    (output / "evidence.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="GrokCell decision execution: bounded internal preview")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("repair", "dependency"):
        legacy = commands.add_parser(name, help="original in-memory fixture demonstration")
        legacy.add_argument("--replay", action="store_true")
    run = commands.add_parser("run", help="persistent run or process-restart replay")
    run.add_argument("--workflow", choices=("repair", "dependency"), required=True)
    run.add_argument("--state", type=Path, required=True)
    run.add_argument("--mode", choices=("offline", "isolated", "live"), default="offline")
    run.add_argument("--config", type=Path)
    run.add_argument("--resume", action="store_true")
    for name in ("cancel", "revoke", "inspect"):
        item = commands.add_parser(name)
        item.add_argument("--state", type=Path, required=True)
    item = commands.add_parser("demo")
    item.add_argument("--out", type=Path, required=True)
    item.add_argument("--mode", choices=("offline", "isolated"), default="offline")
    item = commands.add_parser("release-check")
    item.add_argument("--out", type=Path, required=True)
    commands.add_parser("preflight")
    args = parser.parse_args(argv)
    try:
        if args.command in ("repair", "dependency"):
            from .examples import demo_runtime, repair_workflow, dependency_workflow
            rt = demo_runtime(args.command)
            workflow = repair_workflow if args.command == "repair" else dependency_workflow
            workflow(rt)
            if args.replay:
                workflow(rt)
            result = rt.audit()
        elif args.command == "run":
            result = execute(args.workflow, args.state, mode=args.mode, config_path=args.config, resume=args.resume)
        elif args.command == "demo":
            result = demo(args.out, args.mode)
        elif args.command == "release-check":
            result = release_check(args.out)
        elif args.command in ("cancel", "revoke"):
            control(args.state, args.command)
            result = {"action": args.command, "recorded": True}
        elif args.command == "inspect":
            value = inspect_state(args.state)
            result = {"schema": value["schema"], "configuration_hash": value["configuration_hash"],
                      "state": {key: value["state"][key] for key in ("_calls", "_steps", "_revision", "_canceled", "_epoch")}}
        else:
            result = preflight()
        print(json.dumps(result, indent=2))
        return 0
    except (ExecutionBlocked, ValueError, TypeError, OSError, RuntimeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}), file=sys.stderr)
        return 2
