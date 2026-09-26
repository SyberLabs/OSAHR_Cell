# GrokCell operator guide

**Evidence snapshot:** exact Actions run 36271181196 at PR #29 head `d1b8607230e30ced986c9ce171be0dcbf094b6f7`. S08 separately audited production commit `8c2a0dfb1edf4fc20b2b7a5880acf3f8000ec54f` and supported only limited use of the existing recorded demo.

This guide covers the local CLI and static report. Actions run 36271181196 ran at `d1b8607230e30ced986c9ce171be0dcbf094b6f7`. S08's independent audit is for `8c2a0dfb1edf4fc20b2b7a5880acf3f8000ec54f` and tree `a203a254b21bc381b2b646be0321386285ee91cf`. The `8c2..d1` diff touches only `.github/workflows/execution-scaffold.yml` and `grokcell/tests/test_execution_providers.py`, not production source. The audit and later CI are separate evidence; neither is a full-completion verdict.

## Choose your path

| Goal | Use | Evidence / limit |
|---|---|---|
| View the prepared demo | Open `recorded-demo/index.html` from the kit. | Static synthetic offline report; no install or provider keys. Review embedded HTML content before sharing. |
| Regenerate offline examples | Use the complete approved checkout on a supported POSIX host. | Unexecuted in Session 07; kit reports the offline fixture evidence separately. |
| Run Jev and Hugging Face | Use the full candidate package, reviewed config, dedicated credentials, and separate provider/account/task/budget approval. | Kit made zero live calls; no spend was authorized here. |
| Publish a presentation | Prepare a reviewed static export containing `index.html` and `_headers` for Cloudflare Pages. | No account setup or deployment performed. This does not host GrokCell execution. |

## Install and verify

**Prerequisite-dependent, unexecuted:** start from Session 1's frozen candidate revision in a clean full-repository checkout. Do not copy the kit's sparse runtime over the repository or apply its continuation patch to a different base. Use Python 3.11+ and the POSIX local-storage environment approved for execution.

```bash
python -m pip install -e . -e ./grokcell
python -m grokcell.execution --help
python -m grokcell.execution preflight
```

On the earlier Session 07 base, main help and preflight were executed with workspace Python 3.12.14. Separately, the exact-head Actions run completed the Python 3.11 and 3.13 offline jobs successfully: 191 passed and 2 actual-Docker skips in each matrix job. The installed-wheel fixture workflows, fresh-process replay, and local rollback checks passed. Preflight is presence-only and does not authenticate accounts, validate Docker, or authorize spend. See [Actions run 36271181196](https://github.com/SyberLabs/OSAHR_Cell/actions/runs/36271181196).

## Run offline first

**Prerequisite-dependent, unexecuted on this Windows host:** with the frozen full package installed, choose new output folders:

```bash
python -m grokcell.execution demo --out /tmp/grokcell-demo-new
python -m grokcell.execution release-check --out /tmp/grokcell-rollback-new
```

`demo` defaults to fixture mode and records repair plus dependency assessment and replay. In the repair fixture, the check compares known bytes; it does not execute candidate Python. At d1, Actions verified installed-wheel fixture workflows, replay, and local rollback; this is not a live run or production rollback. A report is recorded evidence, not fresh model inference. `release-check` commands above are not documented as individually run from this Windows Session 07 checkout.

The source CLI also offers persistent commands (all unexecuted here; require the frozen package and supported state storage):

```bash
python -m grokcell.execution run --workflow repair --state /private/repair-001
python -m grokcell.execution run --workflow repair --state /private/repair-001 --resume
python -m grokcell.execution inspect --state /private/repair-001
python -m grokcell.execution cancel --state /private/repair-001
```

Durable state is for operator-owned private POSIX local storage with working file locks, atomic rename, and fsync. Preserve state when a provider/check effect is interrupted or unknown; replay does not mean safe to resend. Configuration, expiry, workflow and provider identity, and check contract are bound across resume.

## Select and configure the models

Jev and Hugging Face have separate roles and credentials. Jev makes a bounded semantic choice among actions the workflow supplies; the HF worker returns a candidate module or structured assessment. GrokCell code owns checks, permission, budgets, and admission. Model confidence is never a permission grant.

For HF, choose a model available for chat completion and an explicit serving provider. In this adapter, `hf.provider` must be `"hf"`; set `hf.model` to the HF model ID with explicit provider suffix, such as `org/model:provider`. The CLI has no browser model picker. HF documents the fine-grained token permission **Make calls to Inference Providers** and model/provider routing. Verify the route in the current catalog and confirm the exact returned model identity before use.

For Jev, configure a versioned TypeSafe model identity and use a separate TypeSafe API key. Current TypeSafe documentation describes the `POST /v1/systemone` Choice endpoint, Jev `jev-1.13.0`, and currently listed input pricing. These facts may change; check the vendor's current model, account, and billing information before setting rates.

The source template `execution_live.template.json` is disabled with `authorized: false` and `budget_scope: credential_owner_no_bill_to_override`. Its example HF route is `openai/gpt-oss-20b:ovhcloud`; Jev input rate/reservation are `42000`/`2700` micro-USD per million tokens/per call; HF input/output rates/reservation are `50000`/`180000`/`3600` micro-USD. These are template values, not an approved account quote, current availability check, billing cap, or permission to run. Keep a reviewed copy outside the repository in a private location. Verify current route availability, returned identity, and account tariffs before setting implemented fields: model and expected response identity, token ceilings, request byte ceiling, timeout, integer micro-USD-per-million-token rates, and maximum charge reservation. HF's output ceiling is sent as `max_tokens`; Jev Choice has no generation-token setting. Bytes are not tokens. Local reservations cannot force vendor billing caps; account for the aggregate across calls and reconcile actual usage with provider records.

No `endpoint`, `temperature`, `top_p`, `reasoning_effort`, `response_format`, custom server URL, `bill_to`, or `X-HF-Bill-To` field is supported by this adapter. Environment variables alone do not enable a call. The adapter reads `TYPESAFE_API_KEY` and `HF_TOKEN`; load them only on the approved execution host through the approved secret manager. Never share keys in chat, source control, JSON, HTML, logs, or screenshots. An environment variable is not encrypted storage.

## Isolated checks and live runs

**Isolated repair:** requires an independently approved, digest-pinned image already available to Docker on the approved host. The runtime does not pull an image or fall back to executing candidate code on the host. At exact d1, the Actions isolated job failed closed because `GROKCELL_APPROVED_ISOLATION_TEST_IMAGE` was unset and exited before Docker. The offline matrix each skipped the two actual-Docker tests. No actual isolation result is established. A restricted-language guard is defense in depth, not a general Python security guarantee.

**Live run command — unexecuted; separate explicit grant required:**

```bash
python -m grokcell.execution run \
  --workflow dependency \
  --state /private/grokcell/dependency-001 \
  --mode live --config /private/approved-execution.json
```

Before any provider request, an authorized owner must approve provider/account, submitted data, task, aggregate dollar/call/time limits, and execution target. Credentials are not authorization. Repair also needs the approved isolated image. There is no silent fallback to fixtures. A dependency assessment does not authorize an upgrade.

## Cloudflare Pages: static report only

Cloudflare Pages Direct Upload can serve a reviewed static report. Session 06's locally verified static export has an exact two-file upload allowlist: `index.html` and `_headers`. Prepare a clean folder containing only those two files and inspect both. Keep `artifact-manifest.json` as local evidence rather than an upload asset, then obtain audience/account approval. A Direct Upload site serves static files; it does not run the Python CLI, provider adapters, or a live execution service. No SyberLabs Pages project or deployment has been created or approved here. Cloudflare notes Direct Upload projects cannot later be converted to Git integration, so choose that workflow deliberately.

A future interactive service would need an authenticated API, fixed reviewed model profiles, permissions and budgets, queue and cancellation behavior, durable-state design, isolation, disclosure controls, deployment approval, and recovery validation. Pages Functions are a platform feature; this repository does not contain that live service. Never place model credentials in the static report or candidate sandbox.

## Evidence status and operator links

At exact PR #29 head `d1b8607230e30ced986c9ce171be0dcbf094b6f7`, GitHub Actions run 36271181196 passed the Python 3.11 and Python 3.13 offline jobs, each with 191 passed and two actual-Docker skips. Installed-wheel fixture workflows, fresh-process replay, and local rollback checks passed. The isolated job failed closed because `GROKCELL_APPROVED_ISOLATION_TEST_IMAGE` was unset, so the overall Actions run failed and no Docker execution occurred. No live Jev/HF calls, Cloudflare deployment, comparative advantage, or external maintainer reuse is evidenced.

S08 independently audited exact production commit `8c2a0dfb1edf4fc20b2b7a5880acf3f8000ec54f` and supports a limited internal recorded-demo recommendation. Its reproduced findings were closed within portable scope; physical POSIX durability, actual isolation, live provider/billing, deployment, comparative advantage, and external reuse remain held. The later `8c2..d1` diff is CI workflow and provider tests only. The d1 Actions run is test/CI evidence, not an independent audit of d1 or full engineering completion.

The exact Actions run status is mixed: offline jobs and listed wheel checks passed, but overall conclusion failed at the unset-image isolation job. No live, Docker, or Cloudflare operation was performed. Keep recorded-demo readiness, engineering completion, operational validation, empirical advantage, and maintainer reuse as separate claims. The S08 audit SHA and d1 CI SHA must not be conflated.

Current primary references checked 2026-09-25: [TypeSafe models](https://docs.typesafe.ai/models), [TypeSafe API](https://docs.typesafe.ai/api), [Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers/index), [HF provider catalog](https://huggingface.co/docs/inference-providers/hub-api), [HF billing](https://huggingface.co/docs/inference-providers/pricing), [Cloudflare Pages Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/), and [Cloudflare Pages Functions](https://developers.cloudflare.com/pages/functions/). Recheck them before an actual operation.
