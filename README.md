# OSAHR Cell

A Python research toolkit for simulating systems whose connections and behavior
change through random events.

Define typed entities, relationships, rewrite rules, and event rates. OSAHR
samples events, validates each change, and records the state for replay.

**Research / alpha · Python 3.11+ · [MIT](LICENSE)**

The core package has no third-party runtime dependencies.

## Quick start

```sh
git clone https://github.com/SyberLabs/OSAHR_Cell.git
cd OSAHR_Cell
python -m pip install -e .
python examples/adaptive_signal.py
```

The example models signal exchange between two agents, including external input
and adaptation. It prints the final state and a reproducible state hash.

## What's here

- **[Kernel](ARCHITECTURE.md):** typed hypergraph rewriting, three stochastic
  schedulers, incremental matching, adaptive parameters, and replay.
- **[Decision workbench](workbench/README.md):** reviewable evidence packets from
  frozen experiments, separating permission to act from support for a claim.
- **[GrokCell](grokcell/README.md):** prototype agent control plane.
- **[Ontology profile](ontology-kernel/README.md):** an experiment in validating
  proposed components against an ontology snapshot.

## Research

The network-control and Liquid-OSAHR experiments explore task-aware routing,
learned event rates, and intervention reliability.

Start with [semantic control](osahr-6g/osahr_6g_experiment_release/EXPERIMENT_REPORT.md),
[intervention calibration](liquid-osahr-experiment-02b/liquid-osahr-exp02b-stage-final/EXPERIMENT_REPORT.md),
or [NetworkBrain](liquid-osahr-experiment-06/EXPERIMENT_REPORT.md).
The [research ledger](research_directions/README.md) tracks further directions.

These are surrogate-model studies, not validated real-network predictions.
Exact simulation is conditional on the [model contracts](ARCHITECTURE.md).
The [ontology benchmark](benchmarks/ontology/RESULTS.md) passed transition-law
checks but was substantially slower than plain direct simulation.
See the [validation framework](docs/VALIDATION_FRAMEWORK.md) for open questions.

## Development

```sh
python -m pip install -e ".[benchmark]" pytest
python -m pytest
```

This runs the root-configured tests. Experiments and prototypes document their
own dependencies and test commands.

[Architecture](ARCHITECTURE.md) · [Research notes](RESEARCH_NOTES.md) ·
[Changelog](CHANGELOG.md) · [Repository guide](CELL.md)
