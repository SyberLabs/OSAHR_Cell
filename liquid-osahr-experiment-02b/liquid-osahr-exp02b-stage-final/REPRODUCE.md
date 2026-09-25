# Reproducing Liquid-OSAHR Experiment 02B

## 1. Environment

The frozen development environment is recorded in `requirements-lock-environment.txt`.
The package itself declares only broad runtime lower bounds in `pyproject.toml`.

## 2. Source-tree environment

For source-tree scripts without an editable install, export the package roots first:

```bash
export PYTHONPATH=".:../.."
```

Alternatively install the project into an isolated environment with `python -m pip install -e .`.

## 3. Regression suite

```bash
python -m pytest -q
python -m compileall -q liquid_osahr02b scripts tests
```

## 4. External telemetry normalization smoke tests

```bash
python scripts/ingest_telemetry.py srsran-jsonl examples/srsran_kpm_sample.jsonl
python scripts/ingest_telemetry.py 5glena-csv examples/5glena_trace_sample.csv
```

These commands validate the adapter boundary only. The included examples are synthetic fixtures, not captured live-network data.

## 5. Rebuild the standards-informed oracle corpus

```bash
python scripts/generate_ran_dataset_02b.py \
  --output artifacts/ran_dataset_rebuilt.pkl \
  --seed 26021802 --horizon 3 --period 0.3 \
  --train 14 --val 5 --test 5
```

The release also contains the exact frozen corpus used for the reported model checkpoint as `artifacts/ran_dataset.pkl`.

## 6. Retrain the bounded graph-CfC residual

```bash
python scripts/train_residual_02b.py \
  --dataset artifacts/ran_dataset.pkl \
  --checkpoint artifacts/residual_cfc_rebuilt.pt \
  --summary artifacts/training_summary_rebuilt.json
```

Training is seeded but bitwise equality across different PyTorch/platform builds is not asserted. The frozen checkpoint used for the reported results is `artifacts/residual_cfc.pt`.

## 7. Frozen intervention calibration

The final calibration protocol uses 6 independent scenarios in each of ID, high-mobility and high-stress regimes. The release stores the frozen aggregate in `artifacts/intervention_calibration_multi.json` and the exact zero-trust recomputations in `artifacts/cal_mechanistic_exact_*.csv`.

`python scripts/extend_calibration_02b.py ...` and `python scripts/recompute_mechanistic_calibration.py ...` expose the checkpointed components used to assemble that calibration study. They are deliberately row/chunk oriented so exact-thinning outliers do not destroy already completed arms.

## 8. Untouched confirmatory holdout

The frozen confirmatory root seed is `920218`. After calibration was frozen, the confirmatory runner evaluated 5 independent scenarios in each of:

- ID;
- high mobility;
- high stress;
- weak channel (never used for intervention trust calibration).

Use `scripts/run_confirmatory_02b.py` for checkpointed execution. The authoritative assembled table is `artifacts/confirmatory_release.csv`.

Rebuild analysis with:

```bash
python scripts/analyze_confirmatory_02b.py
```

Inference treats the physical scenario as the independent unit. Stochastic replicates are averaged inside each scenario before bootstrap resampling.

## 9. Reports

```bash
python scripts/build_reports_02b.py
```

This rebuilds the research-facing summaries from the frozen artifacts.

## 10. Exactness contract

“Exact” in this repository means exact conditional on the declared hybrid model: typed DPO applicability, bounded event-rate contract, rejection thinning, deterministic seed-conditioned physical field, pure candidate-time liquid queries, and deterministic event/replay semantics. It does **not** claim that the shipped radio surrogate is an exact NR PHY/MAC implementation or that its synthetic oracle is a calibrated live 6G network.
