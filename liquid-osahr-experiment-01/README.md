# Liquid-OSAHR Experiment 01

**Hybrid continuous-time neural hazard identification + exact stochastic graph rewriting for a 6G shadow network twin.**

This repository implements the first Liquid-OSAHR experiment. A mechanistic synthetic wireless-link teacher generates irregular telemetry and marked continuous-time events (`service`, `down`, `up`). Continuous-time and recurrent models identify a conditional event law. Their predicted hazards are then injected as exogenous, piecewise-constant intensity schedules into the OSAHR 0.2 typed hypergraph rewrite runtime.

The central semantic split is intentional:

- **neural model:** estimates how event intensities vary from irregular observations;
- **OSAHR:** determines which typed structural events are legal, samples the next graph event exactly under the declared piecewise-constant intensities, commits an atomic graph rewrite, and records deterministic provenance;
- **policy layer:** changes route-selection hazards but not structural legality.

This experiment does **not** claim that the synthetic teacher is a calibrated 6G radio channel. It is an identification/control testbed designed so ground-truth integrated intensities are known and model error can be measured before counterfactual simulation.

## Audited release configuration

- Python 3.13.5
- PyTorch 2.10.0 CPU
- NumPy 2.3.5
- SciPy 1.17.0
- pandas 2.2.3
- OSAHR 0.2 source vendored under `vendor/osahr`
- dataset seed: `20260817`
- control-twin root seed: `80219`

See `requirements-lock-environment.txt` for exact executed versions.

## Model tiers

### Equal-hidden-width main comparison

All receive the same 11 telemetry features. Recurrent baselines receive elapsed time explicitly.

- `cfc`: gated Closed-form Continuous-time (CfC) cell, hidden width 32
- `gru_dt`: GRU with `log1p(delta_t)`, hidden width 32
- `lstm_dt`: LSTM with `log1p(delta_t)`, hidden width 32
- `mlp_dt`: memoryless MLP with current telemetry + `log1p(delta_t)`, width 32
- `constant`: analytic homogeneous marked-Poisson baseline

### Parameter-budget sensitivity

- `gru_param_matched`: GRU with `log1p(delta_t)`, hidden width 54, 11,181 parameters versus CfC's 11,235. This tests whether the CfC result is explained simply by its larger parameter count.

### Resource-capped secondary comparison

- `ltc_capped`: fully connected semi-implicit Liquid Time-Constant cell, hidden width 12, 24 training traces, 10 epochs.

The dense LTC result is **not** an equal-compute or parameter-matched comparison. It is included to exercise the solver-based liquid path while keeping the release computation bounded. CfC is the primary liquid model in Experiment 01 precisely because it avoids repeatedly unfolding an ODE solver.

## Point-process objective

At each irregular telemetry observation `i`, the neural network outputs nonnegative mark-specific intensities `lambda[i,k]`. Intensities are declared constant until the next telemetry observation. For interval duration `Delta_i` and observed mark count `n[i,k]`, training minimizes

```text
sum_i sum_k [ lambda[i,k] * Delta_i - n[i,k] * log(lambda[i,k]) ]
```

(up to event-count constants independent of model parameters).

Because the bridge uses exactly the same piecewise-constant interpretation, the OSAHR next-reaction process is exact **conditional on the predicted hazard schedule**. The learned schedule remains an approximation to the teacher's continuously evolving latent physical process.

## Reproduce

Run project tests:

```bash
python -m pytest -q
```

Run the original OSAHR 0.2 tests against the vendored runtime if the upstream test directory is available:

```bash
PYTHONPATH="$PWD/vendor" python -m pytest -q /path/to/osahr/tests
```

Re-train/evaluate identification models:

```bash
python scripts/run_identification_release.py
```

Run the OSAHR paired bridge study:

```bash
python scripts/run_osahr_release.py
python scripts/run_osahr_release_extension.py
```

Then combine/analyze with the release analysis scripts:

```bash
python scripts/combine_and_analyze_osahr.py
python scripts/analyze_identification_paired.py
```

## Repository map

- `liquid_osahr/liquid.py` - CfC and dense LTC cells
- `liquid_osahr/teacher.py` - mechanistic hidden-state synthetic wireless teacher
- `liquid_osahr/data.py` - deterministic splits, normalization, irregular batching
- `liquid_osahr/models.py` - CfC/LTC/GRU/LSTM/MLP/constant marked-hazard models
- `liquid_osahr/training.py` - exact piecewise-constant point-process NLL
- `liquid_osahr/metrics.py` - held-out likelihood, rate error, count calibration, time-rescaling tests
- `liquid_osahr/osahr_bridge.py` - 6G hypergraph twin + external neural-hazard updates
- `scripts/` - release orchestration and analysis
- `artifacts/` - checkpoints, raw results, generated trace bundle, logs
- `vendor/osahr/` - OSAHR 0.2 runtime

## Read next

- `EXPERIMENT_SPEC.md` - hypotheses and statistical design
- `ARCHITECTURE.md` - hybrid semantics and exactness boundary
- `RESEARCH_NOTES.md` - primary-source grounding
- `EXPERIMENT_REPORT.md` - audited empirical results and limitations
- `THIRD_PARTY_NOTICES.md` - licensing/implementation provenance
