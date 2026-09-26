# GrokCell repair path

The runner makes legal next-action choices deterministically. Qwen proposes a
candidate component module and tests; the isolated runner, frozen operator
contracts, host oracle, and GrokCell admission gate decide whether the revision
is accepted. A proposal is not an accepted repair.

## Routing decision

The TypeSafe/Jev action chooser, Jev-Mem branch, retrieval arm, and paid
multi-arm routing comparison were removed on 2026-09-26. The current fixture
chain exposes at most one productive repair action before dependent components
can run, so an external chooser has no decision to improve. The retrieval arm
would also have confounded routing with memory, while Jev-Mem could not be
bounded under the same usage budget. No provider-based comparison or live
repair result was measured.

Reconsider model-based routing only when an independently accepted fixture
offers at least two productive legal actions and the consequences of choosing
between them can be checked under the same budget and acceptance gates.

## Offline check

From `grokcell/`:

```powershell
python -m grokcell.repair_experiment --check
python -m pytest tests/test_repair_offline.py -q
```

The preflight verifies the frozen contract files. It makes no provider calls,
does not execute candidate code, and does not validate Docker or provider
access.

## One live repair episode

Copy `repair_budget.template.json` to a local budget file and fill in the
digest-pinned Docker image, Qwen token prices, executor estimate, and spend
limit. The image must already be present and contain Python and pytest. With
Docker and `HF_TOKEN` configured, run:

```powershell
python -m grokcell.repair_experiment --live --budget budget.json --output run
```

This runs one Qwen-assisted episode on the seed fixture and writes its
machine-readable result and attempt records to the new output directory. It is
not a comparative result or a production claim.
