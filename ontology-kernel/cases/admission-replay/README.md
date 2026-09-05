# Real maintenance case: recoverable component admission

## Decision and actual user need

The repository maintainer needs a component admission to produce a state that
the existing event records can reproduce. This is an observed repository defect,
not evidence of an external customer, willingness to pay, or product-market fit.

**Keep the repair and regression tests. Do not expand the ontology adapter on
the strength of this case.** Ordinary tests and OSAHR's existing replay engine
are sufficient to detect and correct the defect. A source repair also is not
the profile's operation of adding a fresh component. Representing the repair as
a fictional new admission would invalidate the comparison.

## Observation, repair, and mathematical contract

In `grokcell/grokcell/construction.py`, `licensed_assemble` recorded the external
proposal and assembly rewrite, then appended to `runtime.memory["components"]`.
That last mutation was absent from the records. The state hash includes memory.

For initial state X and recorded transition T, the replay contract is
`replay(X, records(T)) = T(X)`. The old live path instead ended at `U(T(X))`,
where U appended the redundant cache. Its last recorded hash therefore differed
from the actual final hash; subsequent records could not form a complete replay.

The repair removes U. Membership is the projection of Component vertices in the
authoritative graph. Stable entity-ID ordering preserves admission order because
this construction model uses one namespace and monotonically allocated IDs.
This ordering assertion is specific to this model, not arbitrary imported graphs.

The legacy empty memory field remains in the model definition to preserve model
identity and checkpoint compatibility. Populated historical caches are retained
as metadata, ignored for membership, and never appended during admission.
The rule, schema, core rewrite engine, and replay implementation are unchanged.
No new event store, serializer, ontology engine, or cache was introduced.

Removing the extra cache copy removes work proportional to existing membership
on each admission. Listing members still sorts IDs; full runtime costs remain.
No end-to-end latency improvement was measured or claimed for this repair.

## Executed checks

- [Before tests](before-tests.txt): three failed, one passed. The two admission
  cases exposed the event/live hash mismatch; the legacy-cache case exposed the
  unrecorded cache mutation.
- [After tests](after-tests.txt): all four regression checks passed, including
  multiple admissions, stable order after checkpoint restoration, and replay
  from a checkpoint containing stale historical cache data.
- [Initial integration run](integration-tests.txt): preserves the failures,
  including two unavailable Windows symlink privileges and a file-access error.
- [Final integration run](final-tests.txt): **289 passed, two skipped** in 48.71
  seconds on this host.
  Symbolic-link checks skip only when Windows reports missing creation privilege
  (1314); other errors still fail. Those checks remain unverified on this account.
  The isolated file-access failure passed on rerun; its cause is undetermined.
- [Manifest](manifest.json): source identities, evidence digests, and observed
  model-identity and replay comparisons. Checksums bind content; they do not
  authenticate the author or prove evidence truth.

The [ontology negative control](../../test_profile.py) supplies matching digests
for an exception-raising module and explicitly failing test evidence. Preview
still returns `candidate_transition_only` with `live_action_executed: false`.
This is the intended boundary: structural transition evidence is not a test
result or permission to admit code. Existing operator-owned acceptance tests
remain responsible for code admission. No fake acceptance suite was invented
for the source repair.

To rerun the focused checks from the repository root in PowerShell:

```powershell
$env:PYTHONPATH = '.;grokcell;ontology-kernel'
& .\.venv\Scripts\python.exe -m pytest grokcell/tests/test_admission_replay.py ontology-kernel/test_profile.py -p no:cacheprovider
```

For the full suite, use `tests workbench/tests grokcell/tests
ontology-kernel/test_profile.py` as pytest targets. On this Windows host, set
`TEMP` and `TMP` to a writable scratch directory and use a fresh `--basetemp`
under `ontology-kernel/scratch/`. The baseline production source is retained in
Git at `2bf8e91606aa0d3d6a253eef1c021be5ebad24be`; the manifest pins its blob.
To reproduce the negative baseline, run the new regression test against that
revision's production code in a separate checkout. No source copy is vendored.

## Product result and the next justified step

The baseline identified the unrecorded mutation and justified repairing it.
This case demonstrates no additional decision
change caused by the RDF adapter. Owner review time, commercial adoption, repeat
use, and willingness to pay were not observed. One out-of-domain maintenance
case cannot establish that the adapter is useless for every admission workflow.

The executable specialization and external PROV-O fixture already exist. Keep
them as a bounded research artifact. There is no evidence here to justify a
mock Foundry, a second approval system, a new adapter service, or a replacement
for existing graph/replay machinery.

The next owner pilot starts only with an actual pending *new component* and an
independently specified acceptance contract. Record the decision and review
effort using ordinary test artifacts first, then check whether the relational
preview reveals a consequential fact the baseline missed. Use another actual
case to check voluntary repeat use; two cases are a pilot, not market fit.
Preserve negative results. If the preview does not change a decision or remove
recurring work, stop expanding the integration. If it does, implement only the
missing step identified by that observation.

A platform pilot additionally needs an authorized nonproduction ontology and
its actual action contract. Use its native object, action, identity, and commit
semantics. A local mock cannot validate platform permissions or atomicity.
No tenant access, pending owner admission, or external approval is fabricated.
