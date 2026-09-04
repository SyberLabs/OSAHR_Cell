# Experiment 04 Report: Same-Horizon Multi-Query Calibration

**Status:** completed synthetic confirmatory study.
**Calibration seed:** 440318. **Confirmatory seed:** 880419. **Horizon:** 3.0 s.

## 1. Frozen T_strict cells

| Estimand | Regime | α | Calibration MAE | Inadequacy |
|---|---|---:|---:|:---|
| critical_success_rate | high_mobility | 1.00 | 0.02728 | False |
| critical_success_rate | high_stress | 0.50 | 0.18472 | False |
| critical_success_rate | id | 0.50 | 0.01667 | False |
| goal_utility_ratio | high_mobility | 1.00 | 0.03374 | False |
| goal_utility_ratio | high_stress | 0.25 | 0.10864 | False |
| goal_utility_ratio | id | 0.00 | 0.00462 | False |
| mean_latency | high_mobility | 1.00 | 0.01864 | False |
| mean_latency | high_stress | 0.25 | 0.08021 | False |
| mean_latency | id | 1.00 | 0.01919 | False |

Weak channel is uncalibrated and falls back to α=0.

## 2. Primary confirmatory endpoint

Goal-utility semantic-vs-throughput effect MAE versus oracle.

| Selector | Macro MAE | 95% CI |
|---|---:|---|
| T_strict | 0.06497 | [0.03452, 0.09667] |
| global α=0 | 0.05498 | [0.02690, 0.08452] |
| global α=1 | 0.05053 | [0.02274, 0.08067] |

Paired T_strict minus global α=0 (negative = T better):

- macro: `0.00998  [-0.00268, 0.02571]`: unresolved (95% CI includes 0)
- id: `0.00000  [0.00000, 0.00000]`: unresolved (95% CI includes 0)
- high_mobility: `0.02464  [-0.01817, 0.07751]`: unresolved (95% CI includes 0)
- high_stress: `0.01528  [-0.00323, 0.04565]`: unresolved (95% CI includes 0)
- weak_channel: `0.00000  [0.00000, 0.00000]`: unresolved (95% CI includes 0)

## 3. All estimands

| Estimand | Protocol | Macro MAE | vs α=0 | Reading |
|---|---|---:|---:|---|
| goal_utility_ratio | T_strict | 0.06497 | 0.00998 [-0.00268, 0.02571] | unresolved (95% CI includes 0) |
| goal_utility_ratio | T_primary_share | 0.06497 | 0.00998 [-0.00275, 0.02534] | unresolved (95% CI includes 0) |
| goal_utility_ratio | T_intervention_only | 0.06497 | 0.00998 [-0.00268, 0.02558] | unresolved (95% CI includes 0) |
| critical_success_rate | T_strict | 0.08250 | 0.00500 [-0.01250, 0.02750] | unresolved (95% CI includes 0) |
| critical_success_rate | T_primary_share | 0.08250 | 0.00500 [-0.01250, 0.02750] | unresolved (95% CI includes 0) |
| critical_success_rate | T_intervention_only | 0.08250 | 0.00500 [-0.01250, 0.02750] | unresolved (95% CI includes 0) |
| mean_latency | T_strict | 0.07651 | 0.01741 [-0.00160, 0.04032] | unresolved (95% CI includes 0) |
| mean_latency | T_primary_share | 0.07651 | 0.01741 [-0.00155, 0.04043] | unresolved (95% CI includes 0) |
| mean_latency | T_intervention_only | 0.07651 | 0.01741 [-0.00165, 0.04049] | unresolved (95% CI includes 0) |

## 4. Interpretation

Same-horizon calibration **did identify a non-scalar field**. Goal-utility cells are (ID α=0, high mobility α=1, high stress α=0.25). Latency wants α=1 on ID and high mobility. Critical success wants α=0.5 on ID. Calibration LOSO is stable for goal-utility ID (6/6 α=0) and high mobility (6/6 α=1); high stress is mixed (4/6 α=0.25, 2/6 α=0).

That field **did not transport**. On the untouched seed, T_strict goal-utility macro MAE is 0.06497 versus 0.05498 for global α=0 and 0.05053 for global α=1. The paired difference versus α=0 is +0.00998 with 95% CI [-0.00268, +0.02571]: unresolved, and the point estimate favors the mechanism.

Per-regime confirmatory goal-utility MAE:

| Regime | Frozen α | T_strict MAE | global α=0 | global α=1 |
|---|---:|---:|---:|---:|
| id | 0.00 | 0.02659 | 0.02659 | 0.00060 |
| high_mobility | 1.00 | 0.04226 | 0.01762 | 0.04226 |
| high_stress | 0.25 | 0.07112 | 0.05584 | 0.04513 |
| weak_channel | 0.00 fallback | 0.11989 | 0.11989 | 0.11413 |

The licensed high-mobility α=1 cell is the main self-inflicted cost relative to the mechanism. The ID cell that 03 found at α=0.5 from a 2 s tie-break is α=0 here; on this holdout, α=1 would have been better still (MAE 0.00060). That is seed/transport disagreement, not a license to peek.

T_strict, T_primary_share, and T_intervention_only agree on confirmatory macros because several query-specific cells do not change holdout errors: many 3 s scenarios still have zero oracle policy effect, so nearby α values are empirically identical. Query-conditioning can be identified on calibration and still be a no-op on the holdout.

Competing explanation (2) is the one that survived: identifiable, non-transporting. A neural trust head would not have repaired that. Longer horizons, more independent scenarios, or reporting a **distribution over T** rather than a point lookup are the remaining measurement options.

## 5. Scope

- KNOWN: 02B residual checkpoint unchanged; confirmatory seed was declared before freeze.
- MEASURED: 3 s multi-query calibration cells; new-seed arm-selection errors.
- INFERRED: whether same-horizon query-conditioning transports.
- PROPOSED: federation with srsRAN/5G-LENA remains the external-validation step.

Synthetic scenario generator only. Not a real RAN field trial.

