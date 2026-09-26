# GrokCell decision execution — internal technical preview

This package composes fallible decisions and candidate generation with explicit
observations, checks, permission, accounting and accepted-state receipts. It is
not a production multi-tenant service or an autonomous deployment system.

## Run a presenter demo

From an installed `grokcell-surface` package, or after `pip install -e . -e ./grokcell`:

```bash
python -m grokcell.execution demo --out /tmp/grokcell-demo-new
# Open /tmp/grokcell-demo-new/index.html in a browser.
python -m grokcell.execution release-check --out /tmp/grokcell-rollback-new
python -m grokcell.execution preflight
```

Choose new output directories. Existing runs are never silently overwritten.
The demo runs repair and dependency assessment in separate processes, reopens
each journal, and checks that replay adds neither adapter calls nor admissions.
The report is self-contained and makes no network requests. Its default mode
uses fixtures, not Jev/HF, and the repair check compares fixture bytes.

## Persistent execution

```bash
python -m grokcell.execution run --workflow repair --state /tmp/repair-run
python -m grokcell.execution run --workflow repair --state /tmp/repair-run --resume
python -m grokcell.execution inspect --state /tmp/repair-run
python -m grokcell.execution cancel --state /tmp/repair-run
```

`DurableRuntime` exposes READ/DECIDE/CALL/CHECK/ADMIT/YIELD using trusted Python
control flow. `workflows.py` contains two clients and a shared `checked_proposal`
circuit. Composition shares the caller's remaining budget and permission.
`PreviewRuntime` remains available for small in-memory reference tests.

`SnapshotStore` now supports execution-only generation manifests (version 2).
The existing version-1 kernel/surface format is retained. A root may contain one
format, never two competing authoritative pointers. Cross-format opening fails;
no implicit migration, graph projection, or legacy artifact license is created.
Ordinary workflow scheduling does not use the stochastic kernel.

Execution roots must be operator-owned, mode 0700, on POSIX local storage with
working file locks, atomic rename and fsync. The implementation flushes payloads
and directories before/after advancing CURRENT. Checksums detect corruption;
they do not authenticate a host administrator. A missing pointer with generation
files fails closed. The state directory is not an untrusted upload format.

An OS lease prevents competing coordinators. State writes use short locked
compare-and-swap transactions; no lock is held across provider execution. Operator
cancel/revoke can update the journal while a request is in flight. The original
coordinator then loses CAS and cannot commit a late result.

Before an effect, the intent and maximum liability are committed. Completed
results, typed records, checks, receipts and accounting share a generation.
Interrupted provider/check effects remain unknown and are not resent. Uncommitted
local READ/ADMIT/YIELD changes can be recomputed because they had no independent
external commit. Replay is recorded execution, not fresh model inference.

The clock, original expiry, limits, workflow source identity, runtime identity,
provider identities and check contract remain bound across restart. Reopening
with different configuration fails rather than resetting the budget. Code/schema
migration is intentionally blocked until an explicit migration procedure exists.

## Verification modes

- **offline:** known fixture bytes; never executes candidate Python.
- **isolated:** `IsolatedRepairVerifier` reuses the existing digest-pinned Docker
  runner and a narrowed arithmetic-component language guard (no imports, attributes,
  helper functions, defaults or loops). Inputs enter the sandbox; expected values
  and per-case comparisons stay with the host verifier. Only completed matching
  checks can produce an `isolated_contract_checked` execution receipt.
- **data-only:** dependency assessment must match the exact supplied versions and
  source snapshot, preserve unknown compatibility, require human review, and
  deny upgrade authority. It makes no assertion about arbitrary prose truth.

The operator owns contracts. Candidate tests do not select or replace them.
These public example contracts are not sealed evaluation data or proof of general
correctness. The language guard is defense in depth, not a Python security proof.
Docker/OS and the trusted verifier are part of the declared computing base.

To execute isolated behavior, provision and approve a Python image first:

```bash
export GROKCELL_SANDBOX_IMAGE='approved-repository@sha256:APPROVED_DIGEST'
python -m grokcell.execution demo --mode isolated --out /tmp/isolated-demo-new
```

The runtime never pulls an image or falls back to host execution.

## Real Jev/Hugging Face adapters

`providers.py` implements the TypeSafe choice endpoint and the HF chat-completion
router. A trusted transport subprocess bounds local wall time and receives only
the relevant provider credential. Responses are size-limited; application retries
and redirects are disabled. Model identity, usage, request ID, configuration,
serving revision when available and estimated cost are retained.

No provider call is enabled just by setting environment variables. Copy
`execution_live.template.json`, enter reviewed configuration, dedicated credential
scope and explicit authorization, then invoke `run --mode live --config FILE`.
Repair additionally requires the approved sandbox. Missing prerequisites block;
the command never substitutes fixtures for live output.

```bash
export TYPESAFE_API_KEY='set-through-your-approved-secret-manager'
export HF_TOKEN='set-through-your-approved-secret-manager'
python -m grokcell.execution run --workflow repair --state /private/live-repair \
  --mode live --config /private/approved-execution.json
```

Never put actual secrets in this repository, configuration JSON, reports or shell
history. The assignments above are illustrative names, not supplied credentials.

Prices are operator-configured nonnegative integer microdollars per million
tokens, not hardcoded vendor quotations. Missing billable usage remains unknown.
A zero-priced output field does not require output token counts for pricing, but
response-size/call/time limits still apply. Outstanding bounded liabilities stay
reserved. Returned usage beyond a declared ceiling faults the run. The configured
exposure bound must be independently reviewed against the provider's billing and
context guarantees; input bytes are NOT assumed to equal an input token ceiling.
Local accounting cannot force a provider to honor a dollar limit. Reconcile costs
with the provider invoice before making comparative economic claims.

References checked 2026-09-25: TypeSafe `https://docs.typesafe.ai/api` and
`https://docs.typesafe.ai/models`; HF
`https://huggingface.co/docs/inference-providers/tasks/chat-completion`.
No current-model winner or measured advantage is asserted by this implementation.

## Test and release evidence

```bash
(cd grokcell && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_execution_*.py)
```

The suite includes real process kills before dispatch, after a response, and
around admission; explicit cancel/revoke; stale writers; missing/mutated pointers;
forged evidence; missing checks; non-Python snapshot changes; data-only claim
boundaries; provider response/usage validation; report escaping; and a local
entrypoint failure/rollback drill. Docker-specific cases require an actual image
and must not be called executed when skipped.

The CI configuration defines full-checkout regressions, these execution tests,
wheel installation and both demos outside the checkout, then a separate
actual-Docker verification job. The continuation has not completed remote CI;
consult the delivered evidence status before claiming those jobs passed.
The local rollback exercise injects a broken entrypoint and restores the working
entrypoint without rewinding state. It is not a production rollout or a general
schema-migration rollback proof.

## Remaining release gates

A runnable internal demo is not full engineering or commercial completion. Keep
live-provider evidence, independent review, deployment approval, comparative
Studies A/B, and real maintainer reuse distinct. No worker receives deploy keys.
The execution receipts do not write legacy GrokCell graph/artifact licenses.
Marketing guidance and bounded follow-on work orders are in `demo/`.
