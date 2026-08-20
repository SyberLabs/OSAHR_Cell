# Liquid-OSAHR Architecture

## 1. Hybrid state

The conceptual target for Liquid-OSAHR is

\[
X_t=(G_t,H_t,B_t,\mathcal R_t,\Theta_t,Z_t,t),
\]

where `G` is the typed hypergraph and `H` is learned continuous-time neural state.

Experiment 01 implements a deliberately restricted, auditable version. Neural state evolves only on the observation history of an external link trace, producing an exogenous schedule

\[
\hat\Lambda = \{(t_i,\hat\lambda_i)\}_{i=1}^{L}.
\]

OSAHR then evolves conditionally on that schedule.

## 2. Neural update

For CfC,

\[
h_i=\operatorname{CfC}(x_i,h_{i-1},\Delta t_i),
\qquad
\hat\lambda_i=\operatorname{softplus}(W h_i+b)+\epsilon.
\]

The gated CfC implementation follows the default fully-connected formulation exposed by the Neural Circuit Policies reference project.

## 3. Stochastic observation law

For `t in [t_i,t_{i+1})`, Experiment 01 declares

\[
\lambda_k(t)=\hat\lambda_{ik}.
\]

Therefore the integrated intensity is analytic:

\[
\int_{t_i}^{t_{i+1}}\lambda_k(t)dt
=\hat\lambda_{ik}\Delta_i.
\]

The log likelihood is consequently

\[
\ell=\sum_{e_j}\log\lambda_{m_j}(t_j)-
\int_0^T\sum_k\lambda_k(t)dt,
\]

which reduces interval-wise to the training expression in `training.py`.

## 4. Open-system boundary

Every neural hazard schedule is external to the graph process. At telemetry timestamps, OSAHR receives typed deterministic boundary events. The boundary adapter updates an `EdgeNode`'s:

```text
service_rate
down_hazard
up_hazard
```

atomically.

This keeps the neural model outside OSAHR's authoritative mutation path while still making the learned physical law part of the runtime's event sequence.

## 5. Graph dynamics

Within an interval with fixed learned hazard vector, enabled rewrite occurrences form the stochastic transition channels. Examples:

```text
EdgeNode(available=True) --fail--> EdgeNode(available=False)
EdgeNode(available=False) --recover--> EdgeNode(available=True)
Transit(...) --complete--> consumed Task + decremented load
Queued(...) --route--> Transit(...)
```

The next-reaction scheduler handles the piecewise-constant CTMC exactly. When a deterministic telemetry update arrives, it preempts/reschedules affected channels according to OSAHR semantics.

## 6. Why this is not yet the full neural PDMP

A full Liquid-OSAHR process would have

\[
\dot H=F_{G_t}(H,u,t)
\]

between graph jumps and

\[
(G,H)\mapsto(T_e(G),J_e(H))
\]

at a jump, with intensity

\[
\lambda_e=\lambda_e(G,H,t).
\]

Its generator would combine continuous flow and graph jumps:

\[
\mathcal Lf=\nabla_Hf\cdot F_G+
\sum_e\lambda_e(G,H,t)
[f(T_eG,J_eH)-f(G,H)].
\]

Experiment 01 does **not** claim to implement this closed loop. It establishes the identification, hazard-interface, likelihood, and counterfactual-audit infrastructure needed before attempting it.

## 7. Why not unrestricted neural thinning yet

If a neural continuous-time function directly supplies `lambda(t)` at every real-valued time, exact thinning requires a valid intensity upper bound over each proposal horizon. A generic neural network does not automatically provide a certified bound.

Experiment 01 avoids this semantic ambiguity by freezing neural hazards between actual telemetry observations. This gives exact stochastic simulation of the declared approximation.

Future routes include interval bound propagation, certified Lipschitz envelopes, analytically integrable CfC hazard heads, or error-controlled numerical inversion.

## 8. Determinism and replay

The release records deterministic dataset/model seeds and uses OSAHR's stable state hashing/event semantics. Common random numbers use model-independent root seeds at the scenario/replicate level. One learned-hazard OSAHR trajectory runs with incremental matching continuously checked against the exhaustive reference matcher.

## 9. Failure modes deliberately surfaced

- low point-process NLL can coexist with downstream policy-effect error;
- time-rescaling diagnostics can reject local calibration even when aggregate event counts are close;
- full dense LTC backpropagation is computationally expensive relative to CfC on this CPU experiment;
- stochastic paths diverge rapidly after small hazard changes, so raw pathwise equality is not a suitable twin-fidelity metric;
- stochastic replicates on the same telemetry trace are clustered, not treated as independent samples.
