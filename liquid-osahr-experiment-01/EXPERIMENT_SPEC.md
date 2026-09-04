# Liquid-OSAHR Experiment 01: Preregistered-Style Specification

## 1. Research question

Can a liquid continuous-time recurrent model identify irregularly observed stochastic link-event intensities well enough to serve as a useful hazard layer for an exact OSAHR structural network twin?

The experiment deliberately separates three claims:

1. **Identification:** Does a model fit the marked temporal point process better than explicit-time recurrent/memoryless baselines?
2. **Robustness:** Does that advantage persist under sparse telemetry or changed physical regimes?
3. **Counterfactual fidelity:** When learned hazard schedules drive OSAHR, do resulting distributions and policy effects resemble a twin driven by teacher/oracle hazards?

Success on (1) does not imply success on (3).

## 2. Synthetic teacher

The teacher contains hidden continuous physical state:

- shadowing state;
- normalized load;
- mobility/speed;
- obstruction;
- binary blocked/unblocked state.

Continuous latent variables follow exact-discretized OU-like dynamics on a 50 ms process grid. Within each grid segment, event intensities are held constant until a jump. `down`/`up` events mutate the blocked state and cause immediate within-segment rate recomputation; service events do not mutate hidden state.

The three event marks are:

```text
service
link down
link up
```

The service log-intensity depends on SINR, load, obstruction and blockage. Down intensity depends on obstruction, mobility, load and poor SINR. Recovery intensity is available only while blocked.

Two link profiles are generated:

- **fast:** higher service potential, lower robustness;
- **robust:** lower service potential, better down/recovery characteristics.

No model receives the hidden obstruction or blocked flag directly. It receives noisy/derived telemetry and lagged observable event summaries.

## 3. Observation process

Telemetry is irregular. Default observation gaps are lognormal and clipped, with nominal mean scale ~0.42 s. The sparse test regime increases the mean telemetry interval by 2.15x and allows larger gaps.

Observed features:

1. SINR (dB)
2. RSRP (dBm)
3. CQI proxy
4. BLER proxy
5. load
6. speed
7. service-class indicator
8. robustness-class indicator
9. previous-interval service event rate
10. previous-interval down count
11. previous-interval up count

The lagged event features are causal: observation `i` contains only completed interval `i-1` event summaries.

## 4. Dataset

Deterministic split seed: `20260817`.

```text
72 training traces     regime=train
16 validation traces   regime=id
20 test traces/regime  id
20 test traces/regime  high_mobility
20 test traces/regime  high_congestion
20 test traces/regime  sparse
```

Every split alternates fast and robust profiles.

The test regimes are generated from independent random streams rather than transformations of training samples.

## 5. Neural intensity models

All neural models output three positive intensities through `softplus(head) + 1e-5`. The width-32 comparison controls hidden-state width and information, **not parameter count**. A separate width-54 GRU (`gru_param_matched`) has 11,181 parameters versus CfC's 11,235 and is used as a parameter-budget sensitivity check.

### CfC

The primary liquid model implements the default gated interpolation form of the official Neural Circuit Policies CfC cell:

```text
z = backbone([x, h])
f1 = tanh(W1 z)
f2 = tanh(W2 z)
g  = sigmoid(Wa z * delta_t + Wb z)
h' = f1 * (1-g) + f2 * g
```

### GRU-dt / LSTM-dt

Both baselines receive `[x, log1p(delta_t)]`, preventing an unfair comparison in which only CfC knows elapsed time.

### MLP-dt

A memoryless control that receives the current telemetry plus elapsed time.

### Constant

Analytic homogeneous-Poisson intensity estimate:

```text
lambda_k = total_events_k / total_exposure
```

### Dense LTC (secondary)

A dense semi-implicit solver model implementing the conductance-style LTC update. The release caps it at hidden width 12, 24 training traces and 10 epochs because full dense ODE unfolding dominated CPU training cost. It is not used as evidence in an equal-capacity leaderboard.

## 6. Training objective

For each observation interval and event mark:

\[
\mathcal{L}_{ik}=\lambda_{ik}\Delta_i-n_{ik}\log\lambda_{ik}.
\]

The release reports NLL per interval and per event.

This is the exact likelihood under the experiment's declared interval-wise constant conditional-intensity model, up to constants independent of the learned parameters.

## 7. Identification evaluation

Metrics:

- NLL / observation interval;
- NLL / observed event;
- MAE/RMSE against exact teacher interval-average intensity;
- Spearman correlation against teacher intensity;
- predicted/observed total event-count ratio;
- per-mark count ratios;
- time-rescaling KS statistics and p-values.

The time-rescaling calculation exactly integrates the predicted piecewise-constant intensity between teacher event times.

No single metric is considered sufficient. In particular, a low NLL with poor time-rescaling calibration is not treated as a fully adequate stochastic model.

## 8. OSAHR bridge

The network twin is a typed directed hypergraph with:

Vertices:

```text
UE
GNB
EdgeNode
Task
```

Hyperedges:

```text
Association(UE -> GNB)
Neighbor(GNB -> GNB)
Path(GNB -> EdgeNode)
Queued(UE -> Task)
Transit(UE -> {Task,GNB,EdgeNode})
```

Rewrite rules implement task arrival, stochastic routing, service completion, edge failure/recovery, rerouting and handover.

At each irregular telemetry timestamp, an external OSAHR boundary event atomically updates `service_rate`, `down_hazard`, and `up_hazard` on each EdgeNode. Between those timestamps OSAHR uses its exact next-reaction scheduler.

The bridge therefore has a precise semantics:

```text
exogenous neural intensity schedule
          +
exact conditional CTMC graph-rewrite process between schedule changes
```

This is an **open-loop shadow-twin** design. The neural hidden state does not yet consume events generated by the counterfactual OSAHR trajectory. Closed-loop liquid/graph co-evolution is reserved for Experiment 02.

## 9. Control policies

Two routing policies are compared with identical structural rules:

- `throughput`: values service rate/link quality and penalizes load/energy;
- `semantic`: adds task utility/deadline × reliability × fidelity to route-choice score.

Policy changes only a route occurrence hazard; it does not change graph-rewrite legality.

## 10. Common random numbers

All hazard-model and policy arms for a given `(regime, scenario, stochastic replicate)` use the same OSAHR root seed:

```text
seed = derive_seed(root_seed, "liquid6g:{regime}:{scenario}:{replicate}")
```

The model/policy names are intentionally excluded.

This coupling reduces variance in comparisons. It cannot keep paths synchronized after models/policies induce different event choices, so it is not a claim of pathwise identity.

## 11. Independent experimental units

A scenario is a paired `(fast_trace, robust_trace)` draw. Multiple OSAHR stochastic replicates within a scenario share the same telemetry traces and therefore are **not independent experimental units**.

Release inference clusters/bootstraps at the scenario level, averaging stochastic replicates inside each scenario before resampling scenarios.

## 12. Exactness boundary

The following is exact relative to the declared model:

- teacher jump sampling inside each 50 ms process segment;
- interval exposure integration used to define teacher-average intensity;
- piecewise-constant point-process likelihood;
- OSAHR graph matching/rewrite semantics;
- OSAHR stochastic execution between external hazard updates;
- deterministic replay from seeds/state.

The following is approximate/model-dependent:

- telemetry as a surrogate for actual 6G measurements;
- neural approximation of the teacher's hidden process;
- treating neural intensity as constant between telemetry observations;
- the synthetic task/routing utility model;
- extrapolation to real RAN/MEC environments.

No empirical result in Experiment 01 should be interpreted as measured 6G network performance.
