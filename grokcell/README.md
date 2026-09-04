# Autonomous GrokCell

Stateful agentic surface grokbots run on. Descendant of OSAHR 0.2.
Not the kernel. Not confirmatory science.

Experiment 06 (seed 260826) remains the last executed confirmatory
record. This package is a prototype control plane.

## What it is

A layer **above** grokbots.

```text
grokbot / agent
    -> tool ports (bus.post, park.request, oda.*, inspect)
        -> priority bus + vault constraints
            -> admit | hold_unresolved | reject | outcome_unknown
                -> OSAHR construction twin (DPO assemble-component)
```

Messages are control-plane objects. They are not radio links and
not occurrence types. `oda.spawn` registers an owner. It does not
rewrite G. Construction still goes through park / licensed admit.

Priority orders the queue. **Legality outranks priority**. `payload.verified`
is ignored. `critical_module` admits only after a python_tests record
and after an AST mutant dies. Frozen suites still need
`python -m grokcell.runner <name>` first. Generated `module` + `tests` are
untrusted Python and are refused unless an OS-isolated executor is supplied.
This prototype has no portable OS sandbox. For trusted local development only,
set `GROKCELL_ALLOW_UNSANDBOXED_RUNNER=1` to execute them on the host; the
runner still applies a hard timeout, bounded output, a minimal environment,
content-integrity checks, and mutation testing. Frozen repository suites do not
require this opt-in. Fail closed if the runner is absent or a mutant survives.

**Chat is not the database.** `open()` resumes `vault/state/`
(kernel checkpoint + surface queue/holds + admitted artifacts).
Delete that directory for a fresh cell. Snapshot is not an MCP tool.
Installed wheels keep mutable state under `~/.grokcell/vault/` by default;
the source checkout retains the repository-local `vault/` behavior.

## Run

From `grokcell/`:

```bash
python -m pytest tests
python -m grokcell.runner core.api
python -m grokcell
PYTHONPATH=.:.. python -m grokcell.mcp
```

From the repository root:

```bash
python -m pytest grokcell/tests
```

`python -m grokcell.runner core.api` (inside `grokcell/`) runs the
checkable suite. `python -m grokcell` then proposes `core.api`
without a client `verified` flag.

`python -m grokcell.mcp` is the Gate C host: JSON-RPC MCP over
stdio, wrapping the same tool names. Not HTTP. Gate D: connect
as an owner (`initialize` params `owner`). Unbound or mismatched
`bus.post` is refused. Spawn is how a new name enters. In-process
`ToolRegistry` defaults to MOUTH; the stdio process starts unbound.
Gate E: admit writes `vault/state/artifacts/<name>/` (module + tests).
`park.request` `act` send/publish/delete/sign stamps those files
and does not rewrite G. `GROKCELL_STATE_DIR` and
`GROKCELL_FIDELITY_DIR` override the default vault paths so the
process can resume Gate B files.

```json
{
  "mcpServers": {
    "grokcell": {
      "command": "python",
      "args": ["-m", "grokcell.mcp"]
    }
  }
}
```

## Tools

| Tool | Effect |
|---|---|
| `vault.query` | Read a constraint concept |
| `bus.post` | Queue a typed message |
| `bus.drain` | Classify the queue; admit commits |
| `surface.inspect` | Owners, components, hashes, holds, artifacts |
| `park.request` | Commit a held propose, or license artifact files |
| `oda.spawn` | Register an owner; does not rewrite G |
| `oda.attach_skill` | Skill rail on an existing owner |

## Laws that remain (named owners)

| Law | Owner |
|---|---|
| Only DPO + clocks rewrite G | OSAHR 0.2 kernel |
| Junction admit / hold / reject / unknown | Experiment 05 |
| Park licenses irreversible acts | Experiments 05 and 06 |
| Chat is not the database | Process twin (00 / SyberRuntime); Gate B files |
| LLM not in hazards | Experiments 01 / 02A |
| `verified` from python_tests runner | Gate A (12); bot cannot set it |
| File snapshot; `open()` resumes | Gate B (12); not an MCP tool |
| MCP stdio over existing tools | Gate C (12); not a second API |
| Session bind; registered `source_owner` | Gate D (12); not a new tool |
| One artifact type; mutants die | Gate E (12); park stamps files |

Deleted as unowned: no-swarm cap, one-mouth cap, spawn always refused.

## Do not

- Put an LLM in hazards
- Let a bot set `verified`
- Treat bus messages as OSAHR rules
- Let spawn bypass DPO
- Call this MEASURED
