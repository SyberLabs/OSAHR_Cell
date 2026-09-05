# OSAHR Cell

**A Python research toolkit for systems whose connections and behavior change through random events.**

OSAHR stands for *open stochastic adaptive hypergraph rewriting*. You describe a
system as typed entities and relationships, define rules that change them, and
assign each applicable rule occurrence an event rate. The kernel samples when
events happen, applies valid changes atomically, and records the resulting state
for replay and analysis. A hypergraph lets one relationship connect several entities.

This repository contains the kernel, network-control experiments, and prototypes
that turn recorded evidence into reviewable decisions.

**Status:** research / alpha · **Kernel:** 0.2.1 · **Python:** 3.11+ · **License:** [MIT](LICENSE)

The core `osahr` package has no third-party runtime dependencies. Experiments and
optional tools have their own requirements. Exact simulation refers to the
specified mathematical model; it does not establish that the model predicts a
real system accurately.

## Start here

- **Run a model:** follow the quick start below.
- **Inspect a decision:** try the [decision workbench](#decision-workbench).
- **Understand the guarantees:** read [kernel semantics](#kernel-semantics) and the [architecture](ARCHITECTURE.md).
- **Evaluate the evidence:** browse the [experiments](#experiments-and-evidence) and [validation framework](docs/VALIDATION_FRAMEWORK.md).

## Quick start

From a source checkout, using Python 3.11 or newer (a virtual environment is recommended):

```sh
git clone https://github.com/SyberLabs/OSAHR_Cell.git
cd OSAHR_Cell
python -m pip install -e .
python examples/adaptive_signal.py
```

If you already have this checkout, run the last two commands from its root.
The [adaptive signal example](examples/adaptive_signal.py) models two agents,
signal creation and reception, an external input, and a scheduled parameter
change. It prints the event count, receiver state, memory, and final state hash.

### A minimal stochastic model

This example isolates event selection: two rules leave the graph unchanged and
record which event occurred. Rates of 1 and 3 give a total rate of 4, so the mean
waiting time is 0.25 model time units and each event has probability 1/4 or 3/4.

```python
from osahr import (
    BoundaryState, Expr, Hypergraph, Model, PatternGraph, Rule,
    Runtime, Schema, StateAssignment, TemplateGraph,
)

rules = tuple(
    Rule(
        name,
        PatternGraph(()),
        TemplateGraph(()),
        Expr(f"p.{name}"),
        adaptation=(StateAssignment("memory.last", name),),
    )
    for name in ("a", "b")
)

model = Model(
    Hypergraph(Schema([], [])),
    BoundaryState(),
    rules,
    parameters={"a": 1.0, "b": 3.0},
    memory={"last": None},
)

runtime = Runtime(model, root_seed=42)
event = runtime.step().event
print(event.post_time, runtime.memory["last"])
```

Use the adaptive signal example above to see actual graph matching and rewriting.

## Kernel semantics

The committed state contains the graph, open boundaries, active rules, adaptive
parameters, explicit memory, simulation time, and event index. History that
affects future events belongs in that state.

- **Typed rewriting:** injective pattern matching, attribute guards, positive and
  negative graph conditions, and double-pushout (DPO) deletion rules. Deleting a
  vertex requires explicitly handling its incident edges and boundary bindings.
  Invalid matches are excluded before their rates enter event selection.
- **Three schedulers:** direct stochastic simulation (SSA) and modified next
  reaction for piecewise-constant rates; bounded thinning for continuously
  time-varying rates with declared valid finite-window upper bounds. Exactness
  depends on those contracts. Bound violations detected at evaluated points are
  errors; the runtime does not silently clamp rates.
- **Incremental matching:** local graph changes update affected matches while
  the exhaustive matcher remains the correctness reference. Graph conditions
  fall back to full recomputation when remote changes could affect applicability.
- **Adaptation:** parameter constraints are validated atomically. Precompiled
  rule templates can be instantiated, enabled, disabled, or removed within
  declared limits; runs do not compile arbitrary new source code.
- **Analysis and replay:** deterministic seed-partitioned ensembles, first-passage
  recording, state hashes, snapshots, delta replay, and path likelihoods. Exact
  likelihood for time-varying rates additionally requires all needed integrated
  hazards.

To use incremental matching with the next-reaction scheduler, reuse `model`
from the example:

```python
from osahr import RuntimeConfig, SchedulerKind

runtime = Runtime(
    model,
    root_seed=42,
    config=RuntimeConfig(
        scheduler=SchedulerKind.NEXT_REACTION,
        matcher_backend="incremental",
        incremental_verify=True,
    ),
)
```

`incremental_verify=True` compares cached matches with exhaustive matching during
development. It adds verification work; omit it for normal execution.

The kernel requires finite graphs and finite enabled match sets at each committed
event. It does not silently truncate matches or switch to approximate simulation.
Delayed completion events, non-injective matching, synchronized multi-runtime
rewrites, and approximate acceleration remain outside the current implementation.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the full contracts and
[RESEARCH_NOTES.md](RESEARCH_NOTES.md) for their rationale.

Checkpoint files use Python pickle inside a hashed, versioned envelope. Load
checkpoints only from trusted sources.

## Decision workbench

The workbench creates a JSON and HTML evidence packet from the frozen Experiment
06 corpus, then verifies it through replay. It separates whether a decision may
be taken from whether the evidence supports claiming a directed effect.

Run from the repository root; the output path below is relative and works on
Windows, macOS, and Linux:

```sh
python -m workbench decide workbench/scenarios/03-long-outage.json --out ../osahr-packet
python -m workbench replay ../osahr-packet/decision.json
```

This uses recorded results rather than running a new simulation. It rejects
unknown scenarios, untrusted replacement ensembles, and unsupported claim grades.
See [workbench/README.md](workbench/README.md) for the scenario format and decision
rules.

## Experiments and evidence

Two research tracks use the kernel: a network twin studying task-aware control
under disruption, and the Liquid-OSAHR series combining continuous-time neural
state with stochastic rewriting. Experiment 06 brings them together.

The reports distinguish **KNOWN**, **MEASURED**, **INFERRED**, and **PROPOSED**
claims. Read each report's controls and execution status alongside its results.

- **[6G 01 — Semantic control](osahr-6g/osahr_6g_experiment_release/EXPERIMENT_REPORT.md):**
  executed, with 30 trajectories per policy and outage controls. Task-aware
  routing improved utility under the tested outage; the no-outage control showed
  essentially no advantage.
- **[Liquid 01 — Learned event rates](liquid-osahr-experiment-01/EXPERIMENT_REPORT.md):**
  executed with three training seeds and a recurrent-model comparison.
- **[Liquid 02A — Closed-loop neural feedback](liquid-osahr-experiment-02a/liquid-osahr-experiment-02a/EXPERIMENT_REPORT.md):**
  executed. Closing the feedback loop did not consistently improve intervention
  fidelity; simpler ablations performed better in several regimes.
- **[Liquid 02B — Intervention calibration](liquid-osahr-experiment-02b/liquid-osahr-exp02b-stage-final/EXPERIMENT_REPORT.md):**
  executed, including a 400-run untouched confirmatory holdout. Better prediction
  did not establish better intervention estimates; no single trust coefficient
  dominated the holdout.
- **[Liquid 03 — Query-conditioned trust](liquid-osahr-experiment-03/EXPERIMENT_REPORT.md):**
  reanalysis of frozen 02B artifacts, with no new simulation.
- **[Liquid 04 — Multi-query calibration](liquid-osahr-experiment-04/EXPERIMENT_REPORT.md):**
  executed, testing calibration across several quantities at a shared horizon.
- **[Liquid 05 — Claim status](liquid-osahr-experiment-05/EXPERIMENT_REPORT.md):**
  formulation and instrument check only. The declared 22-second confirmatory run
  has **not been executed**.
- **[Liquid 06 — NetworkBrain](liquid-osahr-experiment-06/EXPERIMENT_REPORT.md):**
  executed with seed 260826 and a 60-second horizon. A deterministic controller
  gates rewrites and evidence claims; the confirmatory run used no language model.

These are mechanism studies using surrogate models. They do not establish
real-network calibration or standards conformance. The 02B model uses a
standards-informed propagation model; it is not a full radio-network simulator.

### Performance and product validation

The [open-ontology comparison](benchmarks/ontology/README.md) checks an OSAHR model
against an independently implemented direct simulator before comparing timing.
The [recorded result](benchmarks/ontology/RESULTS.md) passed transition-law checks,
but plain direct simulation was substantially faster on the easy control. No
general speed advantage or real-world product benefit has been established.

The [locality benchmark](benchmarks/benchmark_incremental.py) compares the kernel's
reference and incremental backends. Its timings concern that workload and
environment; both backends must finish with the same canonical state hash.

The [validation framework](docs/VALIDATION_FRAMEWORK.md) defines what further
evidence would be needed to justify using OSAHR in an ontology-backed workflow.

## Development

Install the test dependencies and run the root-configured kernel, ontology-probe,
and workbench tests:

```sh
python -m pip install -e ".[benchmark]" pytest
python -m pytest
```

The tests cover structural validity, scheduler behavior, adaptive rollback,
snapshot and delta replay, and agreement between reference and incremental
execution. Experiment packages and prototypes have separate instructions and
dependencies; the root command does not run every experiment's suite.

Additional entry points:

- [Kernel source](osahr/) and [tests](tests/)
- [GrokCell](grokcell/README.md) — prototype agent control plane
- [Ontology admission profile](ontology-kernel/README.md) — bounded compatibility experiment
- [Research directions](research_directions/README.md) — proposals and research ledger
- [Changelog](CHANGELOG.md)

The canonical project is [SyberLabs/OSAHR_Cell](https://github.com/SyberLabs/OSAHR_Cell).
See [CELL.md](CELL.md) for repository ownership and workspace conventions.
