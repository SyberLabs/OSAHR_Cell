# Experiment 02A Specification

## Primary question

Does closing the graph↔liquid feedback loop improve recovery of the **oracle counterfactual policy effect** compared with open/no-jump neural alternatives?

## Secondary questions

1. Can learned topology-coupled CfC hazards be executed under globally certified exact thinning bounds?
2. Does dynamic topology materially alter the continuous neural field?
3. Does event-jump feedback help beyond topology feedback alone?
4. How does CfC compare with a near-parameter-matched graph GRU?
5. Do conclusions change under high mobility or high stress?

## Hypotheses

- H1: all neural hazard values remain within declared analytic bounds.
- H2: graph rewrites causally alter subsequent neural continuous evolution.
- H3: `cfc_closed` has lower oracle policy-effect error than `cfc_openloop`.
- H4: learned jump feedback lowers policy-effect error versus `cfc_nojump`.
- H5: closed-loop CfC is not assumed a priori to dominate the matched GRU.

H3/H4 are intentionally falsifiable and are **not supported uniformly** by the final study.

## Data

Synthetic oracle trajectories are generated from the analytic hybrid teacher under in-distribution scenario draws. Release identification data currently contain:

```text
train: 20 traces / 1572 frames
val:    5 traces / 365 frames
test:   7 traces / 587 frames
```

Separate high-mobility and high-stress traces are generated for OOD identification evaluation.

## Models

- CfC closed loop: 13,952 trainable parameters.
- Graph GRU closed loop: 14,166 trainable parameters.
- CfC no-jump: 13,952 trainable parameters.

## Counterfactual release design

```text
regimes:      3
scenarios:    6 per regime
models:       5
policies:     2
replicates:   2
horizon:      10 simulation seconds
rows:         360
```

The scenario is the independent unit. Replicates are averaged before resampling.

## Metrics

Primary:

\[
MAE_{effect}=\frac1S\sum_s|\hat\Delta_s-\Delta_s^{oracle}|.
\]

Secondary:

- goal utility level MAE;
- critical-task success effect error;
- mean-latency effect error;
- sign agreement with oracle intervention effect;
- event/outage/handover/reroute distribution error;
- hazard identification normalized MAE and log RMSE;
- thinning rejection statistics;
- deterministic replay/state-hash checks.

## Bootstrap

All release confidence intervals use 50,000 bootstrap resamples over **scenarios**. Stochastic replicates from the same scenario are never treated as independent units.
