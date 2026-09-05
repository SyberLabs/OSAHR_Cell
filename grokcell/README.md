# Autonomous GrokCell

Stateful agentic surface grokbots run on. Descendant of OSAHR 0.2.
Not the kernel. Not confirmatory science. Experiment 06 (seed 260826)
remains the last executed confirmatory record.

Product direction: `PRODUCT_PLAN.md`. Surface laws: `ARCHITECTURE.md`.

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
