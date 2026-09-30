# Autonomous GrokCell

Stateful agentic surface grokbots run on. Descendant of OSAHR 0.2.
Not the kernel. Not confirmatory science. Experiment 06 (seed 260826)
remains the last executed confirmatory record.

Product direction: `PRODUCT_PLAN.md`. Surface laws: `ARCHITECTURE.md`.
The bounded Qwen repair path and the routing-study decision are documented in
`REPAIR_EXPERIMENT.md`.

## Repair path

Action selection is deterministic. Qwen can propose a component module and
candidate tests; GrokCell's sandbox, operator-owned checks, host oracle, and
admission gate decide whether the revision is accepted. The Jev route, retrieval
arms, and paid routing comparison were removed because the current fixtures
offer only one productive next action. No live repair result is measured.

```bash
cd grokcell
python -m grokcell.repair_experiment --check
python -m pytest tests/test_repair_offline.py -q
```

The [repair note](REPAIR_EXPERIMENT.md) records the removal decision and the
single-run budget requirements. The offline preflight remains available above.

```text
grokbot -> bus.post / park.request / oda.* -> vault + junction
        -> DPO assemble-component on licensed admit
```

`oda.spawn` registers an owner. It does not rewrite G. A bot cannot set
`verified`. Generated `module` + `tests` need an OS-isolated runner, or
`GROKCELL_ALLOW_UNSANDBOXED_RUNNER=1` for trusted local development.
Generated payloads also need a pinned operator-owned acceptance suite
(`GROKCELL_ACCEPTANCE_DIR`). Details are in `PRODUCT_PLAN.md`.

Component membership is read from the construction graph in stable allocation
order. Admission makes no separate membership-cache write after its recorded
events. The existing `Runtime.replay_deltas` can reproduce admission events from
a retained initial checkpoint. Historical `memory["components"]` values remain
checkpoint metadata and are ignored when listing members. This preserves model
identity without pretending that previously incomplete event histories are fixed.
Opening a checkpoint resumes state; it does not restore earlier event records.
This guarantee covers admission, not every control-plane memory mutation.
See the [replay regression case](../ontology-kernel/cases/admission-replay/README.md).

## Hosted durability scaffold

Install `grokcell-surface[hosted]` to use the PostgreSQL attempt/head store. A controller
must reserve budget and commit a fenced dispatch intent before external work;
admission then verifies a controller-generated checkpoint and kernel event log,
replays accepted deltas, and atomically writes the new head, attempt outcome,
and outbox record. Restore reads only exact versions named by the committed
head and replays admissions without invoking models or executors. Unknown work
stays blocked until the controller explicitly reconciles it.

| Attempt state | Transition | Recovery rule |
|---|---|---|
| `dispatch_intent` | A fenced PostgreSQL transaction reserves budget before work starts. | Never redispatch the same attempt after an uncertain acknowledgment. |
| `admitted` | One PostgreSQL transaction commits the immutable segment, head CAS, budget settlement, and outbox. | A retry returns this attempt's original receipt, even after later head revisions. |
| `outcome_unknown` | The controller loses the result or a new fence takes over. | Block new cell work until explicit no-admission reconciliation. |
| `reconciled_unknown` | A current controller records no-admission evidence and settles reserved units. | Terminal; a later request needs a new idempotency key. |

The object-store contract is `ControllerObjectStore`; this repository does not
yet provide or verify a cloud adapter or its IAM policy. Before enabling a
hosted endpoint, establish a controller-only PostgreSQL role and verify that
API, candidate, and executor roles cannot mutate heads, attempts, budgets, or
object references. Also verify that only the controller role can write/read
the controller-generated per-owner/cell object namespace, cannot select
quarantined versions, and that the coordinator scratch directory is
controller-only. The PostgreSQL test suite exercises transaction and code
provenance boundaries locally, not live IAM, deployment, or paid Jev comparisons.

## Run

```bash
python -m pytest grokcell/tests
cd grokcell && python -m grokcell.runner core.api && python -m grokcell
PYTHONPATH=grokcell:. python -m grokcell.mcp
```

Chat is not the database. `open()` resumes `vault/state/`.

| Tool | Effect |
|---|---|
| `vault.query` | Read a constraint concept |
| `bus.post` | Queue a typed message |
| `bus.drain` | Classify the queue; admit commits |
| `surface.inspect` | Owners, components, hashes, holds, artifacts |
| `park.request` | License a held propose or artifact files |
| `oda.spawn` | Register an owner; does not rewrite G |
| `oda.attach_skill` | Skill rail on an existing owner |

Do not put an LLM in hazards, let spawn bypass DPO, or call this MEASURED.
