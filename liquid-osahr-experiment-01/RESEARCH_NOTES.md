# Research Notes and Primary Sources

## Liquid Time-Constant Networks

Hasani et al., **Liquid Time-constant Networks**, arXiv:2006.04439.
https://arxiv.org/abs/2006.04439

The paper introduces time-continuous recurrent networks whose effective time constants vary with hidden state/input, with outputs computed using numerical differential-equation solvers. It also develops boundedness/stability and expressivity results. Experiment 01 includes a dense semi-implicit LTC baseline but treats it as resource-capped rather than matched-capacity.

## Closed-form Continuous-time (CfC) Networks

Hasani et al., **Closed-form continuous-time neural networks**, Nature Machine Intelligence (2022).
https://www.nature.com/articles/s42256-022-00556-7

CfC approximates liquid dynamics in a closed-form recurrent update, making elapsed time explicit without requiring a general ODE solve at every recurrent step. This is the primary liquid model in Experiment 01.

## Official Neural Circuit Policies implementation

Mathias Lechner et al., `ncps` reference repository:
https://github.com/mlech26l/ncps

The repository provides PyTorch/TensorFlow CfC and LTC implementations under Apache-2.0. The self-contained cells in this experiment were independently implemented from the published/reference formulations; see `THIRD_PARTY_NOTICES.md`.

## Liquid Graph Time-Constant Networks

Marino, Pacchierotti, Robuffo Giordano, **Liquid-Graph Time-Constant Network for Multi-Agent Systems Control**, arXiv:2404.13982.
https://arxiv.org/abs/2404.13982

LGTC is directly relevant to later Liquid-OSAHR work because it couples liquid continuous-time dynamics to graph communication and studies stability/closed-form variants. OSAHR's next research step is different: the graph topology itself is a stochastic typed rewrite process rather than merely an input communication graph.

## Neural Temporal Point Processes

Shchur et al., **Neural Temporal Point Processes: A Review**, arXiv:2104.03528.
https://arxiv.org/abs/2104.03528

Experiment 01 treats the liquid recurrent model as a marked temporal-point-process intensity estimator. It evaluates likelihood and time-rescaling diagnostics rather than only next-event classification or rate regression.

## Semantic scope

The experiment intentionally uses a piecewise-constant neural intensity between observed telemetry timestamps. This makes both the likelihood compensator and OSAHR stochastic schedule explicit and exactly computable. It should not be confused with a certified continuously varying neural intensity.

## Wireless / 6G relevance

### Robust continuous-time beam tracking with LNNs

Zhu et al., **Robust Continuous-Time Beam Tracking with Liquid Neural Network**, arXiv:2405.00365 / IEEE GLOBECOM 2024.
https://arxiv.org/abs/2405.00365

This work applies liquid networks to a mobility-sensitive mmWave beam-tracking problem and motivates using continuous-time inductive structure for rapidly evolving wireless state. Experiment 01 does not reproduce its beamforming task; it uses the paper as application-level evidence that liquid models are being investigated for dynamic wireless inference.

### Telecom energy estimation with Neural Circuit Policies

Ickin et al., **Towards Green AI-Native Networks: Evaluation of Neural Circuit Policy for Estimating Energy Consumption of Base Stations**, arXiv:2504.02781.
https://arxiv.org/abs/2504.02781

This provides a second telecom application class and is also a useful warning against universal robustness claims: the value of liquid/NCP architectures must be established per task rather than assumed.

### 3GPP Network Digital Twin

3GPP, **The Network Digital Twin: Enabling Network Intelligence and Automation** and TS 28.561.
https://www.3gpp.org/technologies/digital-twin1
https://www.3gpp.org/dynareport/28561.htm

Release-19 NDT work formalizes network-digital-twin management and motivates evaluating network configuration/policy changes away from the live system. Liquid-OSAHR is positioned at this shadow/counterfactual layer rather than as a replacement for a standards-compliant radio simulator.

### O-RAN digital twins and AI experimentation

O-RAN Alliance digital-twin research/platform material:
https://www.o-ran.org/press-releases

The O-RAN ecosystem is explicitly using digital twins for AI/Open-RAN research and network optimization. This is the natural future deployment context for an OSAHR causal/control twin coupled to measured or high-fidelity RAN telemetry.

### IMT-2030 and goal-oriented communication

ITU, **IMT-2030: Technical requirements for the 6G future** (2026):
https://www.itu.int/hub/2026/03/imt-2030-technical-requirements-for-the-6g-future/

Calvanese Strinati et al., **Goal-Oriented and Semantic Communication in 6G AI-Native Networks: The 6G-GOALS Approach**, arXiv:2402.07573:
https://arxiv.org/abs/2402.07573

IMT-2030 includes AI and Communication as a 6G usage scenario. 6G-GOALS provides direct architectural motivation for task/value-aware communication and O-RAN-based semantic control. The semantic route policy in Experiment 01 is intentionally a minimal stochastic-control abstraction of this broader direction, not a standards implementation.
