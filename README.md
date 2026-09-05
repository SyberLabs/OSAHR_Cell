# OSAHR 0.2

**This is the project:** [SyberLabs/OSAHR_Cell](https://github.com/SyberLabs/OSAHR_Cell).
`sykosyber/osahr_project` is a private Cursor workspace, not a second OSAHR. See `CELL.md`.

Exact open stochastic adaptive graph-rewrite over a typed directed hypergraph.
Python 3.11+, no runtime dependencies.

The kernel is `osahr/`. Experiments are confirmatory records on that kernel.
Invariants: `ARCHITECTURE.md`. Licensed packets over Experiment 06: `workbench/`.

## Install

```bash
python -m pip install -e .
python -m pytest
```

Or `python -m pip install osahr-0.2.1-py3-none-any.whl`.

## Minimal CTMC

```python
from osahr import BoundaryState, Expr, Hypergraph, Model, PatternGraph, Rule, Runtime, Schema, StateAssignment, TemplateGraph

schema = Schema([], [])
graph = Hypergraph(schema)
rule_a = Rule("a", PatternGraph(()), TemplateGraph(()), Expr("p.a"), adaptation=(StateAssignment("memory.last", "a"),))
rule_b = Rule("b", PatternGraph(()), TemplateGraph(()), Expr("p.b"), adaptation=(StateAssignment("memory.last", "b"),))
model = Model(graph, BoundaryState(), (rule_a, rule_b), parameters={"a": 1.0, "b": 3.0}, memory={"last": None})
runtime = Runtime(model, root_seed=42)
print(runtime.step().event.post_time, runtime.memory["last"])
```

Schedulers: direct SSA, modified next-reaction, bounded thinning. Incremental matching is an optimization; the exhaustive matcher is the oracle. DPO-invalid embeddings are not stochastic channels.

More examples: `examples/adaptive_signal.py`. API detail: `ARCHITECTURE.md`.

```bash
python -m workbench decide workbench/scenarios/03-long-outage.json --out /tmp/osahr-packet
python -m workbench replay /tmp/osahr-packet/decision.json
```

Ontology execution probe (not a speed claim): `docs/VALIDATION_FRAMEWORK.md` and `benchmarks/ontology/README.md`.

## Experiments

Every public claim is graded **KNOWN**, **MEASURED**, **INFERRED**, or **PROPOSED**.
Confirmatory seeds are declared before execution. Artifacts are frozen with checksums.

These models explore mechanism. They are not calibrated deployments, not 3GPP-conformance simulators, and not replacements for ns-3, srsRAN, or a commercial RF twin.

| Experiment | Question | Status |
|---|---|---|
| [6G](osahr-6g/osahr_6g_experiment_release/EXPERIMENT_REPORT.md) | Does routing by what a task is *for* preserve value under disruption? | Executed |
| [01](liquid-osahr-experiment-01/EXPERIMENT_REPORT.md) | Can an irregular-time recurrent model supply intensities OSAHR consumes as an exact piecewise-constant law? | Executed |
| [02A](liquid-osahr-experiment-02a/liquid-osahr-experiment-02a/EXPERIMENT_REPORT.md) | Does closing the neural feedback loop improve counterfactual fidelity? | Executed |
| [02B](liquid-osahr-experiment-02b/liquid-osahr-exp02b-stage-final/EXPERIMENT_REPORT.md) | Can a mechanistically anchored residual improve a twin without sacrificing intervention fidelity? | Executed |
| [03](liquid-osahr-experiment-03/EXPERIMENT_REPORT.md) | Is trust in a learned residual a property of the query rather than of the model? | Reanalysis of frozen 02B artifacts |
| [04](liquid-osahr-experiment-04/EXPERIMENT_REPORT.md) | Does one calibrated trust coefficient survive across estimands at a shared horizon? | Executed |
| [05](liquid-osahr-experiment-05/EXPERIMENT_REPORT.md) | What can be *claimed*, not merely estimated, about a residual effect? | Formulation only; confirmatory **not executed** |
| [06](liquid-osahr-experiment-06/EXPERIMENT_REPORT.md) | Can a semantic vault and a deterministic controller gate rewrites without licensing unsupported claims? | Executed; seed 260826 |

Selected MEASURED results:

- **Semantic routing pays when capacity must be triaged.** 6G: +0.0369 timely goal utility (CI +0.0071 to +0.0677) and +0.0531 critical-task deadline success (CI +0.0142 to +0.0930) over a 15 s edge outage. No-outage control: 0.8778 vs 0.8783. The mechanism is conditional.
- **Predictive trust ≠ intervention trust.** 02B: residual trust improved factual hazard identification; intervention calibration still selected the mechanistic fallback (18/18 LOSO). One global scalar trust coefficient is not enough.
- **Closing a neural loop is not automatically better.** 02A: no-jump and frozen-open-loop ablations recovered oracle intervention effects better than the fully closed learned jump model in several regimes.
- **Acting and claiming are separate licenses.** 06 scenario 3: ensemble signs disagree while every arm's point estimate is negative. The controller could act; it was not licensed to report the sign as a directed effect.

`research_directions/` is PROPOSED notes, not science. Do not cite it as MEASURED.
GrokCell (`grokcell/`) is a prototype control-plane host, not a confirmatory record.
