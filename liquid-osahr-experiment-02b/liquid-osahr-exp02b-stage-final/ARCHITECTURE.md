# Liquid-OSAHR 02B Architecture

## 1. Augmented state

The authoritative stochastic state is the OSAHR graph/runtime state plus the continuous residual state and deterministic physical realization. OSAHR remains authoritative about type legality, DPO applicability, boundaries, event timing, event sourcing and replay.

## 2. Layers

1. **RAN physical surrogate**: deterministic-in-seed continuous mobility, 38.901-informed path loss, shadow/fading, inter-cell SINR, KPM proxies.
2. **Mechanistic hazard prior**: deliberately incomplete engineering functions for service, failure/recovery and handover.
3. **Residual CfC**: graph/topology-conditioned continuous hidden state and bounded logit correction.
4. **Trust layer**: alpha controls the residual correction; alpha=0 bypasses the neural numerical path exactly.
5. **OSAHR runtime**: exact typed occurrence set + bounded thinning + structural rewrite.
6. **Counterfactual evaluator**: common-random-number paired policy rollouts and scenario-level inference.

## 3. Bounded residual semantics

For each head with floor eps and global bound B:

```text
q = clip((lambda_mech-eps)/(B-eps))
z = logit(q)
r = L*tanh(neural_residual)
lambda = eps + (B-eps)*sigmoid(z + alpha*r)
```

For alpha=0, runtime code returns `lambda_mech` directly. This is stronger than algebraic equivalence: it avoids precision-induced stochastic clock perturbation.

## 4. Purity and caching

Candidate-time field evaluation is observational. Neural flow is cached by `(candidate_time, graph_epoch, anchor_time)` so all rewrite occurrences at the same candidate time share one liquid evaluation. Rejected thinning candidates never commit the liquid anchor. Accepted events commit the pre-event state at exactly the event time, then OSAHR changes topology.

## 5. Common random numbers

Physical seeds and stochastic runtime seeds depend on scenario/replicate, not candidate model/policy. This is tested. Divergent models can of course diverge pathwise after selecting different events; CRN is a variance-reduction coupling, not an assertion of identical event sequences.

## 6. Intervention calibration

Calibration is a separate data split. It minimizes oracle policy-effect error, not trajectory MSE. The final protocol uses six scenarios each from ID/high-mobility/high-stress and freezes alpha before the confirmatory root seed is analyzed.

## 7. External telemetry

`telemetry.py` defines a stable source-neutral record plus srsRAN and 5G-LENA adapters. External source semantics and units remain explicit; missing fields are not fabricated.

## 8. Exactness boundary

The stochastic process is exact relative to its declared bounded hazard functions. Fidelity of those hazards to real NR is a model-validation question. The synthetic RAN layer must not be described as standards-conformant PHY/MAC behavior.
