"""Run a synthetic offline circuit; never reads credentials or executes candidates."""
import argparse
import json

from .examples import demo_runtime, dependency_workflow, repair_workflow


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", choices=("repair", "dependency"))
    parser.add_argument("--replay", action="store_true", help="reuse the same in-memory journal")
    args = parser.parse_args(argv)
    runtime = demo_runtime(args.workflow)
    workflow = {"repair": repair_workflow, "dependency": dependency_workflow}[args.workflow]
    workflow(runtime)
    if args.replay:
        workflow(runtime)
    print(json.dumps(runtime.audit(), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
