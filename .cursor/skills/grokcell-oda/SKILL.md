---
name: grokcell-oda
description: >-
  Use when forming, operating, splitting, reinforcing, synchronizing, or
  dissolving a Grok Bot mission cell, or when deciding whether to spawn, attach,
  split, merge, or keep structure.
---
# GrokCell ODA

The organization exists for the mission. Produce the effect with the smallest existing owner. Spawn is allowed. Spawn does not rewrite G.

## Fast path

Stop at the first rung that holds.

1. **An existing owner can do it** → assign it there. Done. Solo is the default.
2. **It needs a new rail** → write a **skill on an existing owner**.
3. **The work is genuinely independent** → spawn or attach, with a detach condition. `oda.spawn` registers an owner on the surface. It does not assemble a Component.
4. **None of the above** → leave the slot empty. An empty slot beats an invented bot.

## Owned locks (physics or named experiments)

Unowned Cell v0 recommendations were deleted (Elon: no owner → not a requirement). These remain because they have owners:

1. **Park** send, spend, publish, delete, sign. Owner: experiment 05 grammar + experiment 06 vault. `park.request` is the only license for low-reversibility acts on G.
2. **Only DPO + clocks rewrite G.** Owner: OSAHR 0.2 kernel. Tools, bus messages, and grokbots are not occurrence types.
3. **Chat is not the database.** Owner: process twin (SyberRuntime / 00). Durable state lives in files the cell already uses, not the thread.
4. **Junction grammar.** Owner: experiment 05. admit | hold_unresolved | reject | outcome_unknown. Do not promote a predictor that matches while the ensemble withholds.

Deleted as unowned: no agentic swarm; one mouth as a hard cap; `oda.spawn` always refused; spawn-test three conditions as a lock; skills only on MOUTH; no Cloud Agent unless the mouth names it; WRITER/em-dash as a system lock; sidebar-as-law.

## Irreversible work

Ordinary breakage is recovery (`grokcell-recovery-repair`). If continuing is more dangerous than stopping: freeze irreversible work; do not self-expand that freeze; prefer isolate over delete; the freeze expires.

## Done when

The cell produced the effect, parked irreversible acts, and left G unchanged except through DPO after a licensed admit or park.
