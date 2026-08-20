# Experiment 04 Architecture

## Data flow

```text
02B residual checkpoint (frozen)
        │
        ▼
04 calibration seed 440318, h=3s, 3 regimes, 3 estimands
        │
        ▼
fit T(q,I,r)  →  artifacts/FROZEN.json
        │
        ▼
04 confirmatory seed 880419, h=3s, 4 regimes
        │
        ▼
arm-selection scoring of frozen T
```

The 02B runtime remains authoritative for typed matching, DPO, thinning, and \(\alpha=0\) mechanistic identity. Experiment 03's `TrustField` remains the answering-policy object. Experiment 04 only supplies a calibration table that can actually identify query-specific cells at the evaluation horizon.

## Invariants

1. Confirmatory execution requires a freeze record whose calibration checksum matches the calibration CSV.
2. `T.select` still never returns an \(\alpha\) outside the executed grid.
3. Physical and runtime seeds depend on `(root_seed, scenario, replicate)`, not on model or policy.
4. \(T\) is not part of the OSAHR state hash.

## Why not a neural trust head

03 already showed that the missing object was **calibrated cells**, not a new \(\alpha=f_\theta(\cdot)\). This experiment tests whether those cells become identifiable when horizon and estimand support match evaluation.
