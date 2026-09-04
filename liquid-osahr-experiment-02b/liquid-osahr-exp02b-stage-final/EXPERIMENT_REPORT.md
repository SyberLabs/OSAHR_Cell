# Liquid-OSAHR Experiment 02B: Intervention-Calibrated Standards-Informed RAN Twin

**Release:** 0.2.0  
**Experiment status:** completed research prototype / confirmatory synthetic study  
**Primary question:** can a mechanistically anchored liquid-neural residual improve a stochastic RAN digital twin *without sacrificing counterfactual policy fidelity*?

## 1. Executive result

Experiment 02B implements a standards-informed FR1 RAN surrogate, a simplified engineering/mechanistic hazard prior, a topology-coupled CfC residual with globally bounded stochastic intensities, exact OSAHR thinning, intervention-based trust calibration, external srsRAN/5G-LENA telemetry adapters, and a new untouched confirmatory study after the calibration protocol was frozen.

The headline result is deliberately nontrivial:

1. full residual trust (`alpha=1`) improves factual hazard identification over the mechanism on validation and on every OOD hazard set;
2. intervention calibration on 18 independent scenarios nevertheless chooses `alpha=0`, i.e. the mechanistic fallback;
3. that choice is calibration-stable (18/18 leave-one-scenario-out folds; 96.67% of 20,000 stratified bootstrap recalibrations);
4. on a **new untouched 400-run confirmatory holdout**, no single alpha dominates counterfactually: ID favors `alpha=.5`, high-stress goal utility favors `.25`, high mobility and weak channel favor the mechanism for that estimand, while full trust is best for some latency effects;
5. therefore **predictive trust and intervention trust are different quantities, and one global scalar trust coefficient is not sufficient**.

This is stronger evidence for the core OSAHR design principle than a simple neural-model win would have been: the structural stochastic twin must validate the causal consequences of interventions, not only the accuracy of local predictions.

## 2. Scope and exactness boundary

02B is **not** a 3GPP-conformance simulator and is **not** presented as a replacement for 5G-LENA/ns-3, srsRAN, Sionna RT, or commercial RF twins. Those packages were not available locally in this execution environment. Instead 02B implements a deterministic standards-informed system-level surrogate whose large-scale propagation follows the 3GPP TR 38.901 UMi-Street-Canyon form and whose observable telemetry surface mirrors practical RAN metrics exposed by srsRAN/O-RAN paths.

Exact conditional semantics:

- OSAHR typed matching and DPO applicability;
- graph rewrites and deterministic replay;
- common-random-number seed partitioning;
- neural/global rate bounds;
- thinning conditional on the declared continuously varying bounded rates;
- candidate-time state queries are pure and rejected thinning candidates do not commit liquid state.

Model-dependent approximations:

- analytical/stochastic surrogate instead of a full NR PHY/MAC/RLC stack;
- smooth LOS mixing rather than sampled 38.901 channel condition state;
- bounded Doppler/fading surrogate rather than a clustered delay-line channel;
- CQI, BLER/drop, PRB/load and throughput proxies;
- simple A3-like handover pressure rather than complete RRC measurement/event semantics;
- synthetic application/task utility.

## 3. Standards-informed RAN layer

The site model uses 3.5 GHz, 40 MHz, two gNBs, four mobile UEs and two edge/MEC resources. The implemented telemetry includes:

`RSRP`, `SINR`, `CQI`, spectral efficiency, neighbor margin, speed, utilization, drop probability, throughput proxy.

Large-scale UMi path loss uses the 38.901 form implemented in `RANPhysics._pathloss_umi`; stochastic scenario variation is encoded into deterministic seed-conditioned shadow/fading fields so a physical realization is a pure function of `(scenario, seed, time, graph)`. This makes common-random-number policy comparisons meaningful.

02B additionally ships adapters for:

- srsRAN JSON metrics / E2SM-KPM terminal metric names;
- 5G-LENA/ns-3 CSV trace sources through an explicit alias map.

See `TELEMETRY_CONTRACT.md` and `canonical_kpm_schema.json`.

## 4. Mechanism + bounded residual

Let the engineering prior for an event head be `lambda_mech`, with certified global ceiling `B` and floor `eps`. The learned residual model is

```text
p_mech = (lambda_mech - eps) / (B - eps)
z_mech = logit(p_mech)
r = L * tanh(r_CfC(H, X, G))
lambda_alpha = eps + (B-eps) * sigmoid(z_mech + alpha*r)
```

where `L` is a fixed residual-logit limit and `alpha in [0,1]` is the neural trust parameter.

Properties:

- `alpha=0` is now an **exact runtime identity** to the mechanistic hazard, bypassing float32 neural conversion;
- all nonzero-trust hazards remain inside the same certified global OSAHR bound;
- topology still determines legal rewrite occurrences;
- the neural model corrects rates, not ontology or rewrite legality;
- unlike 02A, there is no free learned post-event jump map in 02B.

The trained residual CfC has **14,280 parameters**.

## 5. Identification dataset

Synthetic RAN traces:

| Split | Traces | Frames |
|---|---:|---:|
| Train | 14 | 154 |
| Validation | 5 | 55 |
| Test | 5 | 55 |

The residual was trained against oracle event intensities while receiving only telemetry/topology plus the mechanistic rate. Validation-selected predictive trust is **alpha=1.0**.

Validation hazard error:

| Trust | NMAE | log-RMSE |
|---:|---:|---:|
| 0.00 | 0.024672 | 0.354854 |
| 0.25 | 0.022669 | 0.287967 |
| 0.50 | 0.020564 | 0.229578 |
| 0.75 | 0.018451 | 0.185947 |
| 1.00 | 0.017399 | 0.169005 |


The mechanistic validation NMAE is 0.024672; full residual trust reduces it to 0.017399.

## 6. Intervention calibration

The primary calibration target is not hazard prediction. For each physical scenario `s`, let

`Delta_s = E[goal utility | semantic, s] - E[goal utility | throughput, s]`.

Trust is evaluated against absolute oracle policy-effect error:

`|Delta_hat(alpha,s) - Delta_oracle(s)|`.

The final multi-regime calibration set contains **18 independent scenarios** (6 ID, 6 high-mobility, 6 high-stress), one stochastic replicate per arm, and is disjoint in root seed from the confirmatory holdout. The objective is mean intervention-effect MAE plus `0.1 * predictive_NMAE`.

| alpha | Intervention MAE | Predictive NMAE | Objective | Worst-regime MAE |
|---|---|---|---|---|
| 0.0 | 0.04813 | 0.02467 | 0.05060 | 0.07126 |
| 0.25 | 0.08711 | 0.02267 | 0.08938 | 0.18276 |
| 0.5 | 0.07499 | 0.02056 | 0.07705 | 0.14699 |
| 0.75 | 0.10345 | 0.01845 | 0.10529 | 0.19323 |
| 1.0 | 0.10515 | 0.01740 | 0.10689 | 0.21906 |

Selected robust trust:

**alpha = 0.00**.

Stability audit:

- leave-one-scenario-out: alpha=0 in **18/18** folds;
- stratified bootstrap recalibration: alpha=0 in **96.67%** of 20,000 replicates.

This is an intentionally conservative result: the intervention calibration says that, given its calibration sample and loss, the residual should not be trusted globally for policy selection.

## 7. Why a new confirmatory holdout was necessary

An earlier 360-run pilot was inspected while the calibration protocol was still being enlarged. To avoid presenting an analyst-adaptive holdout as confirmatory, 02B froze:

- the mechanism;
- the CfC checkpoint;
- the alpha grid;
- predictive trust;
- the 18-scenario intervention-calibration procedure;
- the primary goal-utility policy-effect error.

Only then was a new root seed (`920218`) used for the final confirmatory study.

## 8. Confirmatory design

The untouched release contains **400 trajectories**:

- 4 regimes: ID, high mobility, high stress, weak channel;
- 5 independent physical scenarios per regime = **20 independent scenarios**;
- 2 stochastic replicates per model/policy arm;
- 5 model/trust arms;
- throughput and semantic policies.

Thus

`4 * 5 * 2 * 5 * 2 = 400`.

The scenario is the inferential unit. Replicates are averaged inside scenario before bootstrap inference. All model/policy arms within the same `(scenario, replicate)` use the same root stochastic seed and physical realization.

Models:

- `oracle`;
- `mechanistic_calibrated` (`alpha=0`, the frozen robust calibration);
- `residual_quarter` (`alpha=.25`, sensitivity arm);
- `residual_idcal` (`alpha=.5`, ID-only calibration arm);
- `residual_predictive` (`alpha=1`, predictive optimum).

The `weak_channel` regime was not part of multi-regime intervention calibration and serves as an additional transport/OOD test.

## 9. Oracle policy effects

Positive goal-utility effect means semantic policy is better; negative means throughput policy is better.

| Regime | Oracle semantic-throughput | 95% CI |
|---|---|---|
| id | -0.04702 | [-0.11671, -0.00323] |
| high_mobility | -0.03032 | [-0.08508, 0.00092] |
| high_stress | 0.04664 | [-0.01873, 0.15101] |
| weak_channel | 0.01009 | [-0.07027, 0.07482] |

The oracle itself therefore rejects any claim that semantic routing is universally superior in this synthetic world. In the five-scenario ID holdout, the oracle effect is negative and its scenario-bootstrap interval excludes zero. The other goal-utility regimes have intervals spanning zero.

## 10. Confirmatory goal-utility fidelity

| Regime | Model | Effect MAE | Level MAE | Sign |
|---|---|---|---|---|
| id | mechanistic_calibrated | 0.09671 | 0.08580 | 0.20 |
| id | residual_quarter | 0.06475 | 0.07052 | 0.20 |
| id | residual_idcal | 0.05109 | 0.06006 | 0.40 |
| id | residual_predictive | 0.05694 | 0.13556 | 0.00 |
| high_mobility | mechanistic_calibrated | 0.04033 | 0.11782 | 0.20 |
| high_mobility | residual_quarter | 0.05112 | 0.10364 | 0.40 |
| high_mobility | residual_idcal | 0.07032 | 0.12633 | 0.40 |
| high_mobility | residual_predictive | 0.05653 | 0.03488 | 0.20 |
| high_stress | mechanistic_calibrated | 0.17914 | 0.14852 | 0.40 |
| high_stress | residual_quarter | 0.07072 | 0.11089 | 0.80 |
| high_stress | residual_idcal | 0.10341 | 0.14016 | 0.40 |
| high_stress | residual_predictive | 0.12395 | 0.16926 | 0.20 |
| weak_channel | mechanistic_calibrated | 0.05587 | 0.09118 | 0.40 |
| weak_channel | residual_quarter | 0.08253 | 0.10494 | 0.20 |
| weak_channel | residual_idcal | 0.06270 | 0.12634 | 0.60 |
| weak_channel | residual_predictive | 0.09159 | 0.06055 | 0.40 |

No single trust level wins every regime.

Paired difference in absolute policy-effect error versus the frozen mechanistic/calibrated arm (negative = residual better):

| Regime | Residual | Delta abs effect error | 95% CI |
|---|---|---|---|
| id | residual_quarter | -0.03196 | [-0.07360, 0.00000] |
| id | residual_idcal | -0.04561 | [-0.10541, -0.00305] |
| id | residual_predictive | -0.03976 | [-0.09672, 0.00580] |
| high_mobility | residual_quarter | 0.01079 | [-0.01707, 0.04945] |
| high_mobility | residual_idcal | 0.02999 | [-0.01612, 0.10419] |
| high_mobility | residual_predictive | 0.01620 | [-0.01306, 0.06753] |
| high_stress | residual_quarter | -0.10842 | [-0.20299, -0.03373] |
| high_stress | residual_idcal | -0.07573 | [-0.17713, 0.01835] |
| high_stress | residual_predictive | -0.05519 | [-0.11816, -0.01057] |
| weak_channel | residual_quarter | 0.02667 | [0.00036, 0.07408] |
| weak_channel | residual_idcal | 0.00684 | [0.00000, 0.01638] |
| weak_channel | residual_predictive | 0.03573 | [-0.01867, 0.12006] |
| macro | residual_quarter | -0.02573 | [-0.05422, 0.00001] |
| macro | residual_idcal | -0.02113 | [-0.05296, 0.01130] |
| macro | residual_predictive | -0.01076 | [-0.03843, 0.01816] |

Most notable within this five-scenario-per-regime design:

- ID `alpha=.5`: improvement `-0.04561`, bootstrap CI `[-0.10541, -0.00305]`;
- high stress `alpha=.25`: improvement `-0.10842`, CI `[-0.20299, -0.03373]`;
- weak-channel `alpha=.25`: degradation `+0.02667`, CI `[+0.00037, +0.07408]`;
- macro `alpha=.25`: improvement `-0.02573`, but the interval reaches essentially zero.

These are scenario-bootstrap intervals over only five independent scenarios per regime; they should be read as confirmatory *within this synthetic experimental design*, not external telecom effect sizes.

## 11. Factual hazard generalization versus counterfactual fidelity

Twenty additional OOD hazard traces (5 per regime) were generated with a separate root seed. Full residual trust gives the lowest hazard NMAE in **every regime**.

Yet the best goal-utility counterfactual trust differs:

| Regime | Best hazard alpha | Best counterfactual alpha | Spearman |
|---|---|---|---|
| id | 1.0 | 0.5 | 0.80 |
| high_mobility | 1.0 | 0.0 | -0.80 |
| high_stress | 1.0 | 0.25 | 0.20 |
| weak_channel | 1.0 | 0.0 | -0.80 |

Detailed OOD hazard NMAE:

| Regime | alpha=0 | .25 | .50 | .75 | 1.0 |
|---|---:|---:|---:|---:|---:|
| id | 0.04047 | 0.03721 | 0.03491 | 0.03352 | 0.03253 |
| high_mobility | 0.03513 | 0.03121 | 0.02797 | 0.02613 | 0.02571 |
| high_stress | 0.04782 | 0.04398 | 0.04140 | 0.04012 | 0.04001 |
| weak_channel | 0.03859 | 0.03401 | 0.02991 | 0.02577 | 0.02216 |


This is the strongest 02B inference:

> **The model can become more accurate about local event intensities while becoming less reliable about the effect of changing policy.**

The failure is therefore not reducible to poor hazard prediction.

## 12. Mechanism misspecification versus residual overtrust

The calibration traces reveal two distinct failure classes.

**Residual overtrust:** increasing alpha creates counterfactual error that the mechanistic fallback avoids. Shrinkage can address this.

**Structural/mechanistic misspecification:** some scenarios produce essentially the same large policy-effect error for all alpha values, including alpha=0. No residual trust shrinkage can fix a causal abstraction that omitted the relevant mechanism.

This distinction matters operationally. A trust controller should not interpret every counterfactual disagreement as a request to reduce neural influence; some failures require changing the graph ontology, physical model, intervention semantics, or observation model.

## 13. External simulator/testbed bridge

02B now contains executable adapters rather than only a conceptual integration plan.

### srsRAN

`SrsRANKPMAdapter` supports terminal names documented on srsRAN's E2SM-KPM path, including:

- CQI / RSRP / RSRQ;
- `DRB.UEThpDl`, `DRB.UEThpUl`;
- `DRB.RlcPacketDropRateDl`;
- `DRB.PacketSuccessRateUlgNBUu`;
- `DRB.RlcSduTransmittedVolumeDL/UL`.

It can also consume JSON-lines captured from the srsRAN JSON/WebSocket metric output. Unknown fields are ignored; missing required time is rejected rather than fabricated.

### 5G-LENA

`FiveGLenaCSVAdapter` provides an explicit alias map for selected ns-3/5G-LENA trace sources. Since 5G-LENA exposes multiple PHY/MAC/application trace formats rather than one universal CSV, the adapter is intentionally extendable and requires an explicit simulation-time field.

## 14. Runtime audit

Confirmatory study:

- trajectories: **400**;
- independent scenarios: **20**;
- total OSAHR events: **8083**;
- max events in one trajectory: **45**;
- thinning candidate rejections: **8865**;
- unique augmented final hashes: **400 / 400**;
- common-root-seed violations across model/policy arms: **0**.

The first confirmatory residual run additionally executed with incremental matching continuously checked against the exhaustive reference matcher.

## 15. Statistical interpretation

The confirmatory design uses five independent scenarios per regime. This is a meaningful improvement over the pilot but still a small-sample mechanistic experiment. Bootstrap intervals quantify scenario sensitivity inside the declared scenario generator; they do not establish population-level effects for real networks.

The correct epistemic reading is:

- the implementation demonstrates the mechanism and exposes failure modes;
- it provides a reproducible counterfactual-validation protocol;
- it does **not** establish field performance in a deployed RAN;
- external validation now requires 5G-LENA/srsRAN/O-RAN or measured traces plus intervention regimes with known/observable policy outcomes.

## 16. What 02B establishes

1. A standards-informed RAN layer can be coupled to exact OSAHR stochastic structural semantics.
2. A CfC can be constrained to a bounded residual over engineering hazard models without controlling rewrite legality.
3. `alpha=0` can be made an exact semantic fallback to the mechanism.
4. Predictive residual correction materially improves hazard identification.
5. Intervention-based calibration can prefer drastically less neural trust than predictive calibration.
6. That calibration decision itself can fail to transport to fresh regimes/scenarios.
7. Local predictive fidelity and downstream counterfactual fidelity are empirically separable in the same closed stochastic graph twin.
8. A single global trust scalar is inadequate for a trustworthy Network Digital Twin.
9. External srsRAN/5G-LENA telemetry can now enter through a stable canonical schema.

## 17. What 02B does not establish

- 5G-LENA/ns-3 equivalence;
- srsRAN/Open-RAN field validation;
- standards conformance of the synthetic handover or scheduling rules;
- superiority of CfC over every recurrent architecture;
- real-world semantic-routing gains;
- that intervention calibration from synthetic oracle access is directly available in deployment;
- that bootstrap intervals over five generated scenarios are telecom population confidence intervals.

## 18. Optimal next architecture

02B rules out both extremes:

`always trust mechanism` and `always trust neural residual`.

The next architecture should represent trust as a state- and query-dependent epistemic variable:

`alpha = alpha(regime, entity, event head, uncertainty, intervention, estimand)`.

The most defensible implementation route is:

1. replace synthetic KPMs with 5G-LENA and/or srsRAN/O-RAN telemetry through the shipped adapters;
2. retain an explicit mechanistic backbone;
3. learn bounded residuals with ensemble/epistemic uncertainty;
4. propagate **model-trust uncertainty** through OSAHR counterfactual ensembles instead of returning one trajectory distribution;
5. calibrate separately for service, failure, recovery and handover heads;
6. validate policy ranking / directional sensitivity on intervention scenarios, not only NLL/RMSE;
7. detect model-inadequacy cases where all trust levels disagree with oracle/observed interventions;
8. only after shadow validation compile reduced decisions into Non-RT RIC/rApp or Near-RT control logic.

## 19. Primary-source research grounding

- 3GPP TS 28.561: Management and orchestration; Management aspects of Network Digital Twins (Release 19). https://www.3gpp.org/dynareport/28561.htm
- 3GPP, “The Network Digital Twin: Enabling Network Intelligence and Automation,” 27 Apr 2026. https://www.3gpp.org/technologies/digital-twin1
- ETSI / 3GPP TR 38.901, channel model for 0.5–100 GHz, including UMi Street Canyon. https://www.etsi.org/deliver/etsi_tr/138900_138999/138901/
- srsRAN Project, JSON Metrics output. https://docs.srsran.com/projects/project/en/latest/user_manuals/source/outputs.html
- srsRAN Project, O-RAN NearRT-RIC and E2SM-KPM application note. https://docs.srsran.com/projects/project/en/latest/tutorials/source/near-rt-ric/source/index.html
- 5G-LENA NR module and feature documentation. https://cttc-lena.gitlab.io/nr/manual/nr-module.html
- O-RAN ALLIANCE Digital Twin Platform / AI and Open RAN research announcement, 22 May 2025. https://www.o-ran.org/press-releases
- Hasani et al., Closed-form continuous-time neural networks (CfC), Nature Machine Intelligence / arXiv:2106.13898.
- Lemaire et al., Exact simulation of jump times of a class of PDMPs, arXiv:1602.07871.
- Laudy, Digital Twin Counterfactual Framework, arXiv:2604.01325 (2026).
- Jimenez Agudelo et al., Towards Trustworthy 6G Network Digital Twins, arXiv:2604.14787 (2026).

## 20. Apex interpretation

02B began with the hypothesis that intervention calibration would tell us *how much* to trust a liquid neural residual.

The result is more important:

> **Trust is not a scalar property of a digital-twin model. It is a property of a model, regime, intervention, outcome, and causal query together.**

The same full residual model was the best local hazard predictor in every tested regime, while different trust levels were optimal for different counterfactual questions. For an OSAHR-style twin, the correct product is therefore not “the most accurate network predictor.” It is a system that carries competing mechanistic/neural hypotheses into counterfactual simulation and exposes where a decision is robust: or fragile: to model trust.
