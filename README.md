# OSAHR Python 0.2

**OSAHR** is a correctness-first kernel for an **open stochastic adaptive graph-rewrite system over a typed directed hypergraph**.

Version 0.2 moves the project beyond a reference Gillespie simulator into a multi-backend stochastic rewriting engine with exact incremental match maintenance, sparse next-reaction scheduling, exact bounded thinning for time-varying hazards, adaptive parameter contracts, trajectory likelihoods, deterministic ensembles, and safe finite meta-rewriting.

The implementation is dependency-free at runtime and targets Python 3.11+.

## Experiments

The kernel is the substrate. Everything below is built on it and lives in this repository.
Two lines of work run over the same 0.2 kernel: a **6G semantic-control twin**, and the
**Liquid-OSAHR** series pairing continuous-time neural state with exact stochastic
rewriting. Experiment 06 joins them.

Every report grades its public claims **KNOWN**, **MEASURED**, **INFERRED**, or
**PROPOSED**. Confirmatory seeds are declared in the spec before execution, and artifacts
are frozen with checksums before the run.

Start with the 6G experiment for a result, or with 02B for the methodology argument.

| Experiment | Question | Status |
|---|---|---|
| [6G 01](osahr-6g/osahr_6g_experiment_release/EXPERIMENT_REPORT.md): Goal-aware semantic control over a RAN/MEC twin | Does routing by what a task is *for* preserve application value under disruption? | Executed; 30 trajectories per policy, plus no-outage and severe-outage controls |
| [01](liquid-osahr-experiment-01/EXPERIMENT_REPORT.md): Liquid hazards over OSAHR | Can an irregular-time recurrent model supply event intensities that OSAHR consumes as an exact piecewise-constant stochastic law? | Executed; three training seeds, approximately parameter-matched GRU check |
| [02A](liquid-osahr-experiment-02a/liquid-osahr-experiment-02a/EXPERIMENT_REPORT.md): Closed-loop topology-coupled neural state | Does closing the neural feedback loop improve counterfactual fidelity? | Executed |
| [02B](liquid-osahr-experiment-02b/liquid-osahr-exp02b-stage-final/EXPERIMENT_REPORT.md): Intervention-calibrated standards-informed RAN twin | Can a mechanistically anchored liquid residual improve a twin without sacrificing intervention fidelity? | Executed; 400-run untouched confirmatory holdout |
| [03](liquid-osahr-experiment-03/EXPERIMENT_REPORT.md): Query-conditioned trust | Is trust in a learned residual a property of the query rather than of the model? | Reanalysis of frozen 02B artifacts; no new simulation |
| [04](liquid-osahr-experiment-04/EXPERIMENT_REPORT.md): Same-horizon multi-query calibration | Does one calibrated trust coefficient survive across estimands at a shared horizon? | Executed; calibration seed 440318, confirmatory seed 880419 |
| [05](liquid-osahr-experiment-05/EXPERIMENT_REPORT.md): Residual-hypothesis claim status | What can be *claimed*, not merely estimated, about a residual effect? | Formulation and instrument check only; 22 s confirmatory declared on seed 110518, **not executed** |
| [06](liquid-osahr-experiment-06/EXPERIMENT_REPORT.md): NetworkBrain stack | Can a semantic vault and a deterministic controller gate rewrites without licensing claims they cannot support? | Executed; seed 260826, 60 s horizon, no language model in confirmatory |

### Selected results

**Semantic routing pays only when capacity must be triaged.** In the 6G experiment, a
policy conditioned on task utility and urgency beat task-agnostic QoS on timely goal
utility by +0.0369 (95% bootstrap CI +0.0071 to +0.0677) and on critical-task deadline
success by +0.0531 (CI +0.0142 to +0.0930), over a 15 s edge outage with 30 independent
trajectories per policy. The no-outage control shows essentially no advantage: 0.8778
versus 0.8783 goal utility. The mechanism is conditional, and that control is why the
first number is worth reporting.

**Predictive trust and intervention trust are different quantities.** In 02B, full
residual trust improved factual hazard identification on validation and on every OOD
hazard set, yet intervention calibration over 18 independent scenarios still selected the
mechanistic fallback, stable across 18/18 leave-one-scenario-out folds and 96.67% of
20,000 stratified bootstrap recalibrations. On an untouched 400-run confirmatory holdout
no single trust coefficient dominated. One global scalar trust coefficient is not enough.

**Closing a neural feedback loop is not automatically better.** In 02A, no-jump and
frozen-open-loop ablations recovered oracle intervention effects better than the fully
closed learned jump model in several regimes. Learned feedback can recursively amplify
small hazard misspecification while the process stays mathematically well defined.

**Acting on an effect and claiming it are separate licenses.** In 06 scenario 3, ensemble
signs disagree while every arm's point estimate comes out negative. The controller was
allowed to act at that junction; it was not licensed to report the sign as a directed
effect. Doing so would have been an illegal promotion.

### Scope of the experiment models

These models are abstractions for exploring mechanism, not calibrated models of any real
deployment. 02B is a standards-informed FR1 system-level surrogate whose propagation
follows the 3GPP TR 38.901 UMi-Street-Canyon form; it is not a 3GPP-conformance simulator.
None of this replaces ns-3/5G-LENA, srsRAN, Sionna RT, or a commercial RF twin. OSAHR sits
above the PHY/RF layer as an adaptive semantic and control twin.

## What is implemented

### Structural semantics

- finite typed attributed directed hypergraphs;
- explicit role-indexed tail/head incidences;
- subtype-compatible vertex matching and port validation;
- injective typed pattern embeddings;
- variable binding and deterministic guards;
- positive and negative graph conditions (PAC/NAC);
- DPO-style deletion with explicit dangling-condition enforcement;
- deterministic IDs and canonical graph/state hashes;
- typed open boundary handles and external events;
- structural model composition.

### Exact stochastic semantics

Three schedulers are explicit model/runtime choices:

1. **Direct SSA**: exact CTMC simulation for piecewise-constant occurrence hazards.
2. **Modified next reaction**: independent internal Poisson clocks, preserving unaffected channel clocks across sparse local updates.
3. **Bounded thinning**: exact event generation for continuously time-varying hazards when each time-dependent occurrence supplies a finite dominating bound over the requested planning window.

A DPO-invalid pattern embedding is not a stochastic channel. Applicability is checked **before** its hazard contributes to total activity.

### Incremental execution

The exhaustive matcher remains the semantic oracle. The optimized backend maintains:

- per-rule match relations;
- entity -> match reverse dependencies;
- exact localized invalidation and rematching around graph deltas;
- subtype-aware rule dependency signatures;
- conservative full recomputation for PAC/NAC rules when a remote extension could change;
- an explicit match delta (`added`, `removed`, `revalidated`);
- a dynamic deterministic order-statistics tree for rule and match activity.

Unchanged occurrences are not globally re-stamped after every graph epoch. A current-epoch match is created only for the chosen event before atomic rewrite validation. This lets next-reaction channels preserve their internal clocks when a graph edit is provably unrelated.

### Adaptation

Adaptive state is part of the authoritative augmented state:

```text
X_t = (G_t, B_t, R_t, parameters_t, memory_t, t, n)
```

`AdaptiveParameter` declarations provide:

- global/rule/type/entity/boundary scope metadata;
- free, positive, nonnegative, bounded, and probability constraints;
- strict rejection or explicit projection semantics;
- atomic validation after event-driven or scheduled updates.

Reusable pure learning primitives include exponential traces, event-time eligibility traces, and Robbins-Monro updates.

### Meta-rewriting

The active transition repertoire `R_t` can evolve at runtime through safe, finite operations:

- instantiate a precompiled `RuleTemplate` with typed bounded meta-parameters;
- enable a rule;
- disable a rule;
- remove a rule.

No arbitrary source is compiled during a run. Dynamic rule hashes are included in the runtime state hash and meta-events are replayable.

### Analysis

- exact CTMC path log-likelihood from recorded hazards and survival integrals;
- optional analytic hazard-integral contracts for exact likelihoods under thinning;
- deterministic seed-partitioned ensembles;
- first-passage recording;
- numerical ensemble summaries;
- deterministic observables;
- causal event-footprint reconstruction;
- snapshots, delta replay, and canonical audit export.

## Install

```bash
python -m pip install osahr-0.2.0-py3-none-any.whl
```

For a source checkout:

```bash
python -m pip install -e .
python -m pytest
```

## Minimal exact CTMC

```python
from osahr import (
    BoundaryState,
    Expr,
    Hypergraph,
    Model,
    PatternGraph,
    Rule,
    Runtime,
    Schema,
    StateAssignment,
    TemplateGraph,
)

schema = Schema([], [])
graph = Hypergraph(schema)

rule_a = Rule(
    "a",
    PatternGraph(()),
    TemplateGraph(()),
    Expr("p.a"),
    adaptation=(StateAssignment("memory.last", "a"),),
)
rule_b = Rule(
    "b",
    PatternGraph(()),
    TemplateGraph(()),
    Expr("p.b"),
    adaptation=(StateAssignment("memory.last", "b"),),
)

model = Model(
    graph,
    BoundaryState(),
    (rule_a, rule_b),
    parameters={"a": 1.0, "b": 3.0},
    memory={"last": None},
)

runtime = Runtime(model, root_seed=42)
record = runtime.step().event
print(record.post_time, runtime.memory["last"])
```

The total activity is

```text
A(X) = sum_(r,m) a_(r,m)(X)
```

and direct SSA samples

```text
dt = -log(U_wait) / A(X)
```

then chooses an enabled occurrence proportionally to its hazard.

## Sparse modified-next-reaction backend

```python
from osahr import RuntimeConfig, SchedulerKind

runtime = Runtime(
    model,
    root_seed=42,
    config=RuntimeConfig(
        scheduler=SchedulerKind.NEXT_REACTION,
        matcher_backend="incremental",
    ),
)
```

Each occurrence owns an independent exponential internal threshold. When a local rewrite changes only a small dependency neighborhood, unaffected channels retain their accumulated internal time and previously planned firing clocks.

If an occurrence disappears, its residual clock is discarded. If an occurrence of the same structural identity later reappears after absence, it is treated as a newly born stochastic channel and receives a fresh independent threshold.

## Continuously time-varying hazards

A time-varying hazard must use `time` and declare a bound valid on `[time, horizon]`:

```python
rule = Rule(
    "arrival",
    PatternGraph(()),
    TemplateGraph(()),
    Expr("1.0 + time"),
    hazard_upper_bound=Expr("1.0 + horizon"),
)

runtime = Runtime(
    Model(Hypergraph(Schema([], [])), BoundaryState(), (rule,)),
    root_seed=7,
    config=RuntimeConfig(
        scheduler=SchedulerKind.THINNING,
        thinning_window=0.25,
    ),
)
```

The bound is checked at the window start and again against each evaluated candidate hazard. A bound violation is a hard error; the runtime never silently clamps an actual hazard to the proposed bound.

`peek_next_event_time()` does not advance authoritative simulation time. The thinning planner has its own cursor, so a deterministic event may still be inserted after a stochastic peek and before the proposed candidate.

### Exact likelihood for time-varying rules

Event generation via thinning is exact with a valid bound even without a closed-form integral. If exact path likelihood is also required, declare the integrated hazard over `[time, horizon]`:

```python
rule = Rule(
    "arrival",
    PatternGraph(()),
    TemplateGraph(()),
    Expr("1.0 + time"),
    hazard_upper_bound=Expr("1.0 + horizon"),
    hazard_integral=Expr(
        "(horizon-time) + 0.5*(horizon*horizon-time*time)"
    ),
)
```

The event record then carries the exact survival integral. If any time-dependent active occurrence lacks such an integral, trajectory generation remains exact but the event is explicitly marked as lacking an exact likelihood survival term.

## DPO semantics and stochastic eligibility

Rule keys define the DPO span:

```text
L only   -> delete
L and R  -> preserve
R only   -> create
```

For a vertex deleted by a rule, all incident host edges must also be explicitly deleted by that occurrence. A match that violates this dangling condition is structurally invalid and therefore contributes **zero stochastic channel count**, rather than being sampled and failing later.

Boundary-bound vertex deletion likewise requires an explicit boundary effect that deletes, unbinds, or rebinds every affected handle.

## Incremental matcher correctness contract

`Matcher` is the exhaustive oracle. `IncrementalMatcher` is allowed to optimize only when it can maintain the same relation exactly.

For local rules without graph conditions:

```text
GraphDelta
  -> affected typed neighborhood
  -> cached match invalidation
  -> anchored local rematching
  -> added / removed / revalidated match IDs
  -> DPO eligibility + hazard reevaluation only for touched IDs
```

PAC/NAC conditions can be changed by a remote extension that does not touch the base match, so relevant PAC/NAC edits deliberately fall back to a full match computation.

For development, enable continuous differential verification:

```python
RuntimeConfig(
    matcher_backend="incremental",
    incremental_verify=True,
)
```

After each refresh, the cached match IDs are compared against the exhaustive matcher. Divergence is a hard assertion failure.

## First-class adaptive parameters

```python
from osahr import (
    AdaptiveParameter,
    ParameterConstraint,
    ConstraintPolicy,
)

model = Model(
    graph,
    boundary,
    rules,
    parameters={"rate": 1.0},
    memory={},
    adaptive_parameters=(
        AdaptiveParameter(
            "rate",
            constraint=ParameterConstraint.POSITIVE,
            policy=ConstraintPolicy.STRICT,
        ),
    ),
)
```

A rule or scheduled adaptation that attempts to commit `rate <= 0` fails before the invalid adaptive state is accepted. Projection is available only when explicitly declared as part of model semantics.

## Safe meta-rewriting

A rule template is compiled before the run. Its expressions may read the immutable per-instance `meta` namespace:

```python
from osahr import MetaParameter, MetaValueKind, RuleTemplate

prototype = Rule(
    "prototype",
    PatternGraph(()),
    TemplateGraph(()),
    Expr("meta.rate"),
)

template = RuleTemplate(
    "birth-channel",
    prototype,
    parameters=(
        MetaParameter("rate", MetaValueKind.FLOAT, lower=0.0),
    ),
    max_instances=100,
)
```

At a deterministic simulation time, `MetaRuleEvent(INSTANTIATE, ...)` creates a typed instance. The model's active rule repertoire is part of state identity and replay provenance.

## Path likelihood

For an internal trajectory with occurrence hazards `a_k` and survival integrals `S_k`, the recorded path density conditioned on deterministic environmental/adaptation/meta events is

```text
log p(path) = sum_k log(a_k) - sum_k S_k
```

For piecewise-constant CTMC intervals, `S_k = A_k * dt_k`. For integrable time-dependent hazards, `S_k` is the declared exact total integrated activity.

```python
from osahr import path_log_likelihood

result = path_log_likelihood(runtime.event_log)
print(result.log_likelihood)
```

## Ensembles and first passage

```python
from osahr import run_ensemble

ensemble = run_ensemble(
    model,
    replicates=1000,
    root_seed=12345,
    event_count=100,
    observations={"count": lambda rt: rt.event_index},
)

print(ensemble.summary("count"))
```

Replicate seeds are deterministically derived from `(root_seed, replicate_id)`. The reference implementation executes the ensemble serially so results are independent of worker scheduling; parallel orchestration may partition replicate IDs above this API.

## Open boundaries

Boundary inputs are deterministically ordered by

```text
(simulation_time, source_namespace, source_sequence)
```

External inputs can merge/replace attributes on their bound graph vertex or operate in signal-only mode. An external event at or before a proposed stochastic transition preempts it. Discarded proposal randomness is retained in the audit record.

## Persistence and replay

```python
snapshot = runtime.snapshot()
save_checkpoint("run.osahr.gz", snapshot)
restored = Runtime.from_snapshot(model, load_checkpoint("run.osahr.gz"))
```

Snapshots preserve scheduler-specific state, including next-reaction internal thresholds/clocks and the thinning planner audit cursor.

Delta replay verifies pre- and post-state hashes event by event:

```python
replayed = Runtime.replay_deltas(model, initial_snapshot, runtime.event_log)
assert replayed.state_hash == runtime.state_hash
```

Checkpoint serialization uses Python pickle inside a hashed/versioned envelope and must only be loaded from trusted sources.

## Verification

The 0.2 suite contains structural, stochastic, replay, adaptive, incremental, meta-rewrite, and differential tests. In particular it checks:

- DPO-invalid embeddings do not steal probability mass;
- local deletion can re-enable previously DPO-invalid matches;
- next-reaction waiting times and competing-channel frequencies;
- next-reaction clock preservation across deterministic no-op preemption;
- thinning against an analytic integrated-hazard distribution;
- invalid bound detection;
- exact thinning likelihood with a declared integral;
- `peek_next_event_time()` observational semantics under thinning;
- strict adaptive rollback and explicit projection;
- dynamic rule-template instantiation and replay;
- snapshot preservation of next-reaction clocks;
- subtype-aware incremental invalidation;
- event-for-event identity between reference and incremental backends over repeated stochastic execution.

Run:

```bash
python -m pytest
```

## Locality benchmark

`benchmarks/benchmark_incremental.py` compares the reference and incremental backends on repeated single-vertex rewrites over a large match relation.

One development-container run with 1,000 vertices and 100 stochastic events produced:

```text
incremental_seconds=3.866585
reference_seconds=8.171069
speedup=2.11x
full_recomputations=1
localized_recomputations=100
```

This is an implementation smoke benchmark, **not** a portable performance guarantee. Its more important invariant is that both backends finish with the same canonical state hash.

## Exactness envelope

OSAHR 0.2 makes the following semantics explicit:

- finite concrete graph at every committed event;
- finite enabled embedding set per rule;
- injective embedding multiplicity;
- DPO rewriting only;
- serialized state-changing commits;
- direct SSA and modified-next-reaction for piecewise-constant hazards;
- thinning for continuously time-dependent hazards with declared valid finite-window bounds;
- exact likelihood only when every required survival integral is available;
- no silent match truncation, minimum stochastic timestep, rate clamping, or approximate scheduler switch.

## Deliberate non-features in 0.2

These remain future semantic extensions rather than being hidden approximations:

- automorphism-orbit stochastic counting;
- SqPO/SPO deletion-in-unknown-context;
- non-injective matches;
- delayed completion events / general semi-Markov transitions;
- synchronized multi-runtime rewrites;
- stochastic message-channel composition;
- tau leaping or other approximate acceleration;
- arbitrary runtime code generation.

See `ARCHITECTURE.md` for invariants and algorithms, `RESEARCH_NOTES.md` for the research basis and design decisions, and `benchmarks/benchmark_incremental.py` for the locality benchmark.
