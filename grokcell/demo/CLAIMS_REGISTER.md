# GrokCell claims register

**Status: draft; Session 8 audit pending.** This register describes evidence available in the supplied kit and pins the current documentation worktree. It is not a release verdict. Update it only after Session 1 names an integrated candidate and Session 8 audits that same revision. Do not transfer evidence between source identities.

| Claim | Exact source revision / evidence | Allowed scope | Unmet gate |
|---|---|---|---|
| The execution CLI is present in the Session 07 base checkout. | Exact base `c1de0fd34995d0329be37c4e8aa0aab5107b86fc`; source `grokcell/grokcell/execution/cli.py`. Session 07 ran main help, run help, and `preflight` with bundled Python 3.12.14. | This exact local source and read-only help/preflight only; preflight reported no live calls, credentials, Docker CLI, image, or independent review. | Candidate-specific checks and Session 8 audit. |
| Kit continuation overlay is identified by patch SHA-256 `3c31bdc2423653867488d8e3a0f14a2b4902dbc11d4cb1ae40ef4752ad5b099e`. | `LAUNCH_HANDOFF.json`; kit `evidence/STATUS.json` and `evidence/source-manifest.json`. | Identifies supplied overlay evidence only; not a repository commit. | Match to the Session 1 candidate tree and rerun integration checks. |
| Kit reports 104 passed and 2 skipped. | Kit sparse reconstruction: `evidence/tests.txt`, `continuation-tests.xml`, `evidence/STATUS.json`; Python 3.13.5 / pytest 9.0.2, sparse source. | Report the literal sparse-kit result and skips. | Full-checkout continuation CI; actual Docker/image; legacy full-repository case. |
| Offline repair and dependency demos replay in fresh processes. | Kit `evidence/SUMMARY.md`, `tests.txt`, recorded demo assets and `STATUS.json`. | Synthetic offline fixture behavior only. | Reproduction on integrated candidate; no live-provider inference. |
| Local failure/rollback exercise preserved the ledger and calls. | Kit `evidence/rollback.json`, `evidence/STATUS.json`; source summary describes local entrypoint failure/restoration. | Local drill only, not production rollback or schema-migration proof. | Integrated build/package, deployment rollback and operational recovery evidence. |
| Browser rendering and mobile/tab checks passed. | Kit `evidence/STATUS.json` and browser evidence in kit. | The recorded static report rendering in that environment. | Recheck final candidate/report and intended audience/device requirements. |
| Jev and Hugging Face adapter code exists. | Overlay `grokcell/grokcell/execution/providers.py`, `http_worker.py`, provider tests. Tests use injected responses; kit status says zero live calls. | Source-level adapter and conformance behavior only. | Authorized account run with request/model identities, bounded usage, reconciled provider billing. |
| Actual isolated candidate execution passed. | No supporting result. Kit status says not run; Docker/image test skipped. | No such claim allowed. | Approved image and exact digest; actual Docker allowed/denied cases on integrated candidate; independent audit. |
| Full-checkout continuation passed. | No supporting result. Kit status says not run; PR #29's older green CI is a different SHA. | No such claim allowed. | Required CI on exact integrated candidate. |
| System is production-ready, generally secure, or autonomous deployment. | No supporting result; docs/source explicitly disclaim these scopes. | No such claim allowed. | Product, threat, ops, authorization, deployment and recovery gates still need named review. |
| GrokCell has measured speed, cost, or quality advantage. | No comparative study; no live calls or reconciled invoices. | No such claim allowed. | Pre-registered or agreed comparison, identical workloads, repeated runs, full costs, checked outcomes, uncertainty and review. |
| External maintainers use or endorse it. | No supporting record; kit status says external maintainer validation false. | No such claim allowed. | Named maintainer, exact version, independently observed use and permission to report. |
| Static HTML can be deployed on Cloudflare Pages. | Current Cloudflare primary docs (Pages Direct Upload); this is a platform capability, not a GrokCell deployment. | General platform instruction only; no claim that SyberLabs account/site was configured. | Audience approval, clean artifact review, account authorization, access-policy decision and actual deployment verification. |
| Offline demo, isolated, and live commands succeed on the target host. | No such run in Session 07. The Windows host lacks the POSIX runtime and approved Docker/provider prerequisites. | No local result claim allowed; `--help` and read-only `preflight` only are verified. | Run the appropriate command on the frozen candidate in the designated environment. |

## Gate ledger

| Gate | Status in supplied kit | Owner / next evidence |
|---|---|---|
| Internal demo readiness | Fixture report prepared; Session 6 presenter-flow review pending. | Session 6 inspect current report and talk track. |
| Engineering completion | Integration baseline is prepared; completion is not established because required candidate-specific CI and platform gates remain. | Session 1 freeze candidate SHA; run required full-checkout checks. |
| Operational validation | Not established; no actual Docker or provider runs. | Approved execution target, isolation proof, provider/account envelope, billing reconciliation, recovery evidence. |
| Empirical advantage | Not established. | Comparative evaluation with declared workloads and cost/outcome measures. |
| Maintainer reuse | Not established. | Independent real use by a named external maintainer, with permission to report. |
| Marketing factual audit | Pending. | Session 8 audit the frozen copy against exact integrated candidate and evidence. |

## Freeze rule

This draft must not be relabeled final or distributed as audited copy until Session 1 supplies the exact integrated candidate revision and Session 8 records an audit of the material claims against that same revision. If the code, report, source manifest, or evidence changes, repeat the audit for the new identity.
