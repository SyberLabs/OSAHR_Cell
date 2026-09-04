# OSAHR 6G Experiment 01
## Goal-Aware Semantic Control over an Adaptive RAN/MEC Twin

**Date:** 2026-08-12  
**Kernel:** OSAHR 0.2  
**Status:** exploratory mechanistic experiment; exact simulation conditional on an intentionally abstract, non-PHY-calibrated model

## Executive result

This experiment tested whether an OSAHR stochastic adaptive hypergraph can represent a useful 6G control-plane problem: deciding where task-bearing traffic should be sent when mobility, congestion, heterogeneous edge resources, and an edge-node outage alter the network state.

The main 15-second outage experiment used 30 independent trajectories per policy (90 total). The semantic policy produced a higher mean timely goal-utility ratio (0.8264) than throughput-first (0.7995) and task-agnostic QoS (0.7895). It also produced higher critical-task deadline success (0.9052) than throughput-first (0.8698) and QoS (0.8521).

The clearest statistical contrast is semantic vs QoS: independent bootstrap 95% CIs for both goal utility (+0.0369, CI +0.0071 to +0.0677) and critical-task success (+0.0531, CI +0.0142 to +0.0930) exclude zero. Semantic vs throughput is directionally positive but not conclusive at n=30: goal utility +0.0269 with CI -0.0019 to +0.0574; critical success +0.0354 with CI -0.0032 to +0.0757.

A 20-run-per-policy no-outage control shows essentially no semantic advantage: goal utility 0.8778 vs 0.8783 and critical success 0.9908 vs 0.9923. This is important: the model does not make semantic weighting universally superior. Its advantage appears when capacity/reliability must be triaged.

A 20-run-per-policy severe 27-second outage gives positive mean semantic effects on goal utility (+0.0368) and critical success (+0.0529), but with wide confidence intervals. Near congestion collapse, trajectory variance dominates at this sample size.

## Research basis

The experiment was designed against the current 6G direction rather than an imagined air interface:

- ITU IMT-2030 defines AI and Communication (AIAC) and Integrated Sensing and Communication (ISAC) among six 6G usage scenarios, with security/resilience, sustainability, ubiquitous intelligence, and connectivity as overarching principles.
- 3GPP Release 19 introduced management work around Network Digital Twins, including the use of a twin to assess network configuration/policy changes before applying them to a live network. Release 20 contains 6G studies; Release 21 is the first normative 6G release.
- O-RAN's Digital Twin RAN program identifies AI/ML training/evaluation, automated network testing, planning, energy saving, and site-specific optimization as leading DT-RAN use cases, while its key-enabler work emphasizes synchronized physical-network data, modeling, and interfaces.
- The 6G-GOALS research program explicitly proposes timing-aware semantic communication, value/relevance-aware metrics, causal interventions, semantic RIC concepts, and joint communication-computation-control-intelligence optimization.
- Bilen & Akyildiz (arXiv:2603.12695) provide a recent independent example of semantic-aware network-level management evaluated in ns-3 rather than only semantic encoder/decoder design.
- Recent O-RAN/5G-6G connected-robotics testbeds make industrial robots a credible early vertical for task-oriented networking and edge AI.

These sources support placing OSAHR above the PHY/RF simulator, as an adaptive semantic/control digital twin rather than attempting to replace ns-3, radio propagation twins, or a RAN stack.

## Hypothesis

Under uncongested conditions, routing primarily by conventional path/service quality should be sufficient. Under disruption and scarce heterogeneous resources, a controller that conditions route preference on the **utility and urgency of the task** should preserve more application-level value than one that optimizes generic throughput or generic QoS.

The null is not that all policies are identical in every trajectory. The relevant question is whether semantic task conditioning changes the distribution of application-level outcomes under stress.

## State model

Runtime state is the OSAHR augmented state

    X_t = (G_t, B_t, R_t, Theta_t, Z_t, t)

where G is a typed directed hypergraph, B contains open boundary state, R is the active rewrite repertoire, Theta contains parameters, and Z contains sufficient statistics.

### Vertex types

- `UE`: robot endpoint with critical/background generation rates and mobility rate.
- `GNB`: access point.
- `EdgeNode`: MEC node with availability, load, capacity, service rate, reliability, semantic fidelity, and energy cost.
- `Task`: task-bearing message with kind, utility, payload, deadline, birth time, status, and reroute count.

### Hyperedge types

- `Association(UE -> GNB)`
- `Neighbor(GNB -> GNB)`
- `Path(GNB -> EdgeNode)` with link quality
- `Queued(UE -> Task)`
- `Transit(UE -> {Task, GNB, EdgeNode})`

`Transit` is deliberately a higher-order relation. A transmission is not merely a pairwise packet edge; it binds the source, task semantics, current access point, and selected execution destination in one typed relation.

## Environment

Four robot UEs generate two classes of work:

| Class | Rate per UE | Payload | Utility | Deadline |
|---|---:|---:|---:|---:|
| Critical | 0.22/s | 1.0 | 1.00 | 1.5 s |
| Background | 0.48/s | 3.0 | 0.18 | 6.0 s |

Mobility rewrites each UE's `Association` at rate 0.045/s.

Two MEC nodes create an intentional speed/reliability trade-off:

| MEC | Capacity | Service rate | Reliability | Fidelity | Energy cost |
|---|---:|---:|---:|---:|---:|
| Fast | 6 | 8.0 | 0.940 | 0.920 | 1.00 |
| Robust | 3 | 4.2 | 0.997 | 0.990 | 1.18 |

Path quality depends on current gNB:

- A -> Fast: 1.00
- A -> Robust: 0.90
- B -> Fast: 0.84
- B -> Robust: 1.00

Main stress condition: the fast MEC is externally marked unavailable from t=20 to t=35. Arrivals stop at t=50 and the simulation drains until t=60.

No-outage control: outage lies beyond the simulation horizon.

Severe stress: fast MEC unavailable from t=15 to t=42.

## Exact stochastic mechanisms

Task generation is a Poisson-like rewrite channel with hazard

    a_generate = arrival_scale * UE_arrival_rate.

A route occurrence has hazard

    a_route = route_rate * exp(beta * S),

so enabled task/path embeddings compete proportionally to their exponentiated scores while remaining within exact CTMC semantics.

Throughput score:

    S_T = w_s * service_rate/service_scale
          + w_q * link_quality
          - w_l * load/capacity
          - w_e * energy_cost.

QoS score:

    S_Q = S_T + w_r * reliability + w_f * fidelity.

Semantic score:

    S_sem = S_Q
            + w_sem * (task_utility/task_deadline)
                    * reliability * fidelity.

The only experimental treatment is this route-hazard score. The graph, arrival process, service process, mobility, outage, capacities, and all other physical assumptions are unchanged between arms.

Completion hazard:

    a_complete = service_rate * reliability * link_quality
                 / [payload * (1 + gamma * max(0, load-1))].

Failed-edge in-flight tasks become eligible for stochastic rerouting. Handover is a real graph rewrite: the previous `Association` edge is deleted and a new one created.

The simulations use OSAHR's modified next-reaction scheduler and incremental matcher. A separate audit trajectory ran with incremental verification enabled against the exhaustive matcher for every change and completed without mismatch.

## Primary metrics

`goal_utility_ratio` is the primary endpoint:

    timely semantic utility / generated utility.

A task contributes semantic utility only if it arrives before its deadline and is discounted by destination fidelity and link quality.

Other metrics:

- critical-task deadline success
- background-task deadline success
- total timely-task rate
- mean completion latency
- semantic utility per energy
- reroutes
- maximum queued tasks

All generated tasks in the main experiment were delivered by the final drain horizon; the meaningful distinction is whether delivery occurred in time and with useful semantic fidelity.

## Main results: moderate outage

30 trajectories per arm.

| Policy | Goal utility | 95% CI | Critical success | 95% CI | Mean latency |
|---|---:|---:|---:|---:|---:|
| Throughput | 0.7995 | [0.7719, 0.8270] | 0.8698 | [0.8319, 0.9077] | 1.2259 s |
| QoS | 0.7895 | [0.7616, 0.8174] | 0.8521 | [0.8145, 0.8897] | 1.3082 s |
| Semantic | **0.8264** | [0.8115, 0.8412] | **0.9052** | [0.8862, 0.9242] | **1.1486 s** |

Semantic vs throughput:

- Goal utility: +0.0269 (~+3.37% relative); independent bootstrap 95% CI [-0.0019, +0.0574], Welch p=0.085.
- Critical success: +0.0354 (~+3.54 percentage points); CI [-0.0032, +0.0757], p=0.095.

Semantic vs task-agnostic QoS:

- Goal utility: +0.0369; CI [+0.0071, +0.0677], p=0.021.
- Critical success: +0.0531; CI [+0.0142, +0.0930], p=0.013.
- Overall timely-task rate: +0.0255; bootstrap CI [+0.0005, +0.0507], although the Welch p-value is 0.055.

Energy consumption is very similar across the three policies (~354 model energy units), which suggests the utility improvement in this model is chiefly an allocation effect, not a consequence of spending materially more energy.

## Stress controls

### No outage — 20 trajectories per policy

| Policy | Goal utility | Critical success | Mean latency |
|---|---:|---:|---:|
| Throughput | 0.8783 | 0.9923 | 0.6112 s |
| Semantic | 0.8778 | 0.9908 | 0.6179 s |

Semantic minus throughput goal utility = -0.0006, bootstrap CI [-0.0101, +0.0090]. There is no evidence of a useful semantic advantage when healthy capacity makes deadline triage largely unnecessary.

### Severe outage — 20 trajectories per policy

| Policy | Goal utility | Critical success | Mean latency |
|---|---:|---:|---:|
| Throughput | 0.6734 | 0.6877 | 2.1711 s |
| Semantic | 0.7102 | 0.7406 | 2.2001 s |

Semantic minus throughput goal utility = +0.0368, bootstrap CI [-0.0276, +0.1012]. Critical success difference = +0.0529, CI [-0.0248, +0.1294]. Direction is favorable but uncertainty is large.

The stress sweep therefore does not establish monotonic treatment effects. The moderate-outage condition is the cleanest regime: enough scarcity to make prioritization useful, but not so much that congestion-collapse variance dominates.

## Mechanistic interpretation

The QoS ablation is the most informative comparison.

A generic QoS controller sees the robust MEC as globally attractive because of its reliability and fidelity. But that scarce node has only half the capacity and approximately half the service rate of the fast node. Sending low-value/background jobs there can consume exactly the resource that a deadline-critical task later needs.

The semantic controller's extra term

    (utility / deadline) * reliability * fidelity

makes high-reliability/high-fidelity capacity more valuable specifically when the task is both important and urgent. Background jobs can rationally use less reliable or lower-fidelity capacity when their task-level opportunity cost is small.

This is the central application hypothesis for OSAHR in 6G: the network should not merely ask which path has the highest generic QoS; it should ask which **state transition best preserves the receiver's current goal**, given changing topology, load, reliability, and deadlines.

## Why OSAHR is a useful formalism

This problem is not naturally just a vector optimization problem because the admissible action space itself changes:

- mobility rewrites UE-to-gNB association;
- outages change which service transitions are enabled;
- capacity changes route-match availability;
- in-flight failures create rerouting structure;
- task arrivals create new competing semantic objects;
- future work can let policy/rule repertoires themselves adapt.

OSAHR turns each admissible `(task, current-gNB, candidate-edge)` relation into an explicit stochastic occurrence. Structural applicability and transition probability are therefore one coherent mechanism rather than separate simulation/controller layers.

Its event log also gives exact causal provenance: every completed task can be traced through generation, association state, selected path, outage/reroute events, and completion.

## Optimal implementation route

### Route 1 — Private Open RAN + industrial robotics (best first vertical)

Use OSAHR first as an **offline/shadow semantic-control twin** for a private 5G/Open-RAN robotic workcell. The reasons are practical:

1. task goals and deadlines are measurable;
2. the number of cells/robots is small enough for rapid calibration;
3. edge-compute placement matters directly;
4. controlled impairments can be introduced safely in a testbed;
5. recent O-RAN/6G robotics testbeds already expose the relevant edge-AI and semantic-communication problem.

Initial product: replay captured network/application traces, generate counterfactual policies, and report task-success distributions and causal failure paths.

### Route 2 — O-RAN Non-RT RIC / SMO policy laboratory

OSAHR should next become a policy-evaluation rApp/service attached to the Non-RT RIC/SMO domain. It should ingest topology, KPIs, mobility/load summaries, application task state, and network-digital-twin features, then execute counterfactual ensembles before issuing policy recommendations.

This is the safest location for the Python reference runtime because its value is scenario evaluation and policy synthesis, not sub-millisecond packet scheduling.

The output contract should be declarative: constraints, preferences, and candidate policy parameters rather than direct low-level PHY actions.

### Route 3 — Near-RT advisory / xApp coupling

After calibration and performance engineering, expose a reduced OSAHR state model to a Near-RT RIC xApp. OSAHR need not run the full twin at every RAN control interval. Instead:

1. Non-RT OSAHR learns/evaluates policy surfaces and hazard parameters.
2. A compiled reduced policy or lookup model is deployed to the xApp.
3. Near-RT telemetry returns to the OSAHR twin for recalibration and counterfactual audit.

This avoids trying to make a Python graph-rewrite engine replace optimized RAN control software.

### Route 4 — Federated high-fidelity digital twin

Couple OSAHR to a PHY/network simulator or radio digital twin:

    RF/propagation twin -> link/channel state
    packet/RAN simulator -> queues, scheduling, retransmission KPIs
    OSAHR -> task semantics, adaptive topology, stochastic causal control
    application/robot twin -> task success and mission state

OSAHR should consume calibrated stochastic summaries or external events rather than reimplement OFDM, MCS selection, HARQ, beamforming, ray tracing, or a complete protocol stack.

### Route 5 — Semantic representation and learned utility

Replace the synthetic scalar `utility` and `fidelity` with measurable quantities:

- task-success probability from an application model;
- semantic distortion from an encoder/decoder;
- Value/Urgency/Age of Information variants;
- knowledge-graph relevance;
- learned task embeddings;
- mission-state utility from a robotics planner.

This is where the current toy semantic term becomes a genuine semantic networking model.

### Route 6 — Hazard calibration and inference

Use OSAHR event-log likelihood to estimate rates from traces rather than hand-setting them.

Candidate parameters include:

- mobility transition rates;
- edge completion hazards;
- failure/recovery hazards;
- reroute latency distributions;
- task arrival regimes;
- policy temperature and semantic weighting.

A fitted model should be evaluated on held-out traces and with calibration diagnostics before any control recommendation is trusted.

### Route 7 — Decision-policy research

Once the environment is calibrated, compare control families on the *same OSAHR world model*:

- deterministic heuristics;
- contextual/networked bandits;
- constrained RL;
- MPC/stochastic optimization;
- rule/meta-rule adaptation;
- causal intervention policies.

The valuable object is then not a single routing algorithm, but a reproducible policy gym with explicit stochastic mechanisms and causally inspectable failures.

## Recommended engineering architecture

A production-oriented stack should be layered:

1. **Telemetry normalization** — O-RAN/3GPP/network/application adapters into canonical typed events.
2. **Twin state** — OSAHR typed hypergraph, open boundaries, sufficient statistics, parameter state.
3. **Calibration** — trace fitting, posterior/likelihood estimation, drift checks.
4. **Scenario engine** — exact/approximate ensembles, outages, mobility, policy counterfactuals.
5. **Semantic policy engine** — task utility/relevance/deadline models and candidate actions.
6. **Safety/constraints** — invariant checks and hard operating envelopes outside learned optimization.
7. **RIC integration** — non-RT recommendation first; near-RT reduced/compiled control later.
8. **Audit plane** — event provenance, state hashes, policy-version IDs, replayable scenario bundles.

## What not to build

Do not begin by implementing a full 6G radio stack in OSAHR.

Do not claim the current experiment predicts a real operator network. Its parameters are synthetic and intentionally chosen to create interpretable resource trade-offs.

Do not deploy the semantic controller directly to a live RAN before trace calibration, external simulator validation, safety constraints, and shadow-mode evaluation.

Do not treat generic semantic embeddings as utility. A useful semantic metric must be tied to an application outcome or decision objective.

## Validation ladder

1. **Synthetic mechanistic OSAHR model** — completed here.
2. **Trace-driven OSAHR** — replace handcrafted path/service parameters with recorded/simulated traces.
3. **Co-simulation with ns-3/Open-RAN stack** — OSAHR controls semantics/adaptation; lower layer supplies realistic network dynamics.
4. **Hardware-in-the-loop private network** — robotics/edge AI testbed.
5. **Shadow-mode RIC integration** — make recommendations without enforcement and compare against actual outcomes.
6. **Constrained closed-loop trial** — only after calibration and safety validation.

## Limitations

- No OFDM, MCS, HARQ, RLC/PDCP/MAC scheduling, beamforming, interference, channel coding, or RF propagation model.
- Exponential event hazards are abstractions, not fitted distributions.
- Reliability, fidelity, link quality, utility, and energy are synthetic model parameters.
- The semantic policy weights were selected manually, not trained on held-out data.
- Four UEs and two MEC nodes are intentionally small.
- The main treatment has only 30 trajectories per arm; semantic vs throughput remains statistically borderline under conservative independent-resampling inference.
- The severe condition has only 20 trajectories per arm and high variance.
- OSAHR's exactness applies to simulation of the declared hazard model; it does not imply the declared model is a calibrated representation of a real RAN.

## Reproducibility

Main experiment source: `semantic_6g_twin_experiment.py`.

Raw main data: `main_replicates.csv` (30 replicates x 3 policies).

Controls are under `controls/`.

`analyze_results.py` reconstructs confidence intervals and independent bootstrap comparisons and writes `statistical_results.json` and `stress_summary.csv`.

The OSAHR source tree used for the experiment passed all 36 package tests after the experiment work.

## Research references

Primary/official standards and industry sources:

- ITU, *IMT-2030: Technical requirements for the 6G future*, 17 March 2026.
- 3GPP, *The Network Digital Twin: Enabling Network Intelligence and Automation*, 27 April 2026.
- 3GPP, Release 20 and Release 21 program pages; Release 21 is the first normative 6G release.
- O-RAN ALLIANCE, *Digital Twin RAN Use Cases*.
- O-RAN ALLIANCE, *Digital Twin RAN: Key Enablers*.

Primary research used for design context:

- Calvanese Strinati et al., *Goal-Oriented and Semantic Communication in 6G AI-Native Networks: The 6G-GOALS Approach*, arXiv:2402.07573.
- Bilen & Akyildiz, *Semantic-Aware 6G Network Management through Knowledge-Defined Networking*, arXiv:2603.12695.
- *End-to-End O-RAN Testbed for Edge-AI-Enabled 5G/6G Connected Industrial Robotics*, arXiv:2603.13567.

