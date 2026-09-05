import argparse
import json

from .compare import run


def main():
    parser = argparse.ArgumentParser(description="Correctness-gated ontology execution probe")
    parser.add_argument("--copies", type=int, nargs="+", default=[1, 4, 16])
    parser.add_argument("--events", type=int, default=100)
    parser.add_argument("--samples", type=int, default=256)
    args = parser.parse_args()
    print(json.dumps(run(tuple(args.copies), args.events, args.samples), indent=2))


if __name__ == "__main__":
    main()
