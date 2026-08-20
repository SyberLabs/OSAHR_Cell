# OSAHR 0.2 Build and Verification Report

Build date: 2026-08-11  
Runtime semantic version: `osahr-python-0.2.0`  
Package version: `0.2.0`

## Scope implemented

The 0.2 release implements the planned sequence:

1. exact dependency-indexed incremental matching with reference fallback/oracle;
2. dynamic two-level weighted occurrence scheduling;
3. modified-next-reaction clocks for sparse piecewise-constant systems;
4. exact bounded thinning for continuously time-varying hazards;
5. first-class adaptive parameter constraints and reusable learning-state primitives;
6. exact path likelihood when survival-integral contracts are available;
7. deterministic ensembles and first-passage analysis;
8. safe finite meta-rewriting through precompiled typed rule templates.

It also corrects stochastic DPO eligibility: a dangling-invalid embedding is excluded before probability mass is aggregated.

## Automated verification

Final source-suite result:

```text
36 passed
```

The suite includes structural, stochastic, incremental, differential, replay, snapshot, adaptive, thinning, likelihood, and meta-rule tests.

Selected high-value invariants:

- reference and incremental runtimes are event-for-event identical under repeated stochastic execution;
- subtype-compatible pattern dependencies invalidate correctly;
- DPO-invalid base embeddings never enter total stochastic activity;
- modified-next-reaction competition reproduces the expected waiting-time mean and channel frequency;
- no-op deterministic preemption preserves next-reaction clocks;
- thinning for `lambda(t)=1+t` matches the analytic cumulative-hazard transform;
- invalid thinning bounds are rejected;
- thinning peeks do not mutate authoritative simulation time;
- exact analytic hazard-integral declarations populate path-likelihood survival terms;
- strict adaptive constraints reject invalid updates without committing adaptive state;
- dynamic rule instances survive snapshots/delta replay with matching state hashes.

## Locality smoke benchmark

Command:

```bash
python benchmarks/benchmark_incremental.py --vertices 1000 --events 100
```

Development-container result:

```text
vertices=1000 events=100
incremental_seconds=3.866585
reference_seconds=8.171069
speedup=2.11x
full_recomputations=1
localized_recomputations=100
final_state_hash=238cd414f3bc303318846484f75eb90acf30e2ea08d8e2ae6f7ad20a0e1a13ec
```

This is not a portable performance guarantee. The semantic benchmark assertion is that both backends produce the same final canonical state hash.

A smaller release-hardening run (`500` vertices, `50` events) likewise produced identical final state hashes and approximately `2.09x` speedup in this container.

## Wheel build

The release wheel was built with the locally installed toolchain because the environment has no outbound package access:

```text
Python     3.13.5
setuptools 82.0.1
wheel      0.46.3
```

Build command:

```bash
python -m pip wheel . --no-deps --no-build-isolation -w dist
```

## Clean installation test

The wheel was installed into a new virtual environment with `--no-deps` and successfully executed a continuously time-varying rule under the thinning scheduler with an analytic hazard-integral contract.

Observed smoke-test marker:

```text
clean_install_ok osahr-python-0.2.0
```

## Research grounding

The implementation work was informed by primary literature on:

- stochastic rewriting / CTMC semantics and pattern observables;
- localized incremental graph queries;
- random-time-change / modified-next-reaction simulation;
- exact thinning under dynamic propensities;
- DPO versus SqPO deletion semantics.

See `RESEARCH_NOTES.md` for the specific papers and how they map to implementation decisions.

## Deliberate semantic boundaries

OSAHR 0.2 does not silently emulate semantic features it has not implemented. In particular, automorphism-orbit counting, SqPO cascading deletion, delayed completion events, non-injective matches, stochastic message channels, synchronized cross-runtime rewrites, and approximate tau-leaping remain explicit future extensions.
