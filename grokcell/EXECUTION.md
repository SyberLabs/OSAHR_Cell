# Execution scaffold

Status: runnable offline scaffold, not engineering completion or a live repair service.
Base: `c6ea8ad35a8b0c0fa7cde957c6ea7b2854e86070` (2026-09-25).

This is the first implementation slice of the Jev-backed decision-execution plan.
`grokcell.execution` supplies provisional records, adapter protocols, six operations,
an in-memory reference runtime, and two synthetic circuit clients. It introduces
no database, deployment service, paid call, or new dependency. PR #23's repair
restart work and the existing acceptance/runner/experiment paths are untouched.

## Run

From the repository root after installing the existing packages:

```bash
python -m pip install -e . -e ./grokcell
python -m grokcell.execution repair --replay
python -m grokcell.execution dependency --replay
cd grokcell
python -m pytest tests/test_execution_scaffold.py -q
```

The CLI has no live mode. It does not inspect provider credentials, generate code,
execute candidate Python, access the network, or create production artifacts.
Both commands emit JSON with `assurance: offline_preview`, `durable: false`, and
`live_execution_enabled: false`. Replay reuses the same in-memory journal and
must leave calls at two and the preview revision at one.

## Implemented seams

- `records.py`: Observation, Decision, Candidate, Evidence, Permission,
  AcceptedState, ActionOffer, and byte-owned JsonSnapshot; schema version 1.
- `ports.py`: decision and worker adapters, verifier, mandatory CheckContract,
  and replies with exact integer microdollar accounting or unknown usage.
- `runtime.py`: `read`, `decide`, `call`, `check`, `admit`, and `yield_`;
  bounded steps/calls/bytes, conservative reservations, named-step replay,
  cancellation, revocation, dependency invalidation, and idempotent preview commit.
- `examples.py`: repair and dependency-assessment clients share `checked_proposal`.
  There are no workflow-name branches in the core runtime.

The repair fixture checks exact known bytes, not Python behavior. The assessment
fixture checks a JSON shape and denial of upgrade authority, not the truth of
arbitrary prose. Neither fixture establishes model quality or real-world usefulness.

`Permission` and adapter instances are trusted operator configuration. Merely
constructing an Evidence object cannot admit it: admission requires the verifier
record retained by this run. Candidates and decisions must also have been issued
by the same run. Changing a declared checker contract invalidates pending admission.
These are reference invariants, not protection from malicious in-process host code.

Reservations are part of the step's replay identity. Unknown charges retain the
reservation; unrelated steps may use only the remaining allowance. A response
above its declared reservation blocks further work. Interrupted dispatch is not
resent automatically. `resume()` only unpauses this object: it does not reset the
budget, undo cancellation/revocation, or resolve an interrupted effect.

## Deliberate limits

The journal and evidence registry are in memory. There is NO cross-process resume,
power-loss durability, authenticated remote verdict, isolated candidate execution,
provider billing guarantee, or connection to GrokCell's actual artifact admission.
A PreviewRuntime receipt is never a `license.json` or permission to deploy.
`audit()` is a detached report, not an importable trusted checkpoint. Source,
contract, and environment identities here are supplied by trusted configuration;
a complete filesystem snapshotter and checker-artifact pinning remain to be built.

Only adapters declaring `mode = 'offline'` are accepted. That declaration is not
a sandbox; all callbacks are trusted. Deadline and output checks occur at callback
boundaries and cannot preempt a hanging callback or bound its peak allocation.
No live flag is provided to bypass these limits. Existing JevChoice/QwenBuilder
remain the real-provider starting points; the new layer does not replace them.

The parent package now lazily loads its existing public exports. Importing the
new records/CLI does not need to initialize the kernel. Export compatibility is
checked on a full checkout by CI.

## Next owned slices

1. Runtime: persist named effects, reservations, and receipts through the existing
   SnapshotStore generation boundary; reconcile PR #23 instead of duplicating it.
   Test crash windows and stale writers before enabling process restart.
2. Verification: connect independently owned mandatory checks to the approved
   isolated executor; retain host-side verdict authority. Do not weaken existing
   acceptance or mutation rules as a side effect of integration.
3. Providers: bind Jev's finite-choice interface and a configured HF worker through
   the same effect journal; verify usage, model/provider identity, retry ownership,
   and enforceable exposure bounds. Live runs require separately authorized spend.
4. Workflows: replace synthetic fixtures with independently accepted cases offering
   meaningful semantic decisions. Freeze public signatures only after both real
   workflows and a fresh developer's composition test pass.

Only reviewed integration should replace preview admission with real admission.
No production/deployment, empirical advantage, independent review, or external
maintainer-use claim is established by this scaffold.
