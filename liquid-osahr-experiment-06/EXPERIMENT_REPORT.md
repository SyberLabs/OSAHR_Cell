# Experiment 06 Report — NetworkBrain stack

**Status:** formulated; confirmatory numbers are filled only after freeze + seed `260826`.

Every public claim is marked **KNOWN** / **MEASURED** / **INFERRED** / **PROPOSED**.

## What this is

A descendant of the frozen OSAHR 0.2 kernel and the 6G semantic-control twin. It adds a file-backed vault, AnLF boundary analytics, a `route-task` junction gate, and a single deterministic NetworkBrain. It does **not** overwrite Experiments 01–05.

## Claims

| Claim | Grade | Note |
|---|---|---|
| OSAHR kernel state is \(X=(G,B,R,\Theta,Z,t,n)\) | KNOWN | Unchanged 0.2 contract |
| \(\alpha=0\) is mechanistic identity | KNOWN | 02B; not re-litigated |
| 6G scalar semantic is `utility/deadline * reliability * fidelity` | KNOWN | `semantic_6g_twin_experiment.py` `_route_hazard` |
| Vault `critical` forbids `MEC-fast` when `requires_fidelity` | MEASURED | `tests/test_vault.py` |
| Background may use the degraded edge | MEASURED | `tests/test_vault.py` |
| AnLF payloads validate on `BoundaryHandle` and AnLF does not import `Runtime` | MEASURED | `tests/test_anlf.py` |
| Illegal vault pair is not an applicable `route-task`; generate/complete still match | MEASURED | `tests/test_junction.py` |
| 05 `score_claim` is imported, not copied | MEASURED | `tests/test_claims_reuse.py` |
| `park.request_rewrite` refuses `admit` / `reject` / `outcome_unknown` | MEASURED | `tests/test_mcp_park.py` |
| v1 Brain has no LLM import | MEASURED | `tests/test_brain` via `assert_no_llm_import` |
| `Task.concept_id` is experiment-schema only | MEASURED | `tests/test_schema_split.py` |
| Goal-utility MAE vs oracle (60 s, seed 260826) | MEASURED | see `artifacts/analysis.json` after confirmatory |
| Illegal-promotion rate per arm | MEASURED | see `artifacts/analysis.json` after confirmatory |
| Load-penalty mix is a stand-in for 02B \(H\), not the CfC field | INFERRED | declared in the spec; do not cite as 02B residual identity |
| A later LM mouth can sit on MCP tools without entering hazards | PROPOSED | out of scope for confirmatory |
| Vault promotion of a run into ontology needs a freeze | KNOWN | Experiment 04 transport failure; KP8 |

## Confirmatory

- Seed **260826**, horizon **60 s**, declared in `EXPERIMENT_SPEC.md` before execution.
- No LLM in confirmatory (`llm_in_confirmatory: false` in `FROZEN.json`).
- Any LM-shaped stub, if present in a later branch, is **non-confirmatory**.

## What was not done

- Experiment 05’s 22 s confirmatory remains unrun (separate budget).
- No srsRAN oracle, no new CfC, no SPARQL, no VSA runtime.
