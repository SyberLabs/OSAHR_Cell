# Liquid-OSAHR Experiment 01: Audited Experiment Report

## Executive result

Liquid-OSAHR Experiment 01 successfully implements and tests a hybrid architecture in which an irregular-time recurrent model identifies marked event intensities and OSAHR consumes those intensities as an exact piecewise-constant stochastic law for typed graph rewriting.

The primary empirical result is **conditional rather than universal**:

1. **CfC is consistently strongest on in-distribution and pure observation-sparsity likelihood.** Its advantage survives an approximately parameter-matched GRU check and three training seeds.
2. **GRU is stronger under larger physical distribution shifts** (high mobility and high congestion). The liquid inductive bias did not provide universal OOD superiority.
3. **Better point-process likelihood does not guarantee better counterfactual policy fidelity.** Downstream OSAHR trajectories amplify small hazard differences through event-order changes. The learned twin must therefore be evaluated on decision-sensitive structural outcomes, not only NLL.
4. In the generated sparse-regime bridge, CfC has the best learned-model **policy-effect error** while the parameter-matched GRU has marginally lower **goal-utility MAE**. No learned model dominates all fidelity dimensions.

These findings support Liquid-OSAHR as a technically coherent research route while rejecting the stronger claim that liquid models are automatically superior stochastic digital twins.

---

## 1. Research motivation

Liquid Time-Constant (LTC) networks model continuous-time recurrent state with input/state-dependent time constants. CfC networks approximate liquid dynamics with an explicit time-dependent recurrent operator that avoids a general ODE solve at every update. Those properties make them plausible state models for irregular telemetry and event-driven systems.

OSAHR solves a complementary problem: it represents discrete stochastic changes to typed relational structure. Its event law is not a fixed label vocabulary; legal transition channels are generated from graph-rule matches in the current state.

Experiment 01 tests the first conservative integration:

```text
irregular telemetry
       ↓
liquid / recurrent conditional-intensity estimator
       ↓
piecewise-constant marked hazard schedule
       ↓
OSAHR typed stochastic graph-rewrite twin
       ↓
structural outcomes + counterfactual policy metrics
```

The neural model learns **when physical/link events are likely**. OSAHR remains authoritative about **which structural transformations are legal and what they do**.

---

## 2. Exactness boundary

This report uses “exact” only in a conditional, implementation-specific sense.

### Exact relative to the declared model

- jump sampling inside each 50 ms teacher process segment;
- teacher intensity-exposure accumulation;
- marked piecewise-constant point-process likelihood;
- OSAHR DPO-style structural applicability and atomic rewrites;
- next-reaction stochastic execution between deterministic telemetry updates;
- deterministic seed/state replay;
- paired common-random-number root-seed construction.

### Not exact / not claimed

- the synthetic teacher is not a calibrated RF or 3GPP channel model;
- telemetry does not represent measured operator data;
- learned intensities approximate hidden teacher dynamics;
- neural intensities are frozen between telemetry observations;
- control/task utility is a synthetic mechanism;
- no result is a measured 6G throughput or reliability claim.

A full Liquid-OSAHR PDMP with continuously evolving neural state inside the graph process remains a later experiment.

---

## 3. Synthetic wireless teacher

### 3.1 Hidden state

Each link contains continuously evolving hidden state:

- slow shadowing;
- load;
- mobility speed;
- obstruction;
- blocked/unblocked link state.

The continuous variables use exact-discretized OU-style transitions on a `0.05 s` process grid. Within a process segment, rates remain fixed until a discrete link-state event occurs. A `down` or `up` event immediately changes link state and therefore recomputes hazards for the remaining portion of the segment.

### 3.2 Marks

Three marks are generated:

```text
service opportunity
link down
link up
```

Service intensity increases with favorable SINR and decreases under load, obstruction, and blockage. Down intensity increases with obstruction, mobility and load. Recovery intensity exists only while the link is blocked.

### 3.3 Teacher validation

The sampler was audited by comparing total observed event counts with total integrated teacher hazard. On the 72-trace training split:

| Mark | Observed | Integrated teacher hazard | Observed / expected |
|---|---:|---:|---:|
| service | 5,137 | 5,166.75 | 0.9942 |
| down | 349 | 356.63 | 0.9786 |
| up | 343 | 351.57 | 0.9756 |

Finite held-out splits fluctuate more because down/up counts are smaller, but aggregate ratios remain compatible with the declared stochastic mechanism. A structural test additionally verifies that link-down and link-up events respect the binary blocked-state transition law.

Raw validation is in `artifacts/results/teacher_validation.csv`.

---

## 4. Irregular observation model

Telemetry observations are drawn on an irregular grid. Models receive 11 features:

1. SINR
2. RSRP
3. CQI proxy
4. BLER proxy
5. load
6. speed
7. service-class indicator
8. robustness-class indicator
9. previous-interval service-event rate
10. previous-interval down count
11. previous-interval up count

A dedicated leakage test verifies that features 9–11 contain **only interval `i-1` information**, never the current/future training labels.

Two sparsity tests are intentionally distinguished:

- `sparse`: an independently generated sparse-observation regime. Because the original generator's observation and physical randomness share a stream, this is a compound regime shift rather than a pure sampling intervention.
- `paired_sparse`: each ID physical/event trajectory is held fixed and its telemetry observations are thinned; event counts and integrated intensities are exactly merged and lagged features are recomputed. This isolates observation sparsity.

The second control was added specifically to remove an identified experimental confound.

---

## 5. Dataset and split

Deterministic dataset seed: `20260817`.

| Split | Traces |
|---|---:|
| train | 72 |
| validation | 16 |
| ID test | 20 |
| high mobility | 20 |
| high congestion | 20 |
| independently generated sparse | 20 |
| paired sparse view | 20 |

Fast and robust link profiles alternate throughout every generated split.

---

## 6. Models

### 6.1 CfC

Primary liquid model. Width 32, 11,235 trainable parameters. The recurrent update uses the gated CfC form with elapsed time explicitly modulating the interpolation gate.

### 6.2 Equal-hidden-width controls

- GRU-dt, width 32, 4,515 parameters
- LSTM-dt, width 32, 5,987 parameters
- MLP-dt, width 32, 1,571 parameters

The GRU/LSTM/MLP baselines receive `log1p(delta_t)` explicitly. CfC therefore cannot win merely because it sees observation timing while baselines do not.

### 6.3 Parameter-budget sensitivity

`gru_param_matched` uses hidden width 54 and 11,181 trainable parameters, versus CfC's 11,235.

This check is critical: the width-32 comparison is **not** a parameter-matched comparison.

### 6.4 Dense LTC secondary baseline

A self-contained dense semi-implicit LTC cell is included, but its release configuration is capped at:

- hidden width 12;
- 24 training traces;
- 10 epochs.

It is therefore **not** used as an equal-capacity model comparison. Full dense LTC unfolding was much more expensive on the release CPU path and was deliberately prevented from consuming an unbounded experimental budget.

### 6.5 Constant baseline

Homogeneous marked-Poisson maximum-likelihood rate:

\[
\hat\lambda_k = N_k / T.
\]

---

## 7. Training as a marked temporal point process

For observation interval `i`, mark `k`, exposure `Delta_i`, observed count `n_ik` and model intensity `lambda_ik`, the loss is

\[
\mathcal L_{ik}=\lambda_{ik}\Delta_i-n_{ik}\log\lambda_{ik}.
\]

The complete loss sums over intervals and marks.

Because the predicted rate is declared constant inside each observation interval, the compensator term is analytic. This is not “next-event classification”; the network learns an explicit stochastic intensity law.

Optimization uses AdamW, gradient clipping, validation early stopping, deterministic seeds, and CPU execution.

---

## 8. Identification results

### 8.1 Audited single-checkpoint NLL per observation interval

Lower is better.

| Model | ID | Paired sparse | Sparse regime | High mobility | High congestion |
|---|---:|---:|---:|---:|---:|
| **CfC** | **0.4717** | **1.1920** | **1.0443** | 0.8053 | 0.7117 |
| GRU-dt | 0.4776 | 1.2037 | 1.0549 | 0.7526 | 0.7007 |
| GRU parameter-matched | 0.4782 | 1.2029 | 1.0611 | **0.7490** | **0.6972** |
| LSTM-dt | 0.4849 | 1.2105 | 1.0657 | 0.7640 | 0.7071 |
| MLP-dt | 0.5145 | 1.2061 | 1.0555 | 0.7831 | 0.7420 |
| Constant | 0.6393 | 1.4129 | 1.2848 | 1.0161 | 1.0103 |
| LTC resource-capped | 0.8890 | 1.9624 | 1.8873 | 1.0002 | 1.0137 |

### Interpretation

CfC is strongest where the experiment specifically motivates liquid recurrence:

- same-family in-distribution dynamics;
- fewer irregular observations of the **same physical trajectory**;
- independently generated sparse telemetry.

The parameter-matched GRU is stronger when the physical dynamics themselves shift substantially.

This rejects the simplistic hypothesis “liquid is always more robust.” The evidence supports a narrower statement: the CfC temporal inductive bias is useful for irregular/sparse sampling here, while recurrent gating with enough capacity adapts better to some untrained physical regimes.

---

## 9. Three-seed parameter-budget sensitivity

To reduce dependence on one initialization, CfC and the parameter-matched GRU were trained/evaluated across three deterministic training seeds.

### Mean NLL across seeds

| Model | ID | Paired sparse | High mobility | High congestion |
|---|---:|---:|---:|---:|
| **CfC** | **0.4694** | **1.1942** | 0.7781 | 0.7057 |
| GRU parameter-matched | 0.4781 | 1.2028 | **0.7479** | **0.6982** |

CfC's standard deviation is only ~0.0023 on ID and ~0.0019 on paired sparse. The mobility result is more seed-sensitive (`std ≈ 0.0236`). The qualitative split therefore survives initialization:

```text
ID / pure sparse-observation shift → CfC advantage
strong physical regime shift       → parameter-matched GRU advantage
```

Raw seed-level values are stored in `training_seed_sensitivity.csv`.

---

## 10. Calibration diagnostics

NLL alone was not accepted as sufficient evidence.

The release also computes:

- rate MAE/RMSE;
- Spearman rank correlation with exact interval-average teacher intensities;
- expected/observed event count ratios;
- mark-specific count ratios;
- time-rescaling KS tests.

For the audited ID CfC checkpoint:

- rate RMSE: `0.4427`;
- rate Spearman: `0.8995`;
- total predicted/observed count ratio: `0.9831`.

But time-rescaling diagnostics are not uniformly perfect, particularly for less frequent link-state marks and sparse observation. This is an important negative result: **good aggregate likelihood does not mean the learned point process is fully calibrated at every event type/time scale**.

---

## 11. Compute characteristics

CPU inference benchmark over 20 ID traces / 1,790 telemetry intervals:

| Model | µs / interval |
|---|---:|
| MLP-dt | 1.17 |
| GRU-dt | 47.56 |
| LSTM-dt | 48.37 |
| GRU parameter-matched | 48.81 |
| CfC | 76.33 |
| LTC resource-capped | 302.69 |

These numbers are environment-specific and not portable performance claims.

They do show the design tradeoff in this implementation: CfC is ~4× faster than the much smaller solver-based LTC baseline, but our CfC backbone makes it slower than the PyTorch GRU/LSTM cells. The reason to use CfC here is therefore **continuous-time inductive structure**, not a claim that this particular implementation is the fastest recurrent model.

---

## 12. OSAHR 6G shadow twin

### Typed graph

Vertices:

```text
UE
GNB
EdgeNode
Task
```

Relations:

```text
Association(UE -> GNB)
Neighbor(GNB -> GNB)
Path(GNB -> EdgeNode)
Queued(UE -> Task)
Transit(UE -> {Task, GNB, EdgeNode})
```

The higher-order `Transit` hyperedge binds task identity, source UE, access context and compute destination in one typed relation.

### Rewrite process

Rules implement:

- critical/background task arrival;
- throughput- or semantic-weighted routing;
- stochastic service completion;
- edge failure;
- edge recovery;
- rerouting;
- handover.

Learned hazards update `EdgeNode.service_rate`, `down_hazard` and `up_hazard` through deterministic external events at telemetry timestamps.

OSAHR runs its exact next-reaction scheduler between those updates.

---

## 13. Downstream experimental design

The main bridge contains:

- 6 independent fast/robust telemetry-pair scenarios per regime;
- 2 nested stochastic OSAHR replicates per scenario;
- oracle, CfC, GRU-dt, parameter-matched GRU, constant hazard models;
- throughput and semantic routing policies.

For ID + generated-sparse regimes this yields:

\[
6\times2\times5\times2\times2 = 240
\]

exact OSAHR trajectories.

Replicates sharing a telemetry scenario are **not** treated as independent samples. They are averaged within scenario before confidence intervals or policy-effect comparisons. Scenario-level bootstrap is used for uncertainty.

Common random numbers use a root seed determined only by `(regime, scenario, replicate)`, not model/policy name.

One CfC learned-hazard trajectory continuously verifies OSAHR's incremental matcher against its exhaustive reference matcher.

---

## 14. Main OSAHR fidelity results

### ID regime: goal-utility MAE versus oracle

| Twin | MAE |
|---|---:|
| **GRU-dt** | **0.0462** |
| parameter-matched GRU | 0.0588 |
| CfC | 0.0643 |
| constant | 0.1061 |

### Generated sparse regime: goal-utility MAE versus oracle

| Twin | MAE |
|---|---:|
| **parameter-matched GRU** | **0.0716** |
| CfC | 0.0735 |
| GRU-dt | 0.0802 |
| constant | 0.0978 |

### Generated sparse regime: policy-effect MAE versus oracle

The policy effect is

\[
\Delta U = U_{semantic}-U_{throughput}.
\]

| Twin | Policy-effect MAE | Sign agreement across scenarios |
|---|---:|---:|
| **CfC** | **0.0241** | 0.833 |
| parameter-matched GRU | 0.0433 | 0.500 |
| constant | 0.0451 | 0.667 |
| GRU-dt | 0.0472 | 1.000 |

The oracle's mean semantic advantage in this generated sparse regime is `+0.0243`, with scenario-cluster bootstrap interval approximately `[+0.0134, +0.0345]`.

However:

- CfC estimates a smaller mean effect (`+0.0130`) and its interval crosses zero;
- width-32 GRU exaggerates the effect (`+0.0559`);
- parameter-matched GRU reverses the mean sign (`-0.0065`).

Therefore **none of the learned twins should yet be treated as decision-equivalent to the oracle**.

This is one of the experiment's strongest findings.

---

## 15. Why identification NLL and decision fidelity diverge

A stochastic structural simulator is highly sensitive to event ordering.

A modest difference in

\[
\lambda_{down}(t)
\]

can cause an outage to occur before rather than after a route decision. That changes the graph, which changes the match set, which changes all future transition channels.

Thus neural hazard error is propagated through:

\[
\delta\lambda
\rightarrow
\delta t_{event}
\rightarrow
\Delta G
\rightarrow
\Delta M_{rules}
\rightarrow
\text{different future law}.
\]

Consequently:

> **A digital twin intended for policy evaluation must be trained/evaluated on decision-sensitive trajectory distributions, not only one-step prediction or held-out NLL.**

This provides a concrete research direction for Liquid-OSAHR Experiment 02: decision-aware stochastic system identification.

---

## 16. Verification

Project test coverage includes:

- deterministic teacher generation;
- teacher exposure/event accounting;
- legal down/up state sequence;
- no future-label leakage in lagged features;
- exact paired-sparse exposure preservation;
- CfC elapsed-time sensitivity;
- positive neural hazards;
- analytic point-process NLL check;
- deterministic OSAHR bridge replay;
- model/policy-independent common random-number seed contract;
- cross-regime seed-context coupling for paired-sparse controls.

The original OSAHR 0.2 suite was also rerun against the vendored runtime:

```text
36 passed
```

The Liquid-OSAHR project suite passes separately.

---

## 17. Limitations

### Synthetic physical law

The teacher is purpose-built for controlled inference. It is not ns-3, srsRAN, ray tracing, 3GPP channel modeling, or live telemetry.

### Oracle non-deployability

`true_avg_rates` use the exact integrated teacher intensity over the ensuing observation interval. They are a ground-truth benchmark, not a causal estimator available to a live network controller.

### Piecewise-constant neural hazards

The learned model updates at telemetry timestamps. It is continuous-time-aware internally, but Experiment 01 does not claim that its output intensity varies continuously inside the interval.

### Open-loop neural bridge

Neural hidden state is computed from the original exogenous telemetry trace. Counterfactual graph events do not feed back into the neural state. This is deliberate shadow-twin semantics, not yet a fully coupled neural PDMP.

### Model-selection uncertainty

The principal bridge uses one selected trained checkpoint per architecture. Three-seed identification sensitivity was performed for CfC and the parameter-matched GRU, but the 240-run bridge was not repeated over all training seeds.

### Small number of independent bridge scenarios

The main bridge has six independent telemetry scenarios per regime. Bootstrap intervals reflect that fact; stochastic replicates are nested rather than counted as independent evidence.

---

## 18. Optimal implementation route from here

### Route A: calibrated 6G hazard identification

Replace the synthetic teacher with ns-3/srsRAN or recorded RAN/MEC telemetry and learn intensities such as:

\[
\lambda_{service},\lambda_{handover},\lambda_{blockage},\lambda_{failure}.
\]

### Route B: decision-aware training

Augment event likelihood with a differentiable or surrogate penalty for errors that alter downstream control decisions. Pure likelihood weights every event according to statistical evidence, not operational consequence.

### Route C: closed-loop Liquid-OSAHR

Move from exogenous schedule

\[
\hat\lambda(t_i|\text{recorded history})
\]

to a live continuous state

\[
\dot H=F_{G_t}(H,u,t),
\qquad
\lambda_e=g_e(G_t,H_t),
\]

with graph rewrites applying hidden-state jump maps.

### Route D: certified neural stochastic scheduling

Develop valid bounds/integrals for neural hazards so continuously varying CfC/LTC intensities can be sampled with mathematically controlled thinning or integrated-hazard inversion.

### Route E: graph-coupled liquid state

Give UEs, gNBs and MEC nodes their own liquid states and couple them through current OSAHR hyperedges. A handover would then modify not only a symbolic relation but the continuous vector field itself.

---

## 19. Bottom line

Experiment 01 demonstrates a legitimate Liquid-OSAHR architecture:

\[
\boxed{
\text{irregular observation}
\rightarrow
\text{liquid stochastic intensity}
\rightarrow
\text{exact typed graph event}
}
\]

and: more importantly: finds where the architecture is *not yet sufficient*.

CfC provides a repeatable likelihood advantage under ID and pure sparse-observation conditions, even against a parameter-matched GRU. That advantage does not extend universally to stronger physical regime shifts. And stochastic graph simulation exposes a second problem that ordinary sequence benchmarks can hide: a model can predict hazards well yet still distort counterfactual policy effects.

That is not a failure of the experiment. It identifies the next technical target precisely:

> **Liquid-OSAHR should optimize not only for temporal predictive accuracy, but for preservation of causal/decision-relevant stochastic structure.**

# 16. OSAHR bridge study design

Regimes:

- ID;
- paired sparse.

Hazard sources:

- oracle teacher;
- CfC;
- GRU-dt;
- parameter-matched GRU;
- constant-rate baseline.

Policies:

- throughput;
- semantic.

Independent units are six paired `(fast, robust)` telemetry scenarios per regime. Each arm has two stochastic OSAHR replicates. The combined release therefore contains

\[
2\times6\times5\times2\times2=240
\]

unique bridge rows.

Stochastic replicates on the same telemetry scenario are averaged before bootstrap inference. The scenario is the resampling unit, preventing pseudoreplication.

All model/policy arms for a `(regime, scenario, replicate)` unit use the same OSAHR root seed. This common-random-number coupling reduces Monte Carlo noise but cannot maintain pathwise identity once alternative policies or hazards choose different events.

# 17. Oracle semantic policy effect

The oracle twin establishes what the declared physical teacher itself supports.

## ID

\[
U_{semantic}-U_{throughput}=+0.009810
\]

with scenario-bootstrap 95% CI

\[
[-0.022301,0.039602].
\]

No reliable semantic-policy benefit is established in ID.

## Paired sparse

\[
\boxed{U_{semantic}-U_{throughput}=+0.024278}
\]

with 95% CI

\[
\boxed{[0.013359,0.034541]}.
\]

Within this small six-scenario study, semantic prioritization has a positive oracle effect when the same physical system is controlled from a sparser hazard-update schedule.

# 18. Learned-twin distribution fidelity

Mean absolute goal-utility error to the oracle, averaged across policies:

| Regime | Model | Goal-utility MAE |
|---|---|---:|
| ID | **GRU-dt** | **0.046238** |
| ID | matched GRU | 0.058808 |
| ID | CfC | 0.064278 |
| ID | constant | 0.106131 |
| paired sparse | **matched GRU** | **0.071622** |
| paired sparse | CfC | 0.073459 |
| paired sparse | GRU-dt | 0.080188 |
| paired sparse | constant | 0.097760 |

CfC is clearly more useful than the homogeneous baseline, but it does not dominate recurrent alternatives in downstream distributional fidelity.

# 19. Policy-effect fidelity

Define estimated effect error as

\[
\left(\hat U_{sem}-\hat U_{thr}\right)
-
\left(U^{oracle}_{sem}-U^{oracle}_{thr}\right).
\]

| Regime | Model | Policy-effect MAE | Effect-sign agreement |
|---|---|---:|---:|
| ID | **matched GRU** | **0.035121** | 83.3% |
| ID | CfC | 0.042414 | 50.0% |
| ID | GRU-dt | 0.048393 | 33.3% |
| ID | constant | 0.066875 | 50.0% |
| paired sparse | **CfC** | **0.024058** | 83.3% |
| paired sparse | matched GRU | 0.043334 | 50.0% |
| paired sparse | constant | 0.045078 | 66.7% |
| paired sparse | GRU-dt | 0.047227 | 100% |

With only six independent scenarios, these are exploratory estimates. Nevertheless, paired sparse observation is the downstream setting in which CfC looks most promising: it has the smallest policy-effect magnitude error while retaining the oracle effect sign in five of six scenarios.

# 20. Counterfactual distortion: the most important negative result

Some learned twins make the semantic policy look more decisively beneficial than the oracle twin does.

Examples:

- ID parameter-matched GRU semantic advantage: +0.029733, with a bootstrap interval barely above zero; the oracle ID effect is +0.009810 and includes zero.
- paired-sparse GRU-dt semantic advantage: +0.055932; the oracle effect is +0.024278.

These results must **not** be interpreted as evidence that the learned models discovered a stronger true intervention effect.

They show that a predictive stochastic model can distort a counterfactual comparison.

This is a central lesson of Experiment 01:

> **Digital-twin validation must include intervention/policy-effect recovery, not only prediction likelihood.**

# 21. What Experiment 01 establishes

1. A CfC network can serve as a learned marked-hazard layer for OSAHR.
2. Irregular-time liquid state and typed structural stochastic semantics can be cleanly separated.
3. Exact stochastic graph execution can be preserved conditional on an explicitly piecewise-constant learned hazard schedule.
4. CfC has a stable ID/paired-sparse identification advantage over a near-parameter-matched GRU in this teacher, while GRU is stronger under larger physical regime shifts.
5. Point-process calibration and counterfactual policy fidelity remain separate validation problems.
6. The open-system OSAHR boundary is an effective interface between neural dynamics and formal stochastic graph rewriting.

# 22. What Experiment 01 does not establish

The release does **not** justify claims that:

- CfC universally outperforms GRU/LSTM;
- the synthetic teacher is a real 5G/6G RAN model;
- the semantic policy will reproduce these effects on live radio infrastructure;
- low NLL guarantees good policy counterfactuals;
- LTC is inferior under a fair matched-compute comparison;
- arbitrary neural continuous-time hazards have exact OSAHR thinning semantics;
- OSAHR should replace ns-3, srsRAN, RF ray tracing, or standards-based PHY simulators.

# 23. Optimal implementation route after Experiment 01

The experiment supports a layered 6G architecture:

```text
REAL OR HIGH-FIDELITY RADIO SYSTEM
        |
        | irregular telemetry / link events
        v
LIQUID STATE + HAZARD ESTIMATOR
        CfC initially
        |
        | marked conditional intensities
        v
OSAHR STRUCTURAL SHADOW TWIN
        UE / gNB / MEC / Task hypergraph
        exact stochastic rewrites between updates
        |
        | distributions + causal counterfactuals
        v
SMO / NON-RT RIC POLICY EVALUATION
        |
        | reduced policy
        v
NEAR-RT / LIVE CONTROL
```

OSAHR should occupy the adaptive causal/control abstraction layer. It should federate with standards-based radio simulators rather than reimplement them.

# 24. Experiment 02

The next target is the actual closed-loop Liquid-OSAHR process:

\[
\dot H=F_{G_t}(H,u,t),
\]

\[
\lambda_e=\lambda_e(G_t,H_t,t),
\]

\[
(G,H)\mapsto(T_e(G),J_e(H)).
\]

with generator

\[
\mathcal L f(G,H)
=
\nabla_Hf\cdot F_G
+
\sum_e\lambda_e(G,H,t)
[f(T_eG,J_eH)-f(G,H)].
\]

Recommended sequence:

1. ingest ns-3, srsRAN, O-RAN testbed, or measured RAN telemetry;
2. train event intensities from real link/service/failure histories;
3. create entity-scoped liquid states for UE/gNB/MEC nodes;
4. feed OSAHR handover, failure, route, and service events back into the neural state;
5. develop certified neural hazard envelopes or analytically bounded heads for exact thinning;
6. evaluate open-loop versus closed-loop model calibration;
7. validate policy ranking and treatment-effect recovery on held-out intervention scenarios;
8. extend toward graph-coupled liquid dynamics over OSAHR's stochastically changing typed hypergraph.

# 25. Verification audit

At release freeze:

- Liquid-OSAHR tests: **14 passed**;
- original OSAHR 0.2 tests against vendored runtime: **36 passed**;
- bytecode compilation: passed;
- bridge rows: **240 unique arms**;
- independent bridge scenarios: 6 per regime;
- stochastic replicates: 2 per scenario/arm;
- bridge scenario-bootstrap: 20,000 replicates;
- paired identification bootstrap: 30,000 replicates;
- CfC seed-sensitivity runs: 3;
- parameter-matched GRU seed-sensitivity runs: 3;
- clipping values audited: 110,970;
- clipping values above safety cap: 0;
- common-root random-number audit: passed;
- paired-sparse physical-event/exposure preservation: tested;
- causal lag recomputation after sparsification: tested;
- incremental/reference OSAHR matcher verification: exercised on a learned-hazard trajectory.

# 26. Primary-source grounding

1. Hasani R, Lechner M, Amini A, Rus D, Grosu R. **Liquid Time-constant Networks.** arXiv:2006.04439.  
   https://arxiv.org/abs/2006.04439
2. Hasani R et al. **Closed-form continuous-time neural networks.** *Nature Machine Intelligence* 4, 992–1003 (2022).  
   https://www.nature.com/articles/s42256-022-00556-7
3. Lechner M et al. **Official Neural Circuit Policies LTC/CfC implementation.**  
   https://github.com/mlech26l/ncps
4. Shchur O et al. **Neural Temporal Point Processes: A Review.** arXiv:2104.03528.  
   https://arxiv.org/abs/2104.03528
5. Marino A, Pacchierotti C, Robuffo Giordano P. **Liquid-Graph Time-Constant Network for Multi-Agent Systems Control.** arXiv:2404.13982.  
   https://arxiv.org/abs/2404.13982
6. Zhu F et al. **Robust Continuous-Time Beam Tracking with Liquid Neural Network.** arXiv:2405.00365 / GLOBECOM 2024.  
   https://arxiv.org/abs/2405.00365
7. Ickin S et al. **Towards Green AI-Native Networks: Evaluation of Neural Circuit Policy for Estimating Energy Consumption of Base Stations.** arXiv:2504.02781.  
   https://arxiv.org/abs/2504.02781
8. 3GPP. **The Network Digital Twin: Enabling Network Intelligence and Automation.** 2026.  
   https://www.3gpp.org/technologies/digital-twin1
9. 3GPP TS 28.561. **Network Digital Twins; Management aspects.** Release 19.  
   https://www.3gpp.org/dynareport/28561.htm
10. O-RAN Alliance. **O-RAN Digital Twin platform / AI and Open RAN research.** 2025.  
    https://www.o-ran.org/press-releases
11. ITU. **IMT-2030: Technical requirements for the 6G future.** 17 March 2026.  
    https://www.itu.int/hub/2026/03/imt-2030-technical-requirements-for-the-6g-future/
12. Calvanese Strinati E et al. **Goal-Oriented and Semantic Communication in 6G AI-Native Networks: The 6G-GOALS Approach.** arXiv:2402.07573.  
    https://arxiv.org/abs/2402.07573

# 27. Final interpretation

The most important result is not a leaderboard win. It is the successful construction of a system in which

\[
\boxed{
\text{continuous-time learned uncertainty}
\rightarrow
\text{stochastic structural events}
\rightarrow
\text{causal counterfactual trajectories}
}
\]

while preserving a strict distinction between what the neural model estimated, what graph events are legal, what stochastic process was executed, and what intervention conclusions are actually validated.

That is the correct foundation for turning Liquid-OSAHR from a synthetic shadow twin into an AI-native 6G Network Digital Twin research program.

# 16. OSAHR bridge study design

Regimes are ID and paired sparse. Hazard sources are oracle teacher, CfC, GRU-dt, parameter-matched GRU, and constant-rate baseline. Policies are throughput and semantic.

The independent unit is a paired `(fast, robust)` telemetry scenario. There are six scenarios per regime, with two stochastic OSAHR replicates per scenario/arm. The combined release therefore contains

\[
2\times6\times5\times2\times2=240
\]

unique bridge rows.

Replicates on the same telemetry scenario are averaged before bootstrap inference, and the scenario is the resampling unit. All model/policy arms for a `(regime, scenario, replicate)` unit use the same OSAHR root seed. This common-random-number coupling reduces Monte Carlo noise but does not imply pathwise identity after competing models choose different events.

# 17. Oracle semantic policy effect

The oracle twin establishes the effect supported by the declared physical teacher itself.

For ID:

\[
U_{semantic}-U_{throughput}=+0.009810,
\]

with 95% scenario-bootstrap CI

\[
[-0.022301,0.039602].
\]

No reliable semantic-policy effect is established.

For paired sparse:

\[
\boxed{U_{semantic}-U_{throughput}=+0.024278},
\]

with 95% CI

\[
\boxed{[0.013359,0.034541]}.
\]

Within this six-scenario study, semantic prioritization has a positive oracle effect under a sparser hazard-update schedule.

# 18. Learned-twin distribution fidelity

Mean absolute goal-utility error to oracle, averaged across policies:

| Regime | Model | Goal-utility MAE |
|---|---|---:|
| ID | **GRU-dt** | **0.046238** |
| ID | matched GRU | 0.058808 |
| ID | CfC | 0.064278 |
| ID | constant | 0.106131 |
| paired sparse | **matched GRU** | **0.071622** |
| paired sparse | CfC | 0.073459 |
| paired sparse | GRU-dt | 0.080188 |
| paired sparse | constant | 0.097760 |

CfC is more useful than the homogeneous baseline, but does not dominate recurrent alternatives in downstream distributional fidelity.

# 19. Policy-effect fidelity

Define effect error as

\[
(\hat U_{sem}-\hat U_{thr})-(U^{oracle}_{sem}-U^{oracle}_{thr}).
\]

| Regime | Model | Policy-effect MAE | Effect-sign agreement |
|---|---|---:|---:|
| ID | **matched GRU** | **0.035121** | 83.3% |
| ID | CfC | 0.042414 | 50.0% |
| ID | GRU-dt | 0.048393 | 33.3% |
| ID | constant | 0.066875 | 50.0% |
| paired sparse | **CfC** | **0.024058** | 83.3% |
| paired sparse | matched GRU | 0.043334 | 50.0% |
| paired sparse | constant | 0.045078 | 66.7% |
| paired sparse | GRU-dt | 0.047227 | 100% |

With only six independent scenarios these remain exploratory. Nevertheless, paired sparse is the downstream setting in which CfC looks most promising: it has the smallest policy-effect magnitude error and retains the oracle effect sign in five of six scenarios.

# 20. Counterfactual distortion

Some learned twins make the semantic policy look more decisively beneficial than the oracle twin does. For example, ID parameter-matched GRU estimates +0.029733 semantic advantage while the oracle ID effect is +0.009810 and includes zero; paired-sparse GRU-dt estimates +0.055932 versus the oracle +0.024278.

This is **not** evidence of a stronger true intervention effect. It is model-induced counterfactual distortion.

> **Digital-twin validation must include intervention/policy-effect recovery, not only predictive likelihood.**
