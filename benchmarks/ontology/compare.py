"""Correctness-gated, descriptive timings. No automatic superiority claim."""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import platform
import statistics
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

import rdflib

from osahr import Runtime
from osahr.rewrite import RewriteEngine

from .baseline import DirectSSA, transitions
from .model import FIXTURE, compile_model, load_snapshot, project_state, replicate

ROOT = Path(__file__).resolve().parents[2]
# Declared before measurement. These are development controls, not held-out
# real-world validation samples. Never reinterpret them as confirmatory evidence.
PERFORMANCE_SEEDS = (26090501, 26090502, 26090503)
STATISTICAL_SEED_START = 730000


def osahr_transitions(snapshot, state, compiler=compile_model):
    runtime = Runtime(compiler(snapshot, state), root_seed=0)
    return runtime_transitions(runtime, snapshot)


def runtime_transitions(runtime, snapshot):
    result = {}
    for occurrence in runtime.enabled_occurrences():
        rewritten = RewriteEngine().apply(
            graph=runtime.graph, boundary=runtime.boundary,
            parameters=runtime.parameters, memory=runtime.memory,
            rule=occurrence.rule, match=occurrence.match, time=runtime.time,
            delta_time=0.0, event_index=0, event_id="generator-check",
        )
        target = project_state(rewritten.graph, snapshot)
        result[target] = result.get(target, 0.0) + occurrence.hazard
    return result


def check_generator(snapshot, compiler=compile_model):
    if len(snapshot.routes) > 8:
        raise ValueError("Exhaustive gate is capped at eight routes; use the base fixture")
    count = 0
    for state in itertools.product((False, True), repeat=len(snapshot.routes)):
        expected = transitions(snapshot, state)
        actual = osahr_transitions(snapshot, state, compiler)
        if expected.keys() != actual.keys() or any(
            not math.isclose(expected[key], actual[key], rel_tol=1e-12, abs_tol=1e-12)
            for key in expected
        ):
            raise AssertionError(f"Transition generator mismatch at {state}: {expected} != {actual}")
        count += len(actual)
    return {"states": 2 ** len(snapshot.routes), "transitions": count, "passed": True}


class OSAHRRunner:
    def __init__(self, snapshot, seed):
        self.snapshot = snapshot
        self.runtime = Runtime(compile_model(snapshot), root_seed=seed)
        self.indices = {route.uri: i for i, route in enumerate(snapshot.routes)}

    @property
    def state(self):
        return project_state(self.runtime.graph, self.snapshot)

    def step(self):
        event = self.runtime.step().event
        if event is None:
            return None
        updates = list(event.graph_delta.updated_vertices_after.values())
        if len(updates) != 1:
            raise AssertionError("Expected one route change per event")
        attrs = updates[0]
        return (event.post_time, self.indices[attrs["uri"]], attrs["up"])


ENGINES = {"direct_ssa": DirectSSA, "osahr": OSAHRRunner}


def check_first_jump(snapshot, samples=256):
    """Independent exponential waiting-time and categorical channel oracles.

    Six standard errors for waiting-time mean; Hoeffding family bound for
    channel frequencies. Wide smoke alarms, not distributional equivalence
    tests. Exhaustive generator comparison carries the law-equivalence gate.
    """
    if samples < 128:
        raise ValueError("At least 128 statistical samples required")
    rates = [r.failure if r.up else r.repair for r in snapshot.routes]
    total = math.fsum(rates)
    if total == 0:
        raise ValueError("Statistical fixture must have positive activity")
    tolerance = math.sqrt(math.log(4 * len(rates) / 1e-6) / (2 * samples))
    reports = {}
    for name, engine in ENGINES.items():
        waits, counts = [], [0] * len(rates)
        for seed in range(STATISTICAL_SEED_START, STATISTICAL_SEED_START + samples):
            event = engine(snapshot, seed).step()
            if event is None:
                raise AssertionError("Unexpected absorption")
            waits.append(event[0])
            counts[event[1]] += 1
        mean = statistics.mean(waits)
        if abs(mean - 1 / total) > 6 / (total * math.sqrt(samples)):
            raise AssertionError(f"{name}: exponential waiting-time mean failed")
        if any(abs(count / samples - rate / total) > tolerance for count, rate in zip(counts, rates)):
            raise AssertionError(f"{name}: event frequencies failed")
        reports[name] = {"mean_wait": mean, "expected_wait": 1 / total,
                         "channel_counts": counts, "passed": True}
    return {"samples_per_engine": samples, "seed_start": STATISTICAL_SEED_START,
            "frequency_tolerance": tolerance, "engines": reports}


def measure(snapshot, engine, seed, events):
    started = time.perf_counter_ns()
    simulator = engine(snapshot, seed)
    prepared = time.perf_counter_ns()
    trace = []
    for _ in range(events):
        event = simulator.step()
        if event is None:
            break
        trace.append(event)
    final = tuple(simulator.state)
    ended = time.perf_counter_ns()
    # Independently replay the common output contract, outside measured time.
    replay, previous = list(snapshot.initial), 0.0
    for timestamp, index, up in trace:
        if timestamp < previous or up == replay[index]:
            raise AssertionError("Invalid projected event trace")
        replay[index], previous = up, timestamp
    if tuple(replay) != final:
        raise AssertionError("Trace does not reconstruct final state")
    payload = {"trace": trace, "final": final}
    return {"seed": seed, "events": len(trace),
            "prepare_seconds": (prepared - started) / 1e9,
            "run_seconds": (ended - prepared) / 1e9,
            "total_seconds": (ended - started) / 1e9,
            "simulation_time": previous, "final_up": sum(final),
            "output_sha256": hashlib.sha256(json.dumps(payload).encode()).hexdigest()}


def source_manifest():
    paths = [*sorted((ROOT / "osahr").glob("*.py")),
             *sorted(Path(__file__).parent.glob("*.py")), FIXTURE,
             ROOT / "benchmarks/ontology/README.md", ROOT / "pyproject.toml",
             ROOT / "tests/test_ontology_benchmark.py"]
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = "unavailable", None
    return {"git_revision": revision, "git_dirty": dirty, "sha256": hashes}


def run(copies=(1, 4, 16), events=100, samples=256):
    if events < 1 or not copies or any(n < 1 for n in copies):
        raise ValueError("Positive events and copy counts required")
    start = time.perf_counter_ns()
    snapshot = load_snapshot()
    load_seconds = (time.perf_counter_ns() - start) / 1e9
    correctness = check_generator(snapshot)
    statistics_report = check_first_jump(snapshot, samples)
    measurements = []
    for size in copies:
        scaled = replicate(snapshot, size)
        # One discarded warmup each. Then counterbalance order across seeds.
        for engine in ENGINES.values():
            measure(scaled, engine, 999, min(events, 10))
        runs = {name: [] for name in ENGINES}
        for index, seed in enumerate(PERFORMANCE_SEEDS):
            order = tuple(ENGINES) if index % 2 == 0 else tuple(reversed(ENGINES))
            for name in order:
                runs[name].append(measure(scaled, ENGINES[name], seed, events))
        medians = {name: statistics.median(row["total_seconds"] for row in rows)
                   for name, rows in runs.items()}
        measurements.append({"copies": size, "routes": len(scaled.routes), "runs": runs,
                             "median_total_seconds": medians,
                             "osahr_over_baseline_total_ratio": medians["osahr"] / medians["direct_ssa"]})
    return {"protocol": "ontology-route-control-v1", "claim_status": "development_probe_only",
            "python": platform.python_version(), "platform": platform.platform(),
            "cpu_count": os.cpu_count(), "processor": platform.processor(),
            "timer_resolution_seconds": time.get_clock_info("perf_counter").resolution,
            "rdflib": rdflib.__version__, "source": source_manifest(),
            "fixture": asdict(snapshot), "ontology_load_seconds": load_seconds,
            "requested_events": events, "correctness": correctness,
            "first_jump": statistics_report, "measurements": measurements,
            "limitations": ["Not Foundry integration or comparison",
                            "No real-world calibration or user-value evidence",
                            "OSAHR retains richer native audits than the baseline",
                            "Fixed-event timings, not equal simulated-time ensembles",
                            "Three timing repetitions; no superiority inference",
                            "Memory and model-change engineering effort not measured"]}
