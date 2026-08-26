---
name: grokcell-forge
description: >-
  Use when something must be built: implementation, prototype, probe, tool,
  workflow, schema, experiment, integration, or document.
---
# GrokCell Forge

What is the smallest coherent thing we can make that causes the desired mission effect?

Build effects, not files. Output is what you produced; behavior is what it does; **effect is why that matters**.

## Fast path

Stop at the first rung that holds.

1. **Verified capability already exists** → reuse it. Search the repo and known artifacts first.
2. **One decisive uncertainty gates the design** → build the cheap probe that eliminates a branch. Not the system.
3. **Terrain is clear and the change is small and reversible** → build it, self-check. Done.
4. **Multiple systems interact** → define the interface contract first, then a thin end-to-end slice.
5. **High consequence** → make state, failure, and rollback visible before expanding scope.

Label **probe**, **prototype**, and **production**. Do not promote a probe into production by accident.

## Do not

- Build a framework for one use.
- Refactor unrelated modules while implementing the task.
- Swallow significant failures.
- Claim done because it compiled or a demo worked.
- Execute send, spend, publish, delete, or sign without authority (`grokcell-oda`).

If terrain is unclear, stop and use `grokcell-recon`. If you destabilized something that already worked, stop and use `grokcell-recovery-repair`.

## Done when

The effect exists, at the required scope, with no extra machinery. Critical interfaces are explicit. Known limitations are disclosed. Further building is worth less than checking the result.
