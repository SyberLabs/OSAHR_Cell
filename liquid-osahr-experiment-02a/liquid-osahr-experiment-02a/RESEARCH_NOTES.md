# Research Notes — Liquid-OSAHR Experiment 02A

## Continuous-time liquid models

**Hasani et al., Closed-form Continuous-time Neural Models / CfC**  
https://arxiv.org/abs/2106.13898

CfC motivates the primary recurrent architecture: continuous elapsed time enters the state update explicitly without requiring a general numerical ODE solver at every query.

**Hasani et al., Liquid Time-constant Networks**  
https://arxiv.org/abs/2006.04439

Provides the liquid continuous-time foundation and motivates state/input-dependent temporal response rather than a fixed discrete recurrence.

## Liquid dynamics on graphs

**Marino, Pacchierotti, Robuffo Giordano, Liquid-Graph Time-Constant Network for Multi-Agent Systems Control**  
https://arxiv.org/abs/2404.13982

Shows that liquid continuous dynamics and graph-mediated communication can be integrated, including changing communication range/delay. Experiment 02A goes beyond a fixed communication graph by letting typed stochastic graph rewrites change the coupling structure itself.

**Poli et al., Graph Neural Ordinary Differential Equations**  
https://arxiv.org/abs/1911.07532

Provides broader background for continuous-depth/dynamical graph models.

## Hybrid continuous/jump graph systems

**Sevak, Jadhav, Bui, Physics-Informed Graph Neural Jump ODEs for Cascading Failure Prediction in Power Grids (2026)**  
https://arxiv.org/abs/2603.20838

Independent recent evidence for separating continuous graph dynamics from abrupt discrete topology-change events. OSAHR differs by giving jumps typed graph-rewrite semantics and stochastic event clocks rather than treating jumps only as a neural prediction architecture.

## PDMP and exact thinning

**Azaïs et al., Piecewise deterministic Markov process — recent results**  
https://arxiv.org/abs/1309.6061

The mathematical class most closely matching Liquid-OSAHR 02A: deterministic continuous evolution between random jumps.

**Lemaire, Thieullen, Thomas, Exact simulation of the jump times of a class of Piecewise Deterministic Markov Processes**  
https://arxiv.org/abs/1602.07871

Explicitly studies exact jump-time simulation through thinning under jump-rate bounds. This motivates the central engineering requirement that neural intensities expose certified envelopes rather than heuristic maxima.

## Neural temporal point processes

**Shchur et al., Neural Temporal Point Processes: A Review**  
https://arxiv.org/abs/2104.03528

Background for learned continuous-time event intensities and likelihood-based event modeling.

## 6G and semantic communication

**ITU IMT-2030 programme**  
https://www.itu.int/en/ITU-R/study-groups/rsg5/rwp5d/imt-2030/pages/default.aspx

As of February/March 2026, IMT-2030 technical performance requirements explicitly include AI and Communication (AIAC), ubiquitous intelligence, and security/resilience among core scenarios/principles.

**3GPP TS 28.561 — Management aspects of Network Digital Twins**  
https://www.3gpp.org/dynareport/28561.htm

Release-19 Network Digital Twin management work is the closest standards-facing location for OSAHR's shadow-policy-evaluation role.

**3GPP, The Network Digital Twin: Enabling Network Intelligence and Automation (2026)**  
https://www.3gpp.org/technologies/digital-twin1

Describes NDT use for network intelligence/automation and validating configuration/policy changes before live deployment.

**O-RAN ALLIANCE Digital Twin platform**  
https://www.o-ran.org/press-releases

The evolved O-RAN Digital Twin platform is intended to accelerate research at the intersection of AI, Open RAN, and network optimization. OSAHR should federate with this ecosystem rather than replace packet/RF simulators.

**Calvanese Strinati et al., Goal-Oriented and Semantic Communication in 6G AI-Native Networks: The 6G-GOALS Approach**  
https://arxiv.org/abs/2402.07573

Motivates task/value-aware communication and the integration of communication, computation, control, and intelligence. The Experiment 02A `semantic` routing arm is a deliberately simplified mechanistic proxy for this class of goal-aware control.

## Design inference

The literature suggests three layers that should remain distinct:

1. continuous learned state estimation / hazard modeling;
2. formal structural event semantics and stochastic simulation;
3. policy/counterfactual evaluation.

The Experiment 02A results reinforce this separation empirically: a model can predict hazards well yet distort intervention effects after being embedded in a closed-loop twin.
