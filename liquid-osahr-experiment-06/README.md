# liquid-osahr-experiment-06

NetworkBrain stack on top of the frozen OSAHR 0.2 kernel and the 6G semantic-control twin.

Read `EXPERIMENT_SPEC.md` and `ARCHITECTURE.md` first. Run tests with:

```text
python3 -m pytest
```

Confirmatory seed `260826` is declared in the spec. Freeze before confirm:

```text
python3 scripts/run_experiment_06.py freeze
python3 scripts/run_experiment_06.py instrument
python3 scripts/run_experiment_06.py confirm
python3 scripts/run_experiment_06.py analyze
```
