# SyberLabs / GrokCell — technical-preview demo handoff

## Positioning

**Models propose. Execution earns acceptance.**

GrokCell is a small execution layer for composing model judgments and generative
workers into bounded, inspectable workflows. The reference implementation keeps
observations, decisions, candidates, evidence, permission and accepted state
separate. It provides recorded replay and explicit stop conditions instead of
making a model's confidence the authority to act.

**Current audience:** internal SyberLabs demonstration and technical review.
This is not approval to launch a production service or publish superiority claims.

## Three-minute demonstration

1. Generate a fresh bundle with `python -m grokcell.execution demo --out NEW_DIR`.
   Open `index.html`. Start by naming the mode: **offline fixtures** by default.
   The two calls shown are fixture adapter calls, not live provider usage.
2. Select **Component repair**. Explain the arithmetic defect and show the
   candidate. In default mode, the check compares known bytes; in separately
   prepared isolated mode, the host compares actual sandbox behavior against the
   example contract. Neither mode proves arbitrary software correct.
3. Open the audit. Show named steps, reservations and the accepted-state receipt.
   Point out that acceptance does not grant deployment permission.
4. Select **Dependency assessment**. Show the same runtime handling a different
   artifact: known version facts, unknown compatibility, mandatory human review
   and `upgrade_authorized: false`.
5. Show **process-restart replay PASS**. This is computed by reopening each state
   in a new process and checking that calls and admission count do not increase.
   Navigation in the browser only displays the recorded evidence.
6. Close on scope: the implementation has real Jev/HF adapter code, but a report
   must contain actual live request evidence before anyone calls it a live-model
   demonstration. Quantified economics and real maintainer reuse remain separate.

## Safe talking points

| Statement | Evidence needed / current meaning |
|---|---|
| Two workflows compose through one execution interface | Runnable repair and dependency clients in `execution/workflows.py`. |
| Recorded results survive process restart | Executed filesystem/process tests and per-demo replay assertions. |
| Interrupted requests are not silently resent | Retained reservation and outcome-unknown regression cases. |
| Current permission and dependency scope matter | Admission and cancellation/revocation tests; inspect the specific receipt. |
| Real provider integrations are implemented | Adapter source and conformance tests. This does NOT establish live account access, quality or cost. |
| Actual isolated behavior was tested | Cite a completed actual-Docker CI job and image digest, never an offline fixture run. |

Do not claim: production-ready; fully autonomous deployment; universally safe
Python; guaranteed correctness; independent multi-agent review; exactly-once
provider execution; cheaper/better than contemporary alternatives; live Jev/HF
success without a live trace; external customers or adoption without records.

## FAQ

**Why Jev?** It is the required semantic decision component in this reference
implementation. Its advantage on each workload must be measured, not presumed.

**Why Hugging Face?** The worker interface supports an explicitly selected HF
model/provider route. This release does not anoint a model as the best builder.

**Is this a model router?** The provider seam is replaceable, but the product is
bounded execution, verification and recovery around composed decisions.

**Does it deploy code?** No. It produces evidence-scoped execution receipts and
reviewable candidates; deployment requires a separate authorized release path.

**What is proven by passing checks?** Only the tested contract under its declared
runtime and isolation assumptions. Compatibility and broader behavior may remain
unknown. The public demo cases are not a held-out benchmark.

## External-demo go/no-go

Before describing a demo as live, obtain a successful authorized Jev/HF run with
request IDs, serving identities where available, bounded usage, and applicable
checker evidence. Obtain independent technical review and named release approval
before public product availability claims. Use measured comparative evidence for
any superiority claim. Keep private state and credentials out of shared bundles.
