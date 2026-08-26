---
name: grokcell-recovery-repair
description: >-
  Use when something is broken now: a failure, incident, corrupted state,
  degraded service, repeated build failure, or rollback request.
---
# GrokCell Recovery / Repair

What changed from the intended state, how far has the failure spread, and what is the safest shortest path back?

Do not make it worse. Stabilize before optimizing. A failure is not a redesign.

## Fast path

Stop at the first rung that holds.

1. **Small, local, reversible, low consequence** → repair it and move on.
2. **Failure still spreading** → contain first, in the smallest sufficient region.
3. **A known-good state exists and the change is recent** → roll back. Usually beats emergency improvisation.
4. **Cause is understood and local** → smallest correction that restores the capability.
5. **Cause is genuinely unknown** → preserve evidence, restore a safe subset, inspect in parallel. Do not stack irreversible repairs on a weak diagnosis.

Before any consequential change: identify current state, identify ongoing spread, preserve evidence, confirm authority, prefer reversible intervention.

## Freeze (rare)

Ordinary breakage stays on this skill. If **continuing is more dangerous than stopping**:

1. Freeze irreversible work only.
2. Do not self-expand that freeze.
3. Prefer isolate over delete.
4. Keep diagnostic read-only work going where it cannot worsen the failure.
5. The freeze expires. Resume normal work when the restored state is trustworthy.

Park send, spend, publish, delete, sign (`grokcell-oda`).

## Done when

Required capability is back, evidence of the failure is preserved, and we did not enlarge the blast radius to look busy. If the same failure will recur, write the smallest guard that would have caught it. Do not invent a monitoring program.
