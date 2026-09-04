# Liquid-OSAHR Experiment 02A

**Closed-loop topology-coupled continuous neural dynamics with certified stochastic graph rewrites.**

Experiment 02A is the first implementation of the full Liquid-OSAHR computational object proposed after Experiment 01:

\[
H_t \longrightarrow \lambda(G_t,H_t) \longrightarrow \Delta G_t
\longrightarrow J(H_t,\Delta G_t) \longrightarrow H_{t^+}.
\]

The graph changes the continuous neural field, the field changes stochastic graph-event intensities, and accepted graph events feed back into the neural state. OSAHR remains authoritative for typed graph legality, DPO rewriting, event sampling, state hashing, replay, and counterfactual policy execution.

## Core implementation

- persistent liquid state on UE, gNB, and MEC entities;
- relation-specific graph coupling over `Association`, `Path`, and `Transit` relations;
- dynamically recomputed topology after handover, task routing, failure, and recovery;
- exact zero-time anchored flow, `Phi(h,0)=h`;
- learned event-specific jump maps;
- bounded neural hazard heads:

  \[
  \lambda_k = \epsilon +(\lambda_k^{max}-\epsilon)\sigma(z_k),
  \]

  which certify `lambda_k <= lambda_k_max` globally;
- OSAHR exact rejection thinning using those declared global bounds;
- pure candidate-time neural evaluation: rejected thinning proposals do not advance neural state;
- graph-epoch/time caching so one continuous evaluation is shared across all rewrite occurrences at a candidate time;
- augmented state hashing and snapshot/replay including liquid state;
- a matched graph-GRU baseline;
- CfC no-jump and frozen-open-loop ablations;
- analytically soluble closed-loop oracle teacher;
- scenario-clustered counterfactual bootstrap analysis.

## Experiment arms

Five field models are compared:

1. `oracle`: exact analytic topology-coupled teacher;
2. `cfc_closed`: graph-coupled CfC with learned event jumps;
3. `cfc_nojump`: same topology-coupled CfC without event jumps;
4. `cfc_openloop`: initial-topology CfC with no graph/event feedback except OSAHR legality masking;
5. `gru_closed`: near-parameter-matched topology-coupled graph GRU with event jumps.

Each is tested under `throughput` and `semantic` policies in three regimes:

- in-distribution (`id`);
- high mobility;
- high stress/congestion.

The release counterfactual dataset contains 360 runs:

\[
3\;regimes \times 6\;scenarios \times 5\;models \times 2\;policies \times 2\;replicates.
\]

The telemetry scenario is the independent statistical unit. Stochastic replicates are averaged before bootstrap resampling.

## Main result

Experiment 02A validates that the closed-loop neural/structural process can be executed with exact conditional stochastic semantics, but it also falsifies the naive assumption that **more closed-loop feedback automatically yields a better digital twin**.

The learned `cfc_closed` model is executable, bounded, replayable, and topology-sensitive, yet no-jump/open-loop ablations sometimes recover oracle counterfactual effects more accurately. The learned jump map can amplify hazard-model misspecification.

That yields the central design rule:

> A closed-loop neural digital twin must validate **intervention-effect fidelity**, not merely event/hazard prediction or one-step state accuracy.

See `EXPERIMENT_REPORT.md` for the complete methods, results, limitations, and Experiment 02B route.

## Reproduce tests

```bash
python -m pytest -q
```

The project bundles the OSAHR 0.2 reference runtime under `vendor/osahr` for exact reproduction.

## Key scripts

```text
scripts/train_one.py
scripts/evaluate_ood.py
scripts/run_counterfactual_chunk.py
scripts/run_openloop_batch.py
scripts/analyze_counterfactual_full.py
scripts/analyze_feedback_ablation.py
```

## Scientific scope

This is a synthetic 6G/network-digital-twin research experiment. It does not implement 3GPP PHY/MAC/RLC/PDCP, RF propagation, beamforming, HARQ, or standards-complete RAN behavior. The optimal route is federation with ns-3/srsRAN/O-RAN/RF-twin telemetry rather than replacing those simulators.
