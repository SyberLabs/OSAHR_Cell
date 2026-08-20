# Experiment 02B Protocol

## Primary objective

Evaluate whether a bounded liquid-neural residual over a mechanistic RAN prior improves counterfactual policy-effect fidelity in an OSAHR network digital twin.

## Frozen hierarchy

1. Train residual on synthetic oracle hazards.
2. Select predictive alpha on validation hazard NMAE.
3. Select intervention alpha on a disjoint calibration set using goal-utility policy-effect MAE plus a small predictive penalty.
4. Audit calibration stability by leave-one-scenario-out and stratified bootstrap.
5. Freeze model, trust grid, objective, calibration set and confirmatory seed protocol.
6. Evaluate a new untouched root seed across ID/high mobility/high stress/weak channel.

## Independent unit

Physical scenario. Stochastic replicates are averaged inside scenario.

## Confirmatory primary endpoint

Absolute error in the semantic-vs-throughput goal-utility effect relative to oracle.

## Secondary endpoints

- goal-utility level MAE;
- critical-success effect/level error;
- mean-latency effect/level error;
- event/hazard OOD NMAE and log-RMSE;
- sign agreement.

## Confirmatory design

4 regimes x 5 scenarios x 2 stochastic replicates x 5 model/trust arms x 2 policies = 400 runs.

## Calibration design

3 regimes x 6 scenarios with alpha grid {0,.25,.5,.75,1}; one stochastic replicate per arm at 2 s horizon; separate root seed.

## Reporting rule

No claim of real-network efficacy is permitted from this experiment. All empirical effect magnitudes refer only to the declared synthetic scenario generator.
