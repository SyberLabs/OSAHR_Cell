# GrokCell operator guide

**Draft for internal review. Evidence pending for the final candidate.**

This guide covers the supplied local CLI and the recorded demo kit. The pinned documentation base is `c1de0fd34995d0329be37c4e8aa0aab5107b86fc`; it is not a release verdict. Recheck every instruction against Session 1's exact candidate and Session 8's audit before freezing or distributing this guide.

## Choose your path

| Goal | Use | Evidence / limit |
|---|---|---|
| View the prepared demo | Open `recorded-demo/index.html` from the kit. | Static synthetic offline report; no install or provider keys. Review embedded HTML content before sharing. |
| Regenerate offline examples | Use the complete approved checkout on a supported POSIX host. | Unexecuted in Session 07; kit reports the offline fixture evidence separately. |
| Run Jev and Hugging Face | Use the full candidate package, reviewed config, dedicated credentials, and separate provider/account/task/budget approval. | Kit made zero live calls; no spend was authorized here. |
| Publish a presentation | Prepare a reviewed static `index.html` export for Cloudflare Pages. | No account setup or deployment performed. This does not host GrokCell execution. |

## Install and verify

**Prerequisite-dependent, unexecuted:** start from Session 1's frozen candidate revision in a clean full-repository checkout. Do not copy the kit's sparse runtime over the repository or apply its continuation patch to a different base. Use Python 3.11+ and the POSIX local-storage environment approved for execution.

```bash
python -m pip install -e . -e ./grokcell
python -m grokcell.execution --help
python -m grokcell.execution preflight
```

On the Session 07 base, main help and preflight were executed with the workspace Python 3.12.14. Help listed `repair`, `dependency`, `run`, `cancel`, `revoke`, `inspect`, `demo`, `release-check`, and `preflight`. Preflight reported zero live calls and false for TypeSafe credentials, HF credentials, Docker CLI, configured image, and independent review. It only checks presence; it does not authenticate accounts, validate Docker, or authorize spend.

## Run offline first

**Prerequisite-dependent, unexecuted on this Windows host:** with the frozen full package installed, choose new output folders:

```bash
python -m grokcell.execution demo --out /tmp/grokcell-demo-new
python -m grokcell.execution release-check --out /tmp/grokcell-rollback-new
```

`demo` defaults to fixture mode and records repair plus dependency assessment and replay. In the repair fixture, the check compares known bytes; it does not execute candidate Python. `release-check` is a local entrypoint failure and state-preservation drill; it is not a production deployment rollback. A report is recorded evidence, not fresh model inference.

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

The source template `execution_live.template.json` is intentionally not runnable: authorization is false, prices/reservations are null, and the HF model is a placeholder. Keep a completed copy outside the repository in a private location. Configure only implemented fields: model and expected response identity, token ceilings, request byte ceiling, timeout, integer micro-USD-per-million-token rates, and maximum charge reservation. HF's output ceiling is sent as `max_tokens`; Jev Choice has no generation-token setting. Bytes are not tokens. Local reservations cannot force vendor billing caps; account for the aggregate across calls and reconcile actual usage with provider records.

No `endpoint`, `temperature`, `top_p`, `reasoning_effort`, `response_format`, custom server URL, `bill_to`, or `X-HF-Bill-To` field is supported by this adapter. Environment variables alone do not enable a call. The adapter reads `TYPESAFE_API_KEY` and `HF_TOKEN`; load them only on the approved execution host through the approved secret manager. Never share keys in chat, source control, JSON, HTML, logs, or screenshots. An environment variable is not encrypted storage.

## Isolated checks and live runs

**Isolated repair:** requires an independently approved, digest-pinned image already available to Docker on the approved host. The runtime does not pull an image or fall back to executing candidate code on the host. The kit's Docker/image case was skipped; no actual isolation result is established. A restricted-language guard is defense in depth, not a general Python security guarantee.

**Live run command — unexecuted; separate explicit grant required:**

```bash
python -m grokcell.execution run \
  --workflow dependency \
  --state /private/grokcell/dependency-001 \
  --mode live --config /private/approved-execution.json
```

Before any provider request, an authorized owner must approve provider/account, submitted data, task, aggregate dollar/call/time limits, and execution target. Credentials are not authorization. Repair also needs the approved isolated image. There is no silent fallback to fixtures. A dependency assessment does not authorize an upgrade.

## Cloudflare Pages: static report only

Cloudflare Pages Direct Upload can serve a reviewed static report. Before publishing, prepare a clean folder containing only the approved `index.html`, inspect its embedded content, and obtain audience/account approval. A Direct Upload site serves static files; it does not run the Python CLI, provider adapters, or a live execution service. No SyberLabs Pages project or deployment has been created or approved here. Cloudflare notes Direct Upload projects cannot later be converted to Git integration, so choose that workflow deliberately.

A future interactive service would need an authenticated API, fixed reviewed model profiles, permissions and budgets, queue and cancellation behavior, durable-state design, isolation, disclosure controls, deployment approval, and recovery validation. Pages Functions are a platform feature; this repository does not contain that live service. Never place model credentials in the static report or candidate sandbox.

## Evidence status and operator links

The kit's `evidence/STATUS.json` and `evidence/SUMMARY.md` report **104 passed, 2 skipped** on sparse source: actual Docker/image and the unavailable full legacy kernel. The kit records offline fresh-process replay, local rollback exercise, browser rendering, and sparse-wheel smoke. It also records zero live calls, no full-checkout continuation CI, no actual isolation, no independent review, no deployment, no comparative advantage, and no external maintainer validation. PR #29's earlier CI is evidence for its own older revision only.

The exact Session 07 CLI help and read-only preflight succeeded on base `c1de0fd34995d0329be37c4e8aa0aab5107b86fc`; offline demo, release check, live calls, and Docker were not run here. Keep internal demo readiness, engineering completion, operational validation, empirical advantage, and maintainer reuse as separate claims.

Current primary references checked 2026-09-25: [TypeSafe models](https://docs.typesafe.ai/models), [TypeSafe API](https://docs.typesafe.ai/api), [Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers/index), [HF provider catalog](https://huggingface.co/docs/inference-providers/hub-api), [HF billing](https://huggingface.co/docs/inference-providers/pricing), [Cloudflare Pages Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/), and [Cloudflare Pages Functions](https://developers.cloudflare.com/pages/functions/). Recheck them before an actual operation.
