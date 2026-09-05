# Liquid-OSAHR Experiment 05

Claim status over a residual-hypothesis ensemble, not a point trust field \(T\to\alpha^*\).

Descendant of Experiments 02B, 03, and 04. Does not retrain the residual CfC and does not overwrite prior artifacts.

## Frozen confirmatory seed

- confirmatory `110518` at horizon **22.0 s**
- declared in `EXPERIMENT_SPEC.md` and `liquid_osahr05/protocol.py`
- confirmatory execution is refused until `artifacts/FROZEN.json` matches the claim grammar

## Instrument check

The 04 confirmatory table (\(h=3\) s, seed `880419`) scores the grammar. That run is labeled and is not a 05 confirmation.

## Run

```bash
py -3 -m pytest
py -3 scripts/run_experiment_05.py --stage formulate
```

Stages: `freeze`, `instrument`, `formulate` (freeze+instrument), `confirm`, `analyze`, `all`.

`all` includes the long-horizon confirmatory. Formulation does not.

## Read next

- `EXPERIMENT_SPEC.md` - question, decision rule, freeze
- `ARCHITECTURE.md` - HLMG split and invariants
- `EXPERIMENT_REPORT.md` - written by the run script
