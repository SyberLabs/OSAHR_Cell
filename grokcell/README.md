# Autonomous GrokCell

Stateful agentic surface grokbots run on. Descendant of OSAHR 0.2.
Not the kernel. Not confirmatory science.

Experiment 06 (seed 260826) remains the last executed confirmatory
record. This package is a prototype control plane.

Product direction, system design, validation gates, and the reconciliation of
issues #13/#15 are in [PRODUCT_PLAN.md](PRODUCT_PLAN.md).

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

Generated payloads additionally require a pinned operator-owned acceptance suite.
Candidate tests alone cannot license admission. See the configuration below.

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

## Independent acceptance for generated components

Before proposing generated code, the **operator** places independently authored
tests at `$GROKCELL_ACCEPTANCE_DIR/<component>/test_acceptance.py` and the SHA-256
of those exact bytes at `test_acceptance.sha256`. The environment variable is
host configuration. Proposal fields cannot register a suite or replace its pin.
There is no default acceptance suite for generated components.

For example, a trusted development fixture for `edge.ping`:

```bash
export GROKCELL_ACCEPTANCE_DIR=/tmp/grokcell-acceptance
mkdir -p "$GROKCELL_ACCEPTANCE_DIR/edge.ping"
cat > "$GROKCELL_ACCEPTANCE_DIR/edge.ping/test_acceptance.py" <<'PY'
from service import ping

def test_operator_contract():
    assert ping() == "pong"
PY
python - <<'PY'
import hashlib, os
from pathlib import Path
suite = Path(os.environ["GROKCELL_ACCEPTANCE_DIR"]) / "edge.ping"
digest = hashlib.sha256((suite / "test_acceptance.py").read_bytes()).hexdigest()
(suite / "test_acceptance.sha256").write_text(digest + "\n", encoding="ascii")
PY
```

This example is public test data, not a hidden evaluation. For trusted local
development inputs, the existing `GROKCELL_ALLOW_UNSANDBOXED_RUNNER=1` opt-in is
still needed. No sandbox is added by configuring an acceptance suite.

Use the existing `bus.post` with `kind: forge.propose`, component `edge.ping`,
`module`, `tests`, and `constraint: critical_module`, then `bus.drain`.
The candidate suite runs first, followed by a separate directory containing only
the candidate module and the operator tests. Each suite must pass and kill the
existing AST mutant. A wrong `ping()` returning `"wrong"` with matching candidate
tests is refused with `acceptance_failed`.

| Result | Meaning |
|---|---|
| `acceptance_suite_missing` | `outcome_unknown`; no generated code is run without a configured contract |
| `acceptance_suite_invalid` / `acceptance_suite_changed` | Invalid configuration or test bytes do not match the operator pin |
| `acceptance_failed` | Operator tests failed |
| `acceptance_mutant_survived` | Operator tests cannot detect the existing simple mutation |
| `acceptance_timeout` / `acceptance_infrastructure` | Evaluation was not completed successfully |
| `acceptance_modified_artifact` | Evaluation changed staged Python bytes |
| `vault_legal` | Both prototype gates passed; existing DPO admission follows |

Missing dependencies still hold without executing generated code. `park.request`
re-evaluates held proposals against the current configured contract, including
after restart. Admission writes `acceptance_suite_hash` alongside the exact
artifact `hash` in `license.json`; inspection exposes that suite digest, and file
action stamps preserve it. Operator tests themselves are not exported. Retain
their original bytes separately if you need to reproduce evaluation later.
Old admitted artifacts and frozen-suite proposals remain compatible. Generated
payloads using a frozen component's name still require independent acceptance.

**Boundary:** independent test authorship is not test secrecy or hostile-code
isolation. A process with host access can read or alter these files; checksums are
not authenticated signatures. This prototype cannot enforce a platform-wide write
policy. Passing these checks does not authorize deployment or any external action.

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
