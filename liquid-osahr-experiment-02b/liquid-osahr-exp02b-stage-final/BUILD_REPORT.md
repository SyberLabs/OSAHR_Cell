# Liquid-OSAHR Experiment 02B — Build and Verification Report

**Release date:** 2026-08-18  
**Package:** `liquid-osahr-experiment-02b==0.2.0`

## Environment

- Python 3.13.5
- PyTorch 2.10.0+cpu
- NumPy 2.3.5
- pandas 2.2.3
- SciPy 1.17.0
- pytest 9.0.2
- setuptools 82.0.1
- wheel 0.46.3

The exact development environment is captured in `requirements-lock-environment.txt`.

## Full regression suite

From the authoritative worktree:

```text
60 passed
```

Composition:

- 24 Experiment-02B tests;
- 36 vendored OSAHR reference tests.

The original OSAHR suite was also executed independently:

```text
36 passed
```

Static compilation:

```text
python -m compileall -q liquid_osahr02b vendor/osahr scripts tests
PASS
```

## Fresh source-tree verification

A release-staging copy was created with caches/build products excluded. From that fresh copy:

```text
python -m pytest -q
60 passed

python -m pytest -q tests/osahr_reference
36 passed
```

All three shipped telemetry fixtures normalized successfully through their respective adapters (2 records each): generic srsRAN/O-RAN-style KPM JSONL, native srsRAN scheduler JSONL with an explicit 0.5 s sampling period, and 5G-LENA/ns-3-style CSV.

## Wheel build and clean-install smoke

Built without dependency resolution/network access:

```text
python -m pip wheel . --no-deps --no-build-isolation -w dist
```

Wheel:

`liquid_osahr_experiment_02b-0.2.0-py3-none-any.whl`

SHA-256:

`53814c43320de0ca55f185405384547a113fb206d75b8c6b27a685b499da0474`

The wheel contains both `liquid_osahr02b` and the vendored `osahr` runtime. It was installed with `--no-deps` into an isolated target directory. From outside the source tree:

- `liquid_osahr02b` imported from the isolated installation;
- `osahr` imported from the isolated installation;
- an exact-thinning residual smoke trajectory completed with accepted events;
- continuous incremental/reference matcher verification was enabled for that smoke run;
- srsRAN telemetry adapter import succeeded.

## Predictive model

- bounded topology-coupled graph-CfC parameters: **14,280**;
- predictive trust selected by validation hazard error: **alpha=1.0**;
- validation NMAE at alpha=1: **0.0173988**;
- validation NMAE at alpha=0: **0.0246715**.

## Frozen intervention calibration

Final calibration used:

- ID, high-mobility, and high-stress regimes;
- 6 independent physical scenarios per regime;
- 18 scenarios total;
- trust grid {0, 0.25, 0.5, 0.75, 1.0};
- intervention-effect error plus a small predictive term;
- 20,000 stratified bootstrap recalibrations.

Final selected trust: **alpha=0.0** (exact mechanistic fallback).

Stability audit:

- alpha=0 selected in **18/18** leave-one-scenario-out calibrations;
- alpha=0 selected in **96.67%** of stratified bootstrap recalibrations.

The protocol was frozen before confirmatory root seed `920218` was analyzed.

## Untouched confirmatory holdout

- rows: **400** exact hybrid trajectories;
- independent physical scenarios: **20**;
- regimes: ID, high mobility, high stress, weak channel;
- scenarios/regime: **5**;
- stochastic replicates per model/policy arm: **2**;
- fixed model/trust arms: **5**;
- policies: **2**;
- duplicate arm keys: **0**;
- accepted OSAHR events: **8,083**;
- thinning rejections: **8,865**;
- unique final augmented state hashes: **400/400**;
- scenario-level bootstrap draws: **50,000**.

The weak-channel regime was not used in intervention calibration and serves as an additional transport/OOD check.

## Factual OOD hazard audit

A separate OOD hazard corpus used root seed `332211`, 5 traces each in ID, high mobility, high stress, and weak channel. Full residual trust alpha=1 had the lowest local hazard NMAE in **all four** regimes, while the counterfactual trust that minimized goal-policy-effect error varied by regime. This verifies that downstream intervention distortion cannot be reduced to poor local hazard prediction alone.

## Exact zero-trust contract

The residual runtime contains a dedicated alpha=0 path that bypasses neural logit/sigmoid arithmetic and returns the mechanistic rate directly. A regression test requires exact array equality, not approximate equality, between zero-trust residual and mechanistic hazards.

## Exactness boundary

Exact conditional on the declared model:

- typed matching and DPO applicability;
- mechanism/residual applicability masks;
- analytic global neural event-rate bounds;
- rejection thinning under those bounds;
- deterministic seed-conditioned physical surrogate;
- pure candidate-time liquid queries;
- graph-CfC anchor/jump lifecycle;
- event sourcing, snapshot/replay, and augmented state hashes.

Not claimed exact:

- real-world RAN fidelity of the shipped physical surrogate;
- its CQI/BLER/throughput approximations;
- the synthetic oracle hazard law;
- learned residual transport to live networks;
- intervention-calibration transport beyond the declared scenario generator.

The shipped radio layer is **standards-informed, not a full NR PHY/MAC simulator**. The srsRAN and 5G-LENA adapters define a replacement boundary for future high-fidelity or measured telemetry.
