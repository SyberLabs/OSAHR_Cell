# Liquid-OSAHR Experiment 04

Same-horizon, multi-query residual-trust calibration, then a new untouched confirmatory seed.

This is a descendant of Experiments 02B and 03. It does not retrain the residual CfC and does not overwrite prior artifacts.

## Frozen seeds

- calibration `440318`
- confirmatory `880419` (declared before execution; scored only after freeze)

Horizon is 3.0 s on both splits. Estimands: goal utility, critical success, mean latency.

## Run

```bash
py -3 scripts/run_experiment_04.py --stage all
```

Stages: `calibrate`, `freeze`, `confirm`, `analyze`, `all`.

Confirmatory will refuse to start if `artifacts/FROZEN.json` is missing.

## Read next

- `EXPERIMENT_SPEC.md`
- `ARCHITECTURE.md`
- `EXPERIMENT_REPORT.md` (written by `analyze`)
