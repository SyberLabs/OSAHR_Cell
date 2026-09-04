# Experiment 03 Report — Query-Conditioned Trust

**Status:** completed reanalysis of frozen Liquid-OSAHR 02B artifacts.
**Simulation:** none. Confirmatory scores are arm selections from already-committed trajectories.

## 1. Frozen field

Primary protocol `T_strict` applies the 02B objective per calibrated cell
on `goal_utility_ratio` only. Uncalibrated queries and regimes fall back to α=0.

| Regime | Selected α | Source | Intervention MAE (calibration) | Inadequacy |
|---|---:|---|---:|:---|
| high_mobility | 0.00 | calibrated_cell | 0.07126 | False |
| high_stress | 0.00 | calibrated_cell | 0.06850 | False |
| id | 0.50 | calibrated_cell | 0.00463 | False |
| weak_channel | 0.00 | default_mechanistic | — | fallback |

Calibration LOSO selected alphas (6 folds per calibrated regime):

```json
{
  "id": [
    0.5,
    0.5,
    0.5,
    1.0,
    0.5,
    0.5
  ],
  "high_mobility": [
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0
  ],
  "high_stress": [
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0
  ]
}
```

## 2. Confirmatory primary endpoint

Absolute semantic-vs-throughput **goal-utility** effect error versus oracle.
Independent unit: physical scenario. 50,000 scenario bootstraps.

| Selector | Macro MAE | 95% CI |
|---|---:|---|
| T_strict | 0.08161 | [0.03853, 0.13263] |
| global α=0 | 0.09301 | [0.04967, 0.14387] |
| global α=1 | 0.08225 | [0.03744, 0.13732] |

Paired difference in absolute error, T_strict minus global α=0 (negative = T better):

- macro: `-0.01140  [-0.02963, 0.00000]` — unresolved (95% CI includes 0)
- id: `-0.04561  [-0.10541, -0.00305]` — negative, 95% CI excludes 0
- high_mobility: `0.00000  [0.00000, 0.00000]` — unresolved (95% CI includes 0)
- high_stress: `0.00000  [0.00000, 0.00000]` — unresolved (95% CI includes 0)
- weak_channel: `0.00000  [0.00000, 0.00000]` — unresolved (95% CI includes 0)

Per-regime MAE under T_strict:

| Regime | Selected α (mean) | MAE | 95% CI |
|---|---:|---:|---|
| id | 0.50 | 0.05109 | [0.00543, 0.11843] |
| high_mobility | 0.00 | 0.04033 | [0.01112, 0.08913] |
| high_stress | 0.00 | 0.17914 | [0.03835, 0.36312] |
| weak_channel | 0.00 | 0.05587 | [0.00263, 0.10910] |

## 3. Secondary estimands under frozen protocols

`T_strict` cannot condition on critical success or latency because those
queries are absent from the 02B calibration JSON. `T_primary_share` reuses
the goal-utility cell when the regime was calibrated.

| Estimand | Protocol | Macro MAE | vs α=0 (paired) | Reading |
|---|---|---:|---:|---|
| goal_utility_ratio | T_strict | 0.08161 | -0.01140 [-0.02963, 0.00000] | unresolved (95% CI includes 0) |
| goal_utility_ratio | T_primary_share | 0.08161 | -0.01140 [-0.02990, 0.00000] | unresolved (95% CI includes 0) |
| critical_success_rate | T_strict | 0.12792 | 0.00000 [0.00000, 0.00000] | unresolved (95% CI includes 0) |
| critical_success_rate | T_primary_share | 0.11792 | -0.01000 [-0.03000, 0.00000] | unresolved (95% CI includes 0) |
| mean_latency | T_strict | 0.10117 | 0.00000 [0.00000, 0.00000] | unresolved (95% CI includes 0) |
| mean_latency | T_primary_share | 0.09857 | -0.00261 [-0.00822, 0.00172] | unresolved (95% CI includes 0) |

## 4. Exploratory value of information (not confirmatory)

Leave-one-scenario-out selectors fitted **on the confirmatory holdout**
estimate how much query-conditioning could help if calibration had the
same horizon and estimand support. The oracle-per-scenario selector is an
infeasible ceiling.

| Estimand | Frozen T_strict | Exploratory LOSO | Infeasible oracle-cell |
|---|---:|---:|---:|
| goal_utility_ratio | 0.08161 | 0.07426 | 0.04505 |
| critical_success_rate | 0.12792 | 0.11958 | 0.05875 |
| mean_latency | 0.10117 | 0.06068 | 0.03598 |

## 5. Interpretation

Calibrated cells: high_mobility→α=0.00, high_stress→α=0.00, id→α=0.50. Uncalibrated support (other queries, weak_channel) is α=0 by protocol. On the primary confirmatory endpoint, the paired difference versus global α=0 is -0.01140  [-0.02963, 0.00000] and is unresolved. The identifiable ID cell (α=0.5 via predictive tie-break on tied intervention MAE) is the only calibrated departure from α=0, and it improved ID confirmatory recovery. High-stress remains on the mechanistic fallback because calibration penalized residual trust there. Frozen T therefore cannot capture any later high-stress residual benefit; that is a transport/design limit, not a silent interpolation. Confirmatory high-stress MAE under T_strict is 0.17914. Exploratory LOSO on the confirmatory holdout is reported separately. It is not a frozen-protocol confirmation.

`T_intervention_only` (λ=0) selects α=0 in every calibrated cell, so it is identical to 02B's global mechanistic arm. The ID departure in `T_strict` is therefore licensed only by the frozen 02B predictive penalty on a three-way intervention-MAE tie, not by a unique counterfactual ranking at h=2 s. That is a feature of the protocol, not a hidden confirmatory peek.

An ex-post global α=0.25 would have produced a lower confirmatory goal-utility macro MAE than frozen `T_strict`. That ranking was already visible in 02B and is **not** a frozen selector. Using it here would convert Experiment 03 into the thing 02B refused to do: pick α on the holdout.

The exploratory LOSO field, fitted on confirmatory scenarios themselves, prefers α=0.5 on all five ID scenarios and α=0.25 on all five high-stress scenarios for goal utility, and prefers α=1.0 on ID and high-stress for mean latency. Same-horizon, multi-query calibration is therefore still the highest-leverage next measurement — not a larger neural trust head.

## 6. Exactness and scope

- KNOWN: 02B trajectories, hashes, and calibration JSON are unchanged.
- MEASURED: cell-wise α from the frozen calibration objective; confirmatory arm-selection errors.
- INFERRED: whether query-conditioning improves holdout policy-effect recovery under this protocol.
- ASSUMED: confirmatory `trust` column is the residual coefficient actually used in 02B.
- PROPOSED: a later same-horizon multi-query calibration, and only then a new untouched seed.

This is a synthetic scenario-generator result. It is not a real RAN field trial.

