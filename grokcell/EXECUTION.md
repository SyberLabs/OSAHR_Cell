# GrokCell execution preview

**Status: draft for internal review. Evidence-pending for the integrated release candidate.**

GrokCell is a local execution contract for composing a semantic decision with a candidate-generating worker and explicit checks, permission, accounting, and an accepted-state receipt. In this reference flow, Jev chooses among permitted next actions; a Hugging Face Inference Providers route supplies candidate output; GrokCell records and checks the workflow. Model confidence is not admission authority. The CLI examples use bundled inventory-repair and dependency-assessment fixtures; they are not a general repository repair service.

The current Session 07 checkout is based on `c1de0fd34995d0329be37c4e8aa0aab5107b86fc`. The new CLI and implementation are present in this checkout; PR #29 at `481151c00347ce461fb5439f4e0a9f73ec64e8fd` is the earlier scaffold and must not be used as evidence for them. This base is not itself a release verdict. **Freeze all final commands and feature claims against Session 1's exact candidate revision and Session 8's audit.**

## Read the prepared offline report

The kit's `recorded-demo/index.html` is a static report of synthetic fixture runs. It requires no Python environment or provider credentials to view. It is not a hosted service, live provider call, isolated-code result, or deployment authorization. Inspect the HTML itself before sharing because it embeds report content.

## Install and run the continuation (prerequisite-dependent)

**UNEXECUTED here:** these commands require Session 1 to freeze the exact candidate revision, a clean checkout at that revision, the full repository, Python 3.11+, and a supported POSIX host. The kit's sparse demo runtime is not a distribution and must not be copied over the full checkout. Use the integration owner's frozen patch instructions; do not apply the kit patch to a different revision just because it applied to the historical scaffold.

```bash
# From the integrated full-repository checkout, after its revision is frozen:
python -m pip install -e . -e ./grokcell
python -m grokcell.execution --help
python -m grokcell.execution preflight
python -m grokcell.execution demo --out /tmp/grokcell-demo-new
# Open /tmp/grokcell-demo-new/index.html in a browser.
python -m grokcell.execution release-check --out /tmp/grokcell-rollback-new
```

Choose new output folders. Existing run/report folders are not overwritten. In source-overlay CLI code, `demo` defaults to offline fixtures and the report is self-contained. `preflight` reports only whether credential variables, Docker CLI, and image configuration are present; it makes no provider calls and does not authenticate credentials, validate Docker, or establish spending approval. Session 07 executed `python -m grokcell.execution --help`, `python -m grokcell.execution run --help`, and `python -m grokcell.execution preflight` at this checkout using the workspace Python 3.12.14 runtime. Help listed `repair`, `dependency`, `run`, `cancel`, `revoke`, `inspect`, `demo`, `release-check`, and `preflight`; `run` showed workflow, mode, config, state, and resume options. Preflight returned zero live calls and reported TypeSafe credential=false, HF credential=false, Docker CLI=false, image configured=false, independent review=false. The interactive system Python shim was unavailable on PATH; the bundled workspace interpreter was used. Offline demo, release check, isolated behavior, and live-provider commands remain unexecuted here because the host does not meet the documented POSIX and/or approved service prerequisites. Separately, the kit reports 104 passes and two skips for its sparse source (Docker/image and unavailable full legacy kernel); see kit `evidence/SUMMARY.md` and `evidence/tests.txt`. Neither that sparse result nor CLI help establishes full-checkout CI or packaging.

## Offline, isolated, and live modes

- **Offline:** deterministic fixture callbacks; the repair check compares known bytes. No candidate Python execution and no network provider call.
- **Isolated:** repair candidate is checked using the existing digest-pinned Docker runner and a restricted arithmetic component contract. Requires a locally available, separately approved image and actual Docker verification. The kit did not run actual Docker/image cases. A language guard is defense in depth, not proof of general Python safety.
- **Live:** uses both Jev and HF provider adapters. Requires a separately authorized provider/account envelope and credentials; there is no silent fallback to fixtures. The kit made zero live provider calls. Live repair additionally requires approved isolation. Live dependency assessment does not grant upgrade permission.

Durable state is intended for operator-owned private POSIX local storage with working file locks, atomic rename, and fsync. Do not treat state as an upload format. The implementation binds replay to the original limits, expiry, workflow/runtime identity, provider identities, and check contract; it does not silently migrate schemas. Replay shows recorded results, not fresh inference. Preserve state after interrupted or unknown provider effects; do not retry blindly.

## Provider selection and configuration

Jev and HF are separate roles and credentials. The Jev adapter sends a versioned model ID to TypeSafe's `POST /v1/systemone` Choice API. The HF worker sends chat-completion requests to the Hugging Face router. In this code, `hf.provider` is the adapter name `"hf"`; the selected HF serving provider is the explicit suffix in `hf.model`, for example `org/model:provider`. This is a model ID convention, not a UI model picker. Check the live model/provider catalog and returned model identity before an approved run. HF requires a fine-grained token permitted to call Inference Providers; the TypeSafe key is separate.

The source template `execution_live.template.json` is intentionally disabled with `authorized: false`. It includes example numeric tariffs and reservations and an example HF route, `openai/gpt-oss-20b:ovhcloud`; these values are not an approved account quote or permission to run. Do not run it unchanged. An authorized operator must keep a reviewed copy in a private location, verify current route availability and returned identity, revalidate tariffs against the authorized account, and set reservations and workflow limits within the approved aggregate envelope.

Supported configuration in source overlay includes provider, pinned model ID, expected returned identities, token ceilings, input-byte ceiling, request timeout, and operator-supplied per-million-token tariffs and reservation. HF uses `max_output_tokens` as its request `max_tokens`. Jev's Choice adapter does not expose a generation-token limit. The byte check is not a tokenizer. The local reservation cannot force provider billing limits; reconcile with provider usage/bills. The code fixes provider endpoints. It has no `endpoint`, `temperature`, `top_p`, `reasoning_effort`, `response_format`, browser model picker, generic custom-server setting, `bill_to`, or `X-HF-Bill-To` header. Do not add such keys and infer support. Organization billing needs an adapter change if the operator requires the HF organization billing header.

**Credential handling:** use the approved secret manager on the actual execution host and scope dedicated credentials to the approved task. The source adapter reads `TYPESAFE_API_KEY` and `HF_TOKEN`; never paste values into chat, repository files, JSON, reports, screenshots, or shell history. An environment variable is not encrypted storage. Clear temporary variables after the authorized run. No key is requested or included here.

**Live command (UNEXECUTED; separate approval required):**

```bash
python -m grokcell.execution run --workflow dependency \
  --state /private/grokcell/dependency-001 \
  --mode live --config /private/approved-execution.json
```

This exact invocation requires the frozen candidate package, private state storage, completed reviewed configuration, credentials present in the process environment, and a separate grant naming provider/account, data, task, dollar/call/time limits, and execution target. No such spend or live run is authorized by this documentation. A repair run additionally needs an approved digest-pinned image already available on the approved Docker host.

## Share a static report versus host a live service

A reviewed static export may be considered for Cloudflare Pages after explicit audience and data review. Session 06's export allowlist contains `index.html` and `_headers`; preserve and review both files together. The Pages asset contains a report only: no GrokCell backend, live provider logic, secrets, persistent execution state, or browser model control. Cloudflare documents Direct Upload via Wrangler or dashboard drag-and-drop and notes a Direct Upload project cannot later convert to Git integration. These are publishing instructions only; no account configuration or deployment was performed or authorized.

An interactive service is a separate product and security boundary. The kit provides a Python CLI/library, not an authenticated HTTP API or Cloudflare Worker/Pages Function. A future service needs approved API/authentication, fixed model profiles, user and project permissions, budgets, queue/concurrency controls, cancellation/status, isolation, durable-state design, disclosure controls, deployment, and recovery validation. Pages Functions are a Cloudflare server-side capability, not a backend already present in this repository. Do not put provider credentials in static assets or a candidate sandbox. Do not describe this CLI as a drop-in Cloudflare service.

## Evidence and release gates

The kit's `evidence/STATUS.json` reports 104 passed / 2 skipped on a sparse Linux source reconstruction, offline two-workflow fresh-process replay, local entrypoint failure/rollback exercise, browser render checks, and a sparse-wheel smoke. It explicitly reports no full-checkout CI for the continuation, no actual Docker behavior, no live Jev/HF calls, no independent review, no deployment, no comparative advantage, no external maintainer validation, and not engineering complete. Earlier CI for PR #29 does not carry forward to this continuation.

Keep these separate: (1) internal offline-demo readiness, (2) engineering completion on the integrated candidate, (3) operational validation including actual provider/isolation and recovery, (4) empirical advantage under a comparative protocol, and (5) actual maintainer reuse. An execution receipt is not a legacy graph/artifact license or deployment grant. A green fixture suite is not marketing readiness.

**External docs checked 2026-09-25:** [TypeSafe models](https://docs.typesafe.ai/models), [TypeSafe API](https://docs.typesafe.ai/api), [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice), [Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers/index), [HF model/provider catalog](https://huggingface.co/docs/inference-providers/hub-api), [HF pricing and organization billing](https://huggingface.co/docs/inference-providers/pricing), [Cloudflare Pages Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/), [Cloudflare Pages Functions](https://developers.cloudflare.com/pages/functions/). Verify provider availability, rates, and Cloudflare console behavior again before an actual operation.
