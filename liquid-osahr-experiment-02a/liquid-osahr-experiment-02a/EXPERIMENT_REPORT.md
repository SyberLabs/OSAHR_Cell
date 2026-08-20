# Liquid-OSAHR Experiment 02A — Full Technical Report

**Closed-loop topology-coupled continuous neural state with certified stochastic graph-rewrite hazards.**

## Executive result

Experiment 02A successfully implements the full bidirectional Liquid-OSAHR loop:

\[
H_t \rightarrow \lambda(G_t,H_t) \rightarrow \Delta G_t \rightarrow J(H_t,\Delta G_t) \rightarrow H_{t^+}.
\]

The implementation is exact with respect to the declared hybrid stochastic model: neural event intensities are analytically bounded by sigmoid heads, OSAHR samples jump times with rejection thinning against those certified bounds, rejected candidates do not advance neural state, and accepted graph rewrites atomically update both structure and continuous state.

The main scientific finding is deliberately non-celebratory: **closing the neural feedback loop is not automatically counterfactually superior.** In several regimes, the no-jump or frozen-open-loop CfC ablations recover oracle intervention effects better than the fully closed learned jump model. The new failure mode is clear: learned feedback can recursively amplify small hazard/jump misspecification even while the process remains mathematically well-defined.

Therefore the principal conclusion is:

> **A neural digital twin must be validated on intervention-effect recovery, not only predictive/hazard accuracy.**

## 1. Research motivation

Liquid/CfC networks provide continuous-time recurrent state evolution without requiring a general ODE solver for each query. Liquid-Graph Time-Constant work independently shows how liquid state can be coupled through graph structure. PDMP theory supplies the correct stochastic class when deterministic/continuous flow is interrupted by random jumps. Recent graph-neural jump-ODE research independently supports separating continuous graph evolution from abrupt topology events. 6G digital-twin and semantic-communication research provides a concrete application domain where topology, task value, mobility, failure, and control co-evolve.

Experiment 02A combines these strands but preserves a stricter semantic boundary: neural state determines **rates**, while OSAHR determines **legal typed events, stochastic execution, structural mutation, provenance, and counterfactual policy semantics**.

## 2. Hybrid process

The augmented process is

\[
X_t=(G_t,H_t,B_t,\mathcal R_t,\Theta_t,Z_t,t,n).
\]

Between jumps, the topology is fixed and the liquid state follows a graph-conditioned flow. At an accepted stochastic rewrite, OSAHR changes the graph and the neural field applies an event-specific jump to only the affected persistent entities. The new graph determines the next continuous vector/segment field.

For a test function, the intended conceptual generator is

\[
\mathcal L f(G,H)=\nabla_H f\cdot F_G(H)+\sum_e\lambda_e(G,H)\left[f(T_eG,J_eH)-f(G,H)\right].
\]

This is a finite-dimensional piecewise-deterministic Markov process whenever the current graph is finite and intensities satisfy the declared bounds.

## 3. Topology-coupled state

Persistent liquid states are attached to UE, gNB, and MEC/EdgeNode vertices. Task vertices remain explicit OSAHR objects but do not own liquid state in 02A.

The continuous field sees 14 structural features per persistent entity and three typed relation channels: `Association`, `Path`, and `Transit`. Each relation channel has a separate hidden-state message map. The live OSAHR graph is re-projected whenever its epoch changes.

This means a handover changes liquid coupling even without an explicit learned jump; a task route/completion changes `Transit`; edge failure/recovery alters availability features and stochastic legality.

## 4. Closed-form anchored CfC field

The experiment uses a self-contained CfC cell plus a strict outer anchor blend. If `C` is the CfC candidate state,

\[
H(t+\Delta)=H_t+(1-e^{-\operatorname{softplus}(\kappa)\Delta})(C-H_t).
\]

Thus `Phi(H,0)=H` exactly. This is tested directly.

The near-parameter-matched graph-GRU uses the same relation messages, structural inputs, jump API, anchor blend and hazard head; elapsed time is explicitly supplied to the GRU input so the comparison does not withhold timing information.

Parameter counts:

- `cfc_closed`: **13,952**
- `gru_closed`: **14,166**
- `cfc_nojump`: **13,952**

The CfC/GRU parameter mismatch is below 2%.

## 5. Event jump map

At a committed graph event, the learned field first flows to the event time under the pre-event topology. OSAHR then commits the graph rewrite, after which the field applies

\[
H^+=H^-+A_e\odot 0.35\,\sigma(g(H^-,X^+))\odot\tanh(E_e+WX^+).
\]

`A_e` is a deterministic affected-entity mask obtained from typed rule roles. Unaffected entities are guaranteed unchanged by the jump itself. `cfc_nojump` removes this term while preserving dynamic topology; `cfc_openloop` additionally freezes the neural topology/state trajectory at its initial graph, while OSAHR still enforces current structural legality.

## 6. Certified bounded neural hazards

Each neural head is

\[
\lambda_k=\epsilon+(B_k-\epsilon)\sigma(z_k).
\]

Therefore the global upper bound does not depend on empirical training coverage:

\[
0<\lambda_k\le B_k.
\]

Bounds used are service 5.00, edge failure 0.22, edge recovery 0.85, and handover 0.24. Completion modifiers are constrained not to increase the service base intensity, so the service bound remains valid for every concrete graph match.

This is the central exactness device. OSAHR can use the bounds directly for rejection thinning rather than estimating a maximum neural intensity from sampled data.

## 7. Candidate purity and caching

Thinning may inspect many rejected candidate times. A rejected candidate must not modify the authoritative liquid state. `state_at(t)` and `base_rates_at(t)` therefore compute from the last committed anchor without mutation.

The same candidate time can be queried for many graph matches, so the neural state/rate tensor is cached by `(candidate_time, graph_epoch, anchor_time)`. This changes only computational cost: every occurrence still reads the same field state it would have obtained without caching.

## 8. Oracle teacher

The ground-truth field is analytically soluble:

\[
\dot H=-\alpha_{type}(H-\mu(G,S)),
\]

with solution

\[
H(t+\Delta)=\mu+(H_t-\mu)e^{-\alpha\Delta}.
\]

The equilibrium depends on live topology, MEC load/availability, queue and transit pressure, path quality and scenario context. Accepted events add deterministic mechanistic latent jumps. The teacher is intentionally synthetic: it creates a known, nontrivial hybrid system for identification and counterfactual validation; it is not claimed to be standards-complete RAN physics.

## 9. Identification dataset

Release dataset: 20 training traces / 1,572 frames; 5 validation traces / 365 frames; 7 held-out ID traces / 587 frames. Additional independent high-mobility and high-stress traces are used for OOD identification.

The learning target is the oracle base hazard tensor on semantically applicable entity/head cells. The loss combines squared log-intensity error with normalized intensity error so rare failure/recovery heads and high-rate service are both represented.

### Held-out ID identification

| Model | Normalized MAE | log-RMSE | raw MAE |
|---|---:|---:|---:|
| cfc_closed | 0.04962 | 0.14363 | 0.09164 |
| cfc_nojump | 0.04166 | 0.11978 | 0.08185 |
| gru_closed | 0.04486 | 0.12629 | 0.09993 |

The no-jump CfC is best on this small ID identification set, which already warns that explicit learned jump feedback is not guaranteed to help even when the teacher contains true jumps. Dynamic topology itself can expose much of the event consequence.

### OOD normalized MAE

| Regime | cfc_closed | cfc_nojump | gru_closed |
|---|---:|---:|---:|
| high_mobility | 0.14423 | 0.13036 | 0.09796 |
| high_stress | 0.09802 | 0.08392 | 0.10558 |

Again there is no universal liquid win. Under high mobility the closed GRU has lower normalized MAE than closed CfC; under high stress the no-jump CfC is best of these three on normalized MAE. The release therefore treats architecture selection as regime-dependent rather than ideological.

## 10. Counterfactual study design

The release study contains **360 unique trajectories**:

\[
3\;regimes\times6\;scenarios\times5\;field\;models\times2\;policies\times2\;replicates.
\]

Regimes: ID, high mobility, high stress. Policies: throughput and task-aware semantic routing. Field models: oracle, closed CfC, no-jump CfC, frozen-open-loop CfC, closed matched GRU.

The telemetry/network scenario is the independent unit. The two stochastic replicas per arm are averaged before bootstrap. All reported release bootstrap intervals use **50,000 scenario resamples**.

Common root random-number derivation is shared across competing arms for the same scenario/replicate; trajectories diverge legitimately once different hazards/policies select different events.

## 11. Oracle policy effect

The oracle itself does not say that semantic routing is universally beneficial in this 10-second 02A task world:

| Regime | Oracle goal-utility effect (semantic - throughput) | 95% scenario bootstrap CI |
|---|---:|---:|
| id | -0.00662 | [-0.07101, +0.05777] |
| high_mobility | -0.03259 | [-0.06702, -0.00178] |
| high_stress | -0.00267 | [-0.03441, +0.02794] |

High mobility shows a negative oracle effect in this small sample, while ID and high-stress intervals include zero. This matters: learned twins that confidently predict a positive semantic intervention in those regimes can be **counterfactually wrong even if their hazard predictions look reasonable**.

## 12. Policy-effect fidelity

Primary metric:

\[
MAE_\Delta=\frac{1}{S}\sum_s |\hat\Delta_s-\Delta_s^{oracle}|.
\]

### Goal-utility intervention-effect MAE

| Regime | cfc_closed | cfc_nojump | cfc_openloop | gru_closed | best |
|---|---:|---:|---:|---:|---|
| id | 0.11429 | 0.05527 | 0.05386 | 0.10046 | **cfc_openloop** |
| high_mobility | 0.06780 | 0.07108 | 0.03944 | 0.07182 | **cfc_openloop** |
| high_stress | 0.07321 | 0.07430 | 0.04143 | 0.08511 | **cfc_openloop** |

This is the central 02A result: full learned feedback is **not** the best arm in any of the three regimes on the primary intervention-effect metric. ID favors the open/no-jump CfC variants; high mobility and high stress favor the frozen open-loop CfC on effect magnitude fidelity.

That does not invalidate the closed-loop architecture. It demonstrates that the architecture introduces an additional model-risk channel: an imperfect jump map feeds its own errors into future latent state, which modifies future hazards, which changes future graph structure.

## 13. Level fidelity

Goal-utility level MAE to oracle after averaging replicas:

| Regime | cfc_closed | cfc_nojump | cfc_openloop | gru_closed |
|---|---:|---:|---:|---:|
| id | 0.10651 | 0.06385 | 0.12154 | 0.09157 |
| high_mobility | 0.11363 | 0.09745 | 0.08955 | 0.08311 |
| high_stress | 0.19544 | 0.20088 | 0.19579 | 0.16390 |

The best aggregate level model also changes by regime: no-jump CfC on ID; matched GRU on high mobility and high stress.

## 14. Direct feedback ablation

The release bootstraps the *paired difference in absolute oracle error*. Negative values mean `cfc_closed` is better; positive values mean the comparator is better.

Selected goal-utility results:

| Regime | Comparison | closed minus comparator effect-error | 95% CI | closed minus comparator level-error | 95% CI |
|---|---|---:|---:|---:|---:|
| id | cfc_nojump | +0.05901 | [-0.02657, +0.19504] | +0.04266 | [+0.01744, +0.07437] |
| id | cfc_openloop | +0.06043 | [-0.00963, +0.18458] | -0.01503 | [-0.07803, +0.03744] |
| high_mobility | cfc_nojump | -0.00328 | [-0.02288, +0.01407] | +0.01618 | [-0.01109, +0.05555] |
| high_mobility | cfc_openloop | +0.02836 | [-0.02750, +0.11693] | +0.02408 | [-0.02849, +0.07676] |
| high_stress | cfc_nojump | -0.00109 | [-0.01722, +0.01539] | -0.00544 | [-0.04767, +0.03042] |
| high_stress | cfc_openloop | +0.03178 | [+0.00164, +0.07052] | -0.00035 | [-0.03187, +0.04115] |

Most effect-error intervals are wide because there are only six independent scenarios. One notable result is high-stress `cfc_closed` versus `cfc_openloop`: the closed model has **larger** goal-utility effect error by about +0.0318, with bootstrap CI approximately [+0.0016,+0.0705]. On ID, the closed model also has significantly worse goal-utility level error than the no-jump CfC (difference +0.0427, CI roughly [+0.0174,+0.0744]).

For mean latency under high stress, feedback helps materially relative to both no-jump and open-loop CfC; the closed-minus-nojump level-error difference is about -0.1019 with a negative bootstrap interval. This shows the feedback loop is not simply harmful—it improves some dynamical quantities while degrading some intervention estimands.

## 15. Exact thinning audit

The 360-run study produced 25,372 rejected thinning candidates across 979 crossed thinning windows. The largest trajectory had 134 accepted events and the largest per-run rejection count was 272.

Mean rejected candidates per accepted-event denominator was 0.933. All 360 final state hashes were unique, as expected across distinct stochastic/model/policy arms.

No learned bound is inferred from those observations; the sigmoid form certifies the bound independently of sampled data.

## 16. Verification

The release test suite directly checks:

- oracle and neural rates obey certified bounds;
- actual per-occurrence OSAHR hazards do not exceed their declared bound;
- candidate-time state queries are pure;
- repeated peeks do not mutate state or random scheduling decisions;
- neural evaluation caching reuses the same flow at identical candidate time/graph epoch;
- accepted structural events commit liquid anchors;
- handover changes the live graph-derived topology;
- snapshot/restore reproduces the next event and augmented state hash;
- incremental matching agrees with the exhaustive reference matcher during a closed-loop learned trajectory;
- dynamic topology changes the liquid field versus a frozen adjacency;
- open-loop field ignores event feedback while preserving OSAHR legality masking;
- `Phi(H,0)=H` for both CfC and GRU field wrappers;
- neural jump maps modify only explicitly affected entities;
- extreme latent inputs still produce finite rates within the global sigmoid bounds;
- CfC and GRU parameter budgets remain within 2%.

At release freeze: **17 Experiment 02A tests + 36 original OSAHR 0.2 reference tests pass.**

## 17. Interpretation

Experiment 02A establishes the computational object but also exposes its core epistemic risk. In an open-loop model, hazard error affects the current stochastic decision. In a closed-loop neural twin, an error can propagate recursively:

\[
\delta\lambda_t \rightarrow \delta e_t \rightarrow \delta G_{t^+} \rightarrow \delta H_{t^+} \rightarrow \delta\lambda_{t+1}\rightarrow\cdots
\]

This recursive amplification is exactly why closed-loop twins are powerful—and why intervention validation must be stronger than prediction validation.

The experiment therefore suggests a hierarchy of trust:

1. verify structural semantics;
2. verify hazard bounds and stochastic calibration;
3. verify one-step/trajectory state fidelity;
4. verify event-distribution fidelity;
5. **verify policy/intervention-effect recovery**;
6. only then use the twin as a policy-selection instrument.

## 18. 6G interpretation

The architecture remains best positioned above PHY/RF simulators. ITU IMT-2030 explicitly includes AI and Communication and ubiquitous intelligence; 3GPP Release-19 has standardized management aspects of Network Digital Twins; O-RAN maintains digital-twin infrastructure for AI/Open-RAN experimentation; and goal-oriented 6G research argues for value/relevance-aware resource allocation.

Accordingly, Liquid-OSAHR should act as a **shadow policy imagination layer** receiving irregular telemetry or simulator outputs, learning slowly varying latent network condition, and evaluating distributions of typed structural futures before candidate policies are deployed through Non-RT RIC/SMO mechanisms.

It should not replace ns-3, srsRAN, RF propagation tools, or standards-conformant protocol stacks.

## 19. Limitations

- synthetic oracle rather than measured RAN data;
- only 6 independent scenarios per counterfactual regime;
- 10-second counterfactual horizon;
- small fixed persistent network population;
- learned jump maps are flexible rather than physically regularized;
- no RF/PHY/MAC/RLC/PDCP/HARQ/beamforming model;
- one training seed in the main 02A release;
- no continuous neural hazard integral is computed for path likelihood; exact generation relies on thinning, not analytic integrated neural hazards;
- no certification yet for unconstrained neural hazard architectures beyond the deliberately bounded sigmoid head.

## 20. Optimal Experiment 02B

The next step should not simply make the model larger. It should attack the failure mode found here.

**02B: intervention-calibrated Liquid-OSAHR with real/high-fidelity RAN traces.**

Recommended sequence:

1. federate with ns-3/srsRAN/O-RAN traces or measured private-RAN telemetry;
2. keep the certified bounded hazard head;
3. replace unrestricted event jumps with mechanistically constrained/residual jump maps;
4. train not only hazard reconstruction but multi-step rollout/event-distribution objectives;
5. include intervention/policy episodes in training/validation when available;
6. compare open-loop, topology-only, learned-jump, mechanistic-jump and residual-jump architectures;
7. make policy-effect error an early-stopping/model-selection criterion alongside hazard fit;
8. expand independent scenario count substantially before drawing policy conclusions;
9. couple a lower-layer packet/RAN model while keeping OSAHR at the semantic/control plane;
10. eventually add certified interval/Lipschitz bounds if the hazard field becomes more expressive than a globally bounded head.

## 21. Apex inference

The experiment confirms the architectural possibility:

\[
\boxed{\text{continuous learned state}\leftrightarrow\text{typed stochastic structural change}}
\]

But its strongest result is that the feedback arrow itself is a source of epistemic risk. The productive research program is therefore not merely to make the twin more adaptive. It is to develop **counterfactually calibrated adaptive twins** whose closed-loop learned dynamics are judged by whether they preserve the consequences of interventions.

That is a sharper and more valuable goal than ordinary next-event prediction.

## 22. Primary references

- Hasani et al., Closed-form Continuous-time Neural Models (CfC): https://arxiv.org/abs/2106.13898
- Hasani et al., Liquid Time-constant Networks: https://arxiv.org/abs/2006.04439
- Marino et al., Liquid-Graph Time-Constant Network for Multi-Agent Systems Control: https://arxiv.org/abs/2404.13982
- Azaïs et al., Piecewise deterministic Markov process — recent results: https://arxiv.org/abs/1309.6061
- Lemaire et al., Exact simulation of jump times of PDMPs: https://arxiv.org/abs/1602.07871
- Sevak et al., Physics-Informed Graph Neural Jump ODEs for Cascading Failure Prediction (2026): https://arxiv.org/abs/2603.20838
- Shchur et al., Neural Temporal Point Processes: A Review: https://arxiv.org/abs/2104.03528
- 3GPP TS 28.561, Management aspects of Network Digital Twins: https://www.3gpp.org/dynareport/28561.htm
- 3GPP, The Network Digital Twin: Enabling Network Intelligence and Automation: https://www.3gpp.org/technologies/digital-twin1
- ITU, IMT-2030 programme: https://www.itu.int/en/ITU-R/study-groups/rsg5/rwp5d/imt-2030/pages/default.aspx
- O-RAN ALLIANCE, Digital Twin platform / AI Open RAN research: https://www.o-ran.org/press-releases
- Calvanese Strinati et al., 6G-GOALS: https://arxiv.org/abs/2402.07573
