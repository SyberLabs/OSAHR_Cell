# Liquid-OSAHR Experiment 02A — Build and Verification Report

**Release date:** 2026-08-18  
**Package:** `liquid-osahr-experiment-02a==0.1.0`

## Environment

```text
Python 3.13.5
PyTorch 2.10.0+cpu
NumPy 2.3.5
pandas 2.2.3
SciPy 1.17.0
```

## Verification

Experiment 02A tests:

```text
17 passed
```

Vendored OSAHR 0.2 reference tests:

```text
36 passed
```

Bytecode compilation over package, vendored runtime, scripts and tests: **passed**.

## Clean wheel smoke

The wheel was installed with `--no-deps` into a clean target directory. `liquid_osahr02a` and `osahr` both imported from that installed target rather than the source tree. A two-second oracle hybrid run using:

- exact thinning;
- incremental matcher;
- `incremental_verify=True`;
- certified liquid hazard bounds;

completed with 15 accepted events and a valid augmented state hash.

## Counterfactual release audit

```text
rows: 360
regimes: 3
models: 5
policies: 2
independent scenarios / regime: 6
stochastic replicates / cell: 2
duplicate arm keys: 0
unique final state hashes: 360
total thinning rejections: 25372
total thinning windows crossed: 979
max accepted events / run: 134
```

All confidence intervals in the release analysis resample at the **scenario level**, after averaging the stochastic replicates within each scenario/model/policy cell.

## Bound semantics

Neural base hazards use

\[
\lambda=\epsilon+(B-\epsilon)\sigma(z),
\]

so `B` is a global analytical upper bound independent of observed training data. The runtime asserts actual occurrence hazard `<= bound` before thinning.

## Release caveat

`EXACT` refers only to stochastic execution conditional on the declared hybrid model. It does **not** mean the synthetic teacher is a calibrated representation of a physical 5G/6G radio network.
