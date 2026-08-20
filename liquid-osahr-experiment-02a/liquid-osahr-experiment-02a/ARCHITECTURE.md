# Liquid-OSAHR 02A Architecture

## 1. Augmented state

The authoritative state is

\[
X_t=(G_t,H_t,B_t,\mathcal R_t,\Theta_t,Z_t,t,n).
\]

`G_t` is the typed OSAHR hypergraph. `H_t` is entity-scoped continuous hidden state. All other OSAHR state remains unchanged from the 0.2 kernel.

## 2. Continuous segment

Between accepted graph events, topology is fixed. A persistent entity state evolves according to a topology-conditioned segment map

\[
H(t+\Delta)=\Phi_{G_t}(H_t,X(G_t),\Delta).
\]

For the CfC field,

\[
C = \operatorname{CfC}(X,M_G(H),H,\Delta),
\]

then an external anchor blend enforces exact continuity at zero elapsed time:

\[
H(t+\Delta)=H_t+\left(1-e^{-\kappa\Delta}\right)(C-H_t).
\]

Thus `Phi(H,0)=H` exactly even if the internal CfC candidate does not itself equal the anchor at zero time.

## 3. Typed relation coupling

Persistent liquid entities are UEs, gNBs, and MEC nodes. Task vertices remain explicit in OSAHR but do not own continuous state in 02A.

Three relation channels are projected from the live typed hypergraph:

- `Association`;
- `Path`;
- `Transit`.

Each has its own hidden-state linear map. Receiver-normalized relation-specific messages are aggregated before the recurrent update.

Consequently, a handover changes the neural vector field immediately because it changes the `Association` adjacency; routing/completion changes `Transit`; failure/recovery changes structural features and legal hazard masks.

## 4. Jump map

At accepted rewrite event `e`:

1. evaluate the continuous field at the event time using the **pre-event** graph;
2. commit the OSAHR structural rewrite;
3. compute affected persistent entities from typed match roles;
4. apply

\[
H^+ = H^- + A_e\odot 0.35\,\sigma(g(H^-,X^+))\odot\tanh(E_e+W X^+),
\]

where `A_e` is the affected-entity mask;
5. set the new liquid anchor to `(time, H+)`;
6. rebuild stochastic occurrences against the committed graph.

Unaffected entities are exactly unchanged by the jump itself.

## 5. Certified neural intensities

Four neural base heads are used:

- service;
- edge failure;
- edge recovery;
- handover.

Every head is globally bounded:

\[
\lambda_k(H,G)=\epsilon+(B_k-\epsilon)\sigma(z_k(H,G)).
\]

Therefore

\[
0<\lambda_k\le B_k
\]

for all finite neural states and graph features.

Declared bounds are:

```text
service  <= 5.00
failure  <= 0.22
recovery <= 0.85
handover <= 0.24
```

Completion multiplies the service base intensity by reliability, link quality, payload, and congestion factors whose combined multiplier is constrained to <= 1, so the base service bound remains valid.

## 6. Exact stochastic execution

Experiment 02A uses OSAHR's rejection-thinning scheduler. For a stochastic occurrence with actual intensity `lambda_e(t)` and certified bound `B_e`, candidates are generated from the dominating bounded process and accepted according to the actual/bound ratio.

Candidate neural evaluation is **pure**. Rejected candidates never move the liquid anchor. Only accepted structural events commit continuous state.

This is the correct state semantics for a piecewise-deterministic Markov process.

## 7. Evaluation cache

A single scheduler candidate time can require hazards for many graph matches. Naively evaluating the neural flow independently per occurrence changes no semantics but is needlessly expensive.

`NeuralLiquidField` caches by

```text
(candidate_time, graph_epoch, anchor_time)
```

so every occurrence at that candidate time reads the same already-computed liquid state/rate tensor. Cache invalidation occurs on committed events and restore.

## 8. Oracle field

The oracle teacher uses an analytically soluble topology-dependent flow:

\[
\dot H=-\alpha_{type}(H-\mu(G,S)),
\]

so

\[
H(t+\Delta)=\mu+(H_t-\mu)e^{-\alpha\Delta}.
\]

`mu` depends on live graph properties such as association/path degree, queue/inflight pressure, MEC load and availability, path quality, plus scenario mobility/stress/channel/demand.

Events also apply explicit mechanistic jumps. This gives a ground-truth hybrid process for which continuous state and hazard targets are known exactly.

## 9. Counterfactual semantics

Policies alter only explicit routing hazards. They do not change the physical neural/oracle field definition.

The primary estimand is the scenario-level intervention effect

\[
\Delta_s = E[Y|policy=semantic,s]-E[Y|policy=throughput,s].
\]

A learned twin is evaluated by

\[
|\hat\Delta_s-\Delta_s^{oracle}|,
\]

not merely by predictive error.

## 10. Exactness boundary

Exact relative to the declared model:

- typed matching and DPO rewriting;
- structural legality masks;
- global neural hazard bounds;
- rejection thinning conditional on the learned field;
- deterministic state hashing and replay;
- analytic oracle flow;
- neural anchor/jump lifecycle;
- scenario-paired stochastic seed derivation.

Model approximations:

- synthetic teacher rather than measured RAN physics;
- finite-dimensional neural approximation to teacher dynamics;
- small graph and task model;
- learned jump map is empirical and not physics-constrained;
- no full RF/PHY co-simulation.
