# Experiment 03 Protocol: Query-Conditioned Trust

**Status:** confirmatory reanalysis of frozen Liquid-OSAHR 02B artifacts, plus a labeled exploratory value-of-information study.

**Does not overwrite 02B.** 02B remains the cited intervention-calibration record. This experiment is a versioned descendant.

## Question

Does a query-conditioned trust field

```text
T(q, I, r, h)
```

fit only on the frozen 02B 18-scenario calibration split recover confirmatory policy effects more accurately than any single global \(\alpha\)?

## Hypothesis

A cell-wise application of the 02B objective

```text
J(α; q, I, r) = MAE_Δ(α; q, I, r) + λ · NMAE_pred(α)
```

with \(\lambda = 0.1\) and conservative tie-breaking toward smaller \(\alpha\) yields a non-scalar \(T\) that improves confirmatory goal-utility effect recovery relative to the frozen global \(\alpha = 0\), without using confirmatory trajectories for selection.

Competing explanations:

1. **Null / global sufficiency.** Cell-wise \(T\) collapses to \(\alpha = 0\) and cannot beat 02B's preselected mechanistic arm.
2. **Calibration non-identifiability.** The 2 s calibration trajectories do not distinguish residual trust; any ID preference is an artifact of the predictive tie-break.
3. **Transport failure.** Cell-wise \(T\) fitted at \(h=2\) s does not travel to the confirmatory \(h=3\) s holdout, especially in uncalibrated regimes.

## Formal object

A query is an estimand, not a model property:

```text
q ∈ {goal_utility_ratio, critical_success_rate, mean_latency}
I = do(semantic) vs do(throughput)
r ∈ {id, high_mobility, high_stress, weak_channel}
h = simulation horizon
```

\(T\) returns a residual trust \(\alpha \in \{0, 0.25, 0.5, 1.0\}\) used for the **entire twin** while answering \(q\). Different estimands may require different twins. One trajectory cannot carry several \(\alpha\) values at once.

Unknown cells fall back to \(\alpha = 0\) (exact mechanistic identity in 02B). No interpolation across regimes or queries in the primary protocol.

## Frozen protocols (specified before confirmatory scoring)

### T_strict (primary)

- Fit one cell per \((q, I, r)\) present in the 02B multi-regime calibration JSON.
- That JSON records **only** \(q =\) `goal_utility_ratio`.
- Grid is the confirmatory-available set \(\{0, 0.25, 0.5, 1.0\}\) (exclude \(0.75\) so evaluation is exact arm selection, not snapping).
- Uncalibrated query or regime: \(\alpha = 0\).
- Horizon is recorded, not interpolated: calibration \(h=2\), evaluation \(h=3\) is an explicit transport test.

### T_primary_share (secondary frozen)

Same cells as `T_strict`, but an uncalibrated query inherits \(T(\text{goal_utility_ratio}, I, r)\) when that cell exists. Uncalibrated regimes still fall back to \(\alpha = 0\).

### T_intervention_only (sensitivity)

Same as `T_strict` with \(\lambda = 0\). Labeled sensitivity, not primary.

## Evaluation

No new stochastic simulation. Each confirmatory arm already committed a residual trust. \(T\) selects among those arms.

- Independent unit: physical scenario (20 total).
- Replicates averaged inside scenario before inference.
- Primary endpoint: scenario-level absolute error of the semantic-vs-throughput **goal-utility** effect relative to oracle, under `T_strict`.
- Secondary: the same for critical success and mean latency; sign agreement; paired bootstrap versus global \(\alpha = 0\) and global \(\alpha = 1\).
- OOD: `weak_channel` was not in calibration; `T` must use the pre-specified fallback.

## Exploratory layer (not confirmatory)

Leave-one-scenario-out selectors fitted on the confirmatory holdout itself estimate the value of information of query-conditioned trust **if** calibration were drawn from the same horizon and estimand support. An infeasible oracle-per-scenario selector is reported as a ceiling, not a method.

These numbers must not be described as a frozen-protocol confirmation.

## Failure criteria

- If `T_strict` uses any confirmatory row during fitting, the confirmatory claim is invalid.
- If a selected \(\alpha\) is not an executed confirmatory arm, the evaluation is invalid.
- If a paired 95% interval includes zero, the comparison is unresolved.
- No claim of real-network efficacy.

## Exactness boundary

Arm selection is exact relative to the already-committed 02B trajectories. It does not create a new stochastic process and does not make the RAN surrogate more physically realistic.
