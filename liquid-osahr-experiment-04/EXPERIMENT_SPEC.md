# Experiment 04 Protocol — Same-Horizon Multi-Query Calibration

**Status:** confirmatory synthetic study, descendant of Experiments 02B and 03.

**Does not overwrite 02B or 03.** Those remain the cited records for the 2 s single-query calibration and the arm-selection reanalysis.

## Question

If residual trust is calibrated at the **same horizon** as evaluation, and **separately for each estimand**, does

```text
T(q, I, r, h=3)
```

recover confirmatory policy effects more accurately than any single global \(\alpha\), including the 02B mechanistic fallback \(\alpha=0\)?

## Hypothesis

The 03 ID cell was identified only by a predictive tie-break on a 2 s calibration whose trajectories barely distinguished \(\alpha\). A 3 s, multi-query calibration on a new disjoint seed will produce a non-scalar \(T\) whose confirmatory goal-utility effect MAE is lower than global \(\alpha=0\).

Competing explanations:

1. **Still unidentifiable.** Even at \(h=3\) s, cell-wise intervention MAE ties and \(T\) collapses to \(\alpha=0\).
2. **Identifiable but non-transporting.** Calibration \(T\) is non-scalar and fails on a new seed.
3. **Query-pooling is enough.** A single \(\alpha\) per regime, shared across estimands, matches query-specific \(T\).
4. **Global 02B \(\alpha=0\) remains optimal** under the frozen objective.

## Frozen constants (declared before confirmatory execution)

| Quantity | Value |
|---|---|
| Residual checkpoint | 02B `artifacts/residual_cfc.pt` (unchanged) |
| Horizon \(h\) | **3.0 s** for calibration and confirmatory |
| Grid | \(\{0, 0.25, 0.5, 1.0\}\) |
| \(\lambda\) (primary) | 0.1, using **frozen 02B validation predictive NMAE** |
| Intervention | semantic vs throughput |
| Calibration root seed | `440318` |
| Confirmatory root seed | `880419` |
| Calibration regimes | id, high_mobility, high_stress |
| Confirmatory regimes | those three plus **weak_channel** (OOD fallback test) |
| Calibration | 6 scenarios × 2 replicates |
| Confirmatory | 5 scenarios × 2 replicates |
| \(\alpha=0\) semantics | exact `mechanistic` field, not residual-at-zero arithmetic |

Predictive NMAE is **not** refit on 04 scenarios. It is the 02B validation term, frozen so intervention calibration cannot retune the predictive penalty.

The confirmatory seed is declared here and must not be analyzed until `artifacts/FROZEN.json` exists.

## Independent unit

Physical scenario. Replicates are averaged inside scenario before \(\Delta\) and before bootstrap.

## Estimands

```text
q ∈ {goal_utility_ratio, critical_success_rate, mean_latency}
```

Primary endpoint: goal-utility policy-effect MAE under `T_strict`.

Secondary: the other two estimands; sign agreement; paired bootstrap vs global \(\alpha=0\) and \(\alpha=1\); `T_intervention_only` (\(\lambda=0\)); `T_primary_share`; weak-channel fallback.

## Protocols

### T_strict (primary)

One cell per \((q, I, r)\) present in the 04 calibration table. Unknown regime or query: \(\alpha=0\). No interpolation. No snapping.

### T_intervention_only

Same cells with \(\lambda=0\).

### T_primary_share

Uncalibrated query inherits \(T(\text{goal_utility_ratio}, I, r)\) when that cell exists. Weak channel still \(\alpha=0\).

## Failure criteria

- Fitting \(T\) from any confirmatory row invalidates the confirmatory claim.
- Running confirmatory before `FROZEN.json` invalidates the freeze.
- A paired 95% CI that includes 0 is unresolved.
- No real-network efficacy claim.

## Exactness boundary

OSAHR thinning is exact relative to the declared bounded hazards. The RAN layer remains a standards-informed surrogate. New trajectories are a new stochastic sample of that declared process, not a more physical radio model.
