# Liquid-OSAHR Experiment 01: Build and Verification Report

**Date:** 2026-08-17

## Environment

- Python 3.13.5
- PyTorch 2.10.0 CPU
- NumPy 2.3.5
- SciPy 1.17.0
- pandas 2.2.3
- dataset seed: 20260817
- OSAHR bridge root seed: 80219

Exact environment versions are recorded in `requirements-lock-environment.txt`.

## Tests

Liquid-OSAHR project suite:

```text
13 passed
```

Original OSAHR 0.2 suite run against the vendored runtime:

```text
36 passed
```

Static compilation:

```text
python -m compileall liquid_osahr scripts tests
PASS
```

## Statistical/reproducibility audits

- 240 unique OSAHR bridge arms;
- 6 independent telemetry scenarios per bridge regime;
- 2 stochastic replicates per scenario/arm;
- common model-independent root seeds verified across model/policy arms;
- scenario-level bootstrap: 20,000 replicates;
- trace-level paired identification bootstrap: 30,000 replicates;
- 3 training seeds each for CfC and parameter-matched GRU sensitivity;
- paired-sparse event histories and exposure exactly preserved;
- causal lagged event features tested before and after sparsification.

## Hazard import audit

- intensity values audited: 110,970;
- values > 30: 0;
- values > 20: 0.

Therefore the downstream simulator's defensive intensity cap does not determine any reported result.

## Exactness boundary

Exact relative to the declared model:

- teacher event sampling inside 50 ms process segments;
- teacher integrated exposure accounting;
- interval-wise marked point-process likelihood;
- deterministic neural hazard schedules at observation times;
- OSAHR matching, DPO rewriting, and next-reaction execution between hazard updates;
- seed/state reproducibility.

Approximate/model-dependent:

- synthetic wireless teacher as a surrogate for real RAN physics;
- neural approximation to hidden teacher state;
- holding neural hazards constant between telemetry observations;
- task utility and semantic routing model;
- generalization to real 6G systems.

## Release hardening

- Built `liquid_osahr_experiment_01-0.1.0-py3-none-any.whl` with local build tooling.
- Verified wheel contents include both `liquid_osahr` and vendored `osahr` packages.
- Installed the wheel into a clean target directory and ran a learned-runtime bridge smoke trajectory using only the installed package paths; import and execution passed.
- Extracted the final source archive into a fresh directory and reran the project suite there: **14 passed**.
