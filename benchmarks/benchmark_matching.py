"""Reproducible sparse matching comparison; output JSON, no timing assertions.

Run: python -m benchmarks.benchmark_matching --vertices 24 48 96 --samples 3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from osahr import HyperedgeType, Hypergraph, Matcher, PatternEdge, PatternGraph, PatternVertex, PortSpec, Schema, VertexType
from osahr.indexed_matcher import IndexedMatcher


def build_ring(size):
    schema = Schema([VertexType("V")], [HyperedgeType(
        "Arc", {"s": PortSpec("s", "V")}, {"t": PortSpec("t", "V")},
    )])
    graph = Hypergraph(schema)
    ids = [graph.add_vertex("V").entity_id for _ in range(size)]
    for index, source in enumerate(ids):
        graph.add_edge("Arc", {"s": (source,)}, {"t": (ids[(index + 1) % size],)})
    pattern = PatternGraph((PatternVertex("a", "V"), PatternVertex("b", "V")),
                           (PatternEdge("e", "Arc", {"s": ("a",)}, {"t": ("b",)}),))
    return graph, pattern


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vertices", type=int, nargs="+", default=[24, 48, 96])
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()
    if min(args.vertices) < 2 or args.samples < 1:
        parser.error("vertices must be >= 2 and samples >= 1")
    root = Path(__file__).resolve().parents[1]
    report = {
        "python": platform.python_version(), "platform": platform.platform(),
        "scope": "matching only; excludes graph creation, rewriting, hashing and scheduling",
        "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                          for name in ("osahr/matcher.py", "osahr/indexed_matcher.py", "osahr/incremental.py",
                                       "benchmarks/benchmark_matching.py")},
        "results": [],
    }
    for size in args.vertices:
        graph, pattern = build_ring(size)
        for mode, bindings in (
            ("full", {}),
            ("vertex_anchor", {"prebound_vertices": {"a": next(iter(graph.vertices))}}),
            ("edge_anchor", {"prebound_edges": {"e": next(iter(graph.edges))}}),
        ):
            timings = {"reference": [], "indexed": []}
            engines = {"reference": Matcher(), "indexed": IndexedMatcher()}
            # Warm up both searches and compare the complete records.
            expected = engines["reference"].find_pattern_matches(graph, pattern, **bindings)
            assert engines["indexed"].find_pattern_matches(graph, pattern, **bindings) == expected
            for sample in range(args.samples):
                for name in (("reference", "indexed") if sample % 2 == 0 else ("indexed", "reference")):
                    start = time.perf_counter()
                    matches = engines[name].find_pattern_matches(graph, pattern, **bindings)
                    timings[name].append(time.perf_counter() - start)
                    assert matches == expected
            medians = {name: statistics.median(values) for name, values in timings.items()}
            report["results"].append({
                "vertices": size, "edges": size, "mode": mode, "matches": len(expected),
                "seconds": timings, "median_seconds": medians,
                "speedup": medians["reference"] / medians["indexed"],
            })
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
