"""Microbenchmark: local single-vertex rewrites over a large match relation.

Run from repository root:
    python benchmarks/benchmark_incremental.py --vertices 2000 --events 200

This is not a stable performance contract; it is a locality smoke benchmark.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osahr import (
    AttributeSpec,
    BoundaryState,
    Expr,
    Hypergraph,
    Model,
    PatternGraph,
    PatternVertex,
    Rule,
    Runtime,
    RuntimeConfig,
    Schema,
    TemplateGraph,
    TemplateVertex,
    ValueKind,
    Var,
    VertexType,
)


def build_model(vertices: int) -> Model:
    schema = Schema(
        [VertexType("Node", {"x": AttributeSpec(ValueKind.FLOAT, required=True)})],
        [],
        schema_id="benchmark-locality",
    )
    graph = Hypergraph(schema)
    for i in range(vertices):
        graph.add_vertex("Node", {"x": float(i % 17)})
    rule = Rule(
        "tick",
        PatternGraph((PatternVertex("node", "Node", {"x": Var("x")}),)),
        TemplateGraph((TemplateVertex("node", "Node", {"x": Expr("x + 1.0")}),)),
        Expr("1.0 + 0.001 * x"),
    )
    return Model(graph, BoundaryState(), (rule,))


def run(model: Model, backend: str, events: int) -> tuple[float, Runtime]:
    runtime = Runtime(
        model,
        root_seed=20260811,
        config=RuntimeConfig(matcher_backend=backend),
    )
    # Include initial index construction in both measurements.
    start = time.perf_counter()
    runtime.run_events(events)
    elapsed = time.perf_counter() - start
    return elapsed, runtime


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vertices", type=int, default=2000)
    parser.add_argument("--events", type=int, default=200)
    args = parser.parse_args()
    model = build_model(args.vertices)
    inc_time, inc = run(model, "incremental", args.events)
    ref_time, ref = run(model, "reference", args.events)
    if inc.state_hash != ref.state_hash:
        raise SystemExit("ERROR: benchmark backends diverged")
    matcher = inc.occurrence_index.incremental
    print(f"vertices={args.vertices} events={args.events}")
    print(f"incremental_seconds={inc_time:.6f}")
    print(f"reference_seconds={ref_time:.6f}")
    print(f"speedup={ref_time / inc_time:.2f}x")
    print(f"full_recomputations={matcher.full_recomputations}")
    print(f"localized_recomputations={matcher.localized_recomputations}")
    print(f"final_state_hash={inc.state_hash}")


if __name__ == "__main__":
    main()
