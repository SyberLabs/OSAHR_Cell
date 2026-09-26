# GrokCell execution preview

**Evidence snapshot: PR #29 head `d1b8607230e30ced986c9ce171be0dcbf094b6f7`. S08 supports limited internal use of the existing recorded demo only; full engineering, operational, comparative, and adoption gates remain open.**

GrokCell is a local execution contract for composing a semantic decision with a candidate-generating worker and explicit checks, permission, accounting, and an accepted-state receipt. In this reference flow, Jev chooses among permitted next actions; a Hugging Face Inference Providers route supplies candidate output; GrokCell records and checks the workflow. Model confidence is not admission authority. The CLI examples use bundled inventory-repair and dependency-assessment fixtures; they are not a general repository repair service.

The recorded PR #29 head is `d1b8607230e30ced986c9ce171be0dcbf094b6f7`. GitHub Actions run [36271181196](https://github.com/SyberLabs/OSAHR_Cell/actions/runs/36271181196) ran at that exact SHA. Session 8's independent audit is for earlier production commit `8c2a0dfb1edf4fc20b2b7a5880acf3f8000ec54f` (tree `a203a254b21bc381b2b646be0321386285ee91cf`). The `8c2..d1` diff contains only `.github/workflows/execution-scaffold.yml` and `grokcell/tests/test_execution_providers.py`; it changes CI and tests, not production source. The audit therefore remains an audit of `8c2`, and the Actions result is separate test/CI evidence at `d1`. This does not establish full completion.

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

Choose new output folders. Existing run/report folders are not overwritten. In source-overlay CLI code, `demo` defaults to offline fixtures and the report is self-contained. `preflight` reports only whether credential variables, Docker CLI, and image configuration are present; it makes no provider calls and does not authenticate credentials, validate Docker, or establish spending approval. Session 07 previously executed main help, `run --help`, and read-only preflight on base `c1de0fd34995d0329be37c4e8aa0aab5107b86fc` with bundled Python 3.12.14. The stronger remote evidence is Actions run 36271181196 at exact head `d1b8607230e30ced986c9ce171be0dcbf094b6f7`: offline Python 3.11 and 3.13 jobs each passed 191 tests and skipped two actual-Docker tests. The installed-wheel fixture workflow, fresh-process replay, and local rollback checks passed. The overall run failed because the isolated job exited before Docker: `GROKCELL_APPROVED_ISOLATION_TEST_IMAGE` was unset. The failure was fail-closed; it is not actual isolation evidence. See the exact run for scope. These results do not establish full engineering completion.

## Offline, isolated, and live modes

- **Offline:** deterministic fixture callbacks; the repair check compares known bytes. No candidate Python execution and no network provider call.
- **Isolated:** repair candidate is checked using the existing digest-pinned Docker runner and a restricted arithmetic component contract. Actions run 36271181196 failed closed because `GROKCELL_APPROVED_ISOLATION_TEST_IMAGE` was unset, before actual Docker execution. No actual Docker/image result exists. A language guard is defense in depth, not proof of general Python safety.
- **Live:** uses both Jev and HF provider adapters. Requires a separately authorized provider/account envelope and credentials; there is no silent fallback to fixtures. The kit made zero live provider calls. Live repair additionally requires approved isolation. Live dependency assessment does not grant upgrade permission.

Durable state is intended for operator-owned private POSIX local storage with working file locks, atomic rename, and fsync. Do not treat state as an upload format. The implementation binds replay to the original limits, expiry, workflow/runtime identity, provider identities, and check contract; it does not silently migrate schemas. Replay shows recorded results, not fresh inference. Preserve state after interrupted or unknown provider effects; do not retry blindly.

## Provider selection and configuration

Jev and HF are separate roles and credentials. The Jev adapter sends a versioned model ID to TypeSafe's `POST /v1/systemone` Choice API. The HF worker sends chat-completion requests to the Hugging Face router. In this code, `hf.provider` is the adapter name `"hf"`; the selected HF serving provider is the explicit suffix in `hf.model`, for example `org/model:provider`. This is a model ID convention, not a UI model picker. Check the live model/provider catalog and returned model identity before an approved run. HF requires a fine-grained token permitted to call Inference Providers; the TypeSafe key is separate.

The source template `execution_live.template.json` is disabled with `authorized: false` and `budget_scope: credential_owner_no_bill_to_override`. It includes the example HF route `openai/gpt-oss-20b:ovhcloud`; Jev input rate/reservation `42000`/`2700` micro-USD per million tokens/per call; and HF input/output rates/reservation `50000`/`180000`/`3600` micro-USD. These are template examples, not an approved account quote, current availability check, billing cap, or permission to run. Do not run it unchanged. Keep the reviewed file private, verify current route availability and returned identity, revalidate tariffs against the credential owner, and fit reservations within the approved aggregate envelope.

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

At exact head `d1b8607230e30ced986c9ce171be0dcbf094b6f7`, Actions run 36271181196 reports two successful offline matrix jobs: Python 3.11 and 3.13 each 191 passed / 2 actual-Docker skips. The installed wheel fixture workflows, restart replay, and local rollback checks passed. The isolated job failed closed because its approved-image variable was unset; no actual Docker execution occurred. The workflow run as a whole is therefore failed. No live Jev/HF calls, Cloudflare deployment, comparative advantage, or external maintainer reuse are evidenced.

Session 8 independently audited production commit `8c2a0dfb1edf4fc20b2b7a5880acf3f8000ec54f` / tree `a203a254b21bc381b2b646be0321386285ee91cf` and recommended only limited use of the existing historical internal recorded demo. The audit closes its reproduced source findings within portable scope; it explicitly leaves physical POSIX durability, actual isolation, live providers/billing, deployment, comparative advantage, and external reuse open. The later `8c2..d1` diff changes only the CI workflow and provider tests. Neither the older independent audit nor the newer CI result establishes full engineering completion.

Keep these separate: (1) internal offline-demo readiness, (2) engineering completion on the integrated candidate, (3) operational validation including actual provider/isolation and recovery, (4) empirical advantage under a comparative protocol, and (5) actual maintainer reuse. An execution receipt is not a legacy graph/artifact license or deployment grant. A green fixture suite is not marketing readiness.

**External docs checked 2026-09-25:** [TypeSafe models](https://docs.typesafe.ai/models), [TypeSafe API](https://docs.typesafe.ai/api), [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice), [Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers/index), [HF model/provider catalog](https://huggingface.co/docs/inference-providers/hub-api), [HF pricing and organization billing](https://huggingface.co/docs/inference-providers/pricing), [Cloudflare Pages Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/), [Cloudflare Pages Functions](https://developers.cloudflare.com/pages/functions/). Verify provider availability, rates, and Cloudflare console behavior again before an actual operation.
