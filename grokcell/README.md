# Autonomous GrokCell

Stateful agentic surface grokbots run on. Descendant of OSAHR 0.2.
Not the kernel. Not a bot swarm. Not confirmatory science.

Experiment 06 (seed 260826) remains the last executed confirmatory
record. This package is a prototype control plane.

## What it is

A layer **above** grokbots, not a new family of them.

```text
grokbot / agent
    -> tool ports (bus.post, park.request, oda.*, inspect)
        -> priority bus + vault constraints
            -> admit | hold_unresolved | reject | outcome_unknown
                -> OSAHR construction twin (DPO assemble-component)
```

Messages are control-plane objects. They are not radio links and
not occurrence types. The mouth is `MOUTH`. `oda.spawn` is refused.
A new rail is `oda.attach_skill` on that owner.

OSAHR owns the **system graph** being built: Cell, Slot, Component,
PartOf. Park is the only path that commits a component. Priority
cannot override a vault exclude or a missing dependency.

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
| `oda.spawn` | Always refused in v0 |
| `oda.attach_skill` | Skill rail on MOUTH, not a new bot |

## Do not

- Put an LLM in hazards
- Treat bus messages as OSAHR rules
- Spawn specialist grokbots to "do message passing"
- Bypass DPO from the tool layer
