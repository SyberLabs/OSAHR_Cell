# Liquid-OSAHR Experiment 02B

Intervention-calibrated, standards-informed RAN digital-twin experiment built on OSAHR.

## Core architecture

`RAN mechanism -> bounded CfC residual -> certified event hazards -> typed OSAHR rewrites -> counterfactual policy evaluation`

The project includes a 3GPP TR 38.901-informed RAN surrogate, exact OSAHR thinning, mechanistic and residual hazard fields, trust calibration, srsRAN/5G-LENA telemetry adapters, synthetic training data, frozen calibration artifacts, an untouched 400-run confirmatory study, and full tests.

## Important result

Full neural trust gives the best local hazard prediction across all tested regimes, but not the best policy-effect fidelity. The final 18-scenario intervention calibration selects alpha=0, while the untouched holdout shows the best alpha is query/regime dependent. See `EXPERIMENT_REPORT.md`.

## Run tests

```bash
python -m pytest -q
```

## Normalize external telemetry

```bash
python scripts/ingest_telemetry.py srsran-jsonl examples/srsran_kpm_sample.jsonl
python scripts/ingest_telemetry.py srsran-native-jsonl examples/srsran_native_scheduler_sample.jsonl --period-s 0.5
python scripts/ingest_telemetry.py 5glena-csv examples/5glena_trace_sample.csv
```

See `TELEMETRY_CONTRACT.md` for the source boundary and unit/provenance requirements.

## Key artifacts

- `artifacts/residual_cfc.pt`: trained residual checkpoint
- `artifacts/training_summary.json`: predictive calibration
- `artifacts/intervention_calibration_multi.json`: frozen 18-scenario intervention calibration
- `artifacts/confirmatory_release.csv`: 400 untouched confirmatory trajectories
- `artifacts/confirmatory_summary.csv`: compact results
- `artifacts/ood_hazard_evaluation.json`: factual OOD hazard audit
- `artifacts/predictive_vs_counterfactual.json`: prediction/intervention mismatch audit

## Scope warning

The shipped radio layer is standards-informed but is not a full NR protocol simulator. The code deliberately includes adapters so future experiments can replace it with 5G-LENA, srsRAN/O-RAN, or measured telemetry without changing OSAHR's structural semantics.
