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

Priority orders the queue. **Legality outranks priority**: an
unverified `critical_module` at 99 is still rejected. Spawn is
not a ban and not a second kernel.

## Run

From `grokcell/`:

```bash
python -m pytest tests
python -m grokcell
```

From the repository root:

```bash
python -m pytest grokcell/tests
```

`python -m grokcell` (inside `grokcell/`) posts a legal core.api
propose, drains, and prints `surface.inspect`.

## Tools

| Tool | Effect |
|---|---|
| `vault.query` | Read a constraint concept |
| `bus.post` | Queue a typed message |
| `bus.drain` | Classify the queue; admit commits |
| `surface.inspect` | Owners, components, hashes, holds |
| `park.request` | Commit a held propose iff deps exist |
| `oda.spawn` | Register an owner; does not rewrite G |
| `oda.attach_skill` | Skill rail on an existing owner |

## Laws that remain (named owners)

| Law | Owner |
|---|---|
| Only DPO + clocks rewrite G | OSAHR 0.2 kernel |
| Junction admit / hold / reject / unknown | Experiment 05 |
| Park licenses irreversible acts | Experiments 05 and 06 |
| Chat is not the database | Process twin (00 / SyberRuntime) |
| LLM not in hazards | Experiments 01 / 02A |

Deleted as unowned: no-swarm cap, one-mouth cap, spawn always refused.

## Do not

- Put an LLM in hazards
- Treat bus messages as OSAHR rules
- Let spawn bypass DPO
- Call this MEASURED
