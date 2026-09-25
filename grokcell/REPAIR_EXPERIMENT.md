# GrokCell repair experiment

From `grokcell/`, run the offline preflight without provider calls or candidate execution:

```powershell
python -m grokcell.repair_experiment --check
python -m pytest tests/test_repair_offline.py -q
```

Copy `repair_budget.template.json` to `budget.json` and fill its deliberately
unusable image and price placeholders from your authorized infrastructure.
The live runner needs a pre-pulled digest-pinned Linux image containing Python and pytest,
Docker, `HF_TOKEN`, and (for the paired pilot) `TYPESAFE_API_KEY`. Supply real
account prices for Qwen and Jev input/output tokens and the executor-second
estimate. The budget names `sandbox_image` as `repository@sha256:<digest>`.
The runner will not pull an image or use the host-execution opt-in.

```powershell
python -m grokcell.repair_experiment --live --seed-prior --budget budget.json --output seed-run
python -m grokcell.repair_experiment --live --budget budget.json --prior-state seed-run/seed_reserve/B/state --output pilot-run
python -m grokcell.repair_experiment --live --resume --budget budget.json --prior-state seed-run/seed_reserve/B/state --output pilot-run
```

The unscored seed episode creates public repair evidence on a distinct input.
The paired pilot
shuffles five frozen variants across A (Qwen routing), B (deterministic), C
(Jev), D (Jev with simple retrieval), and E (Jev-Mem). E is currently reported
as **blocked** because Jev-Mem's nested provider usage cannot yet be metered
and reserved under the same hard budget. `results.jsonl`, `run_config.json`,
and `summary.json` are the machine-readable evidence. Resume skips fully
recorded episodes; an interrupted episode stops for operator reconciliation
before any call or admission is replayed.

Routing is deterministic when there is at most one productive legal action;
the always-present escalation option does not by itself justify a model call.
The summary reports Jev route calls. Zero calls mean this pilot did not test
Jev's judgment and cannot support retaining it.
With the current three-component chain, component gates expose at most one
failing component before its dependents can run. The no-memory C arm therefore
has no Jev routing opportunity; A, B, and C choose the same productive action.
D can ask Jev whether to retrieve prior evidence, so a D/C difference would
mix routing with retrieval. This fixture tests repair and admission, but cannot
establish a Jev routing gain or separate the value of simple retrieval. Do not
create artificial choices solely to make Jev run.
The `upstream_sku` defect is caught by the decoder's own public contract before
the downstream components run, so this fixture also does not demonstrate a
misleading downstream failure. A different independently accepted incident is
needed to test root-cause routing.

The frozen test manifest is `tests/repair_contracts/SHA256SUMS.txt`. A separate
test-author context wrote the operator suites before the repair loop was built;
this is authorship separation, not external validation. A passing episode
requires the component gates and assembled application check on the same
revision manifest. The generated module language is constrained, and Docker
provides host isolation; hostile-code claims require a live adversarial run in
the approved image.

The predeclared worthwhile threshold is 20% more independently accepted
complete repairs per **estimated** dollar, without lower completion or an
observed false acceptance. The estimate uses measured token counts, configured
provider prices, and an executor-second rate. The seed cost is reported
separately and included in the fully loaded D/E rate. A five-task pilot is
descriptive and cannot authorize production promotion. Unknown cost blocks
comparison.

References: [Qwen3-Coder-Next](https://huggingface.co/Qwen/Qwen3-Coder-Next)
(repository revision `a7fbcb5c0e12d62a448eaa0e260346bf5dcc0feb`, Apache-2.0),
[TypeSafe API](https://docs.typesafe.ai/api), and
[Jev-Mem](https://github.com/libingzheren/Jev-Mem)
(source inspected at commit `81574eb23f3fd8d1a6c4d54a1e7d6f2dd539e9bb`, MIT;
not installed in the runnable path).
Provider-served runtime revisions and prices remain unverified until a live run.
