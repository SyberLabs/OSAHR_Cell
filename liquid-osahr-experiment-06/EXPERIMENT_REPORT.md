# Experiment 06 Report: NetworkBrain stack

**Status:** frozen and confirmatory-executed on seed `260826`, horizon 60 s. No language model in confirmatory.

Every public claim is marked **KNOWN** / **MEASURED** / **INFERRED** / **PROPOSED**.

## What this is

A descendant of the frozen OSAHR 0.2 kernel and the 6G semantic-control twin. It adds a file-backed vault, AnLF boundary analytics, a `route-task` junction gate, and a single deterministic NetworkBrain. It does **not** overwrite Experiments 01–05.

## Unit-layer claims

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
| v1 Brain has no LLM import | MEASURED | `tests/test_brain.py` |
| `Task.concept_id` is experiment-schema only | MEASURED | `tests/test_schema_split.py` |
| Vault promotion of a run into ontology needs a freeze | KNOWN | Experiment 04; KP8 |
| Load-penalty mix is a stand-in for 02B \(H\), not the CfC field | INFERRED | declared in the spec |
| A later LM mouth can sit on MCP tools without entering hazards | PROPOSED | out of scope for confirmatory |

## Confirmatory (MEASURED)

- Root seed **260826**, horizon **60 s**, 3 scenarios × 2 replicates.
- Runtime seeds are `(root, scenario, replicate)`, not policy (05/02B contract).
- Oracle = vault-greedy high-fidelity controller vs throughput on `goal_utility_ratio`.
- \(H=\{0,0.25,0.5,1\}\) is a load-penalty mix on the scalar semantic hazard (**INFERRED** analogue of 02B, not the CfC checkpoint).
- `llm_in_confirmatory`: false.

| Arm | MAE vs oracle | Illegal-promotion rate |
|---|---|---|
| (i) 6G scalar semantic | 0.0565 | 1/3 |
| (ii) vault-gated semantic | 0.0767 | 1/3 |
| (iii) Brain-at-hold | 0.0689 | 1/3 |

Per scenario (eps = 0):

| Scenario | Regime | Claim status | What Brain did |
|---|---|---|---|
| 1 | id | `admit` | idle; Δ identical to vault-gated |
| 2 | high_stress | `admit` | idle; Δ identical to vault-gated |
| 3 | long_outage | `hold_unresolved` | load-penalty select among vault-legal matches |

Scenario 3 is the KP11 cell: ensemble signs disagree (\(\alpha=1\) flips), oracle \(\Delta\) is expressed and negative, and every arm’s point \(\Delta\) also comes out negative: **illegal promotion** if that point is reported as a licensed directed effect. The Brain was allowed to *act* at hold; it was not licensed to *claim* the oracle-matching sign.

Scalar semantic has the lowest MAE. That does not license it as an intervention policy: it still uses the degraded `MEC-fast` edge that the vault forbids for `critical` (KP2, KP6). Vault/Brain are legality layers, not a bid to win predictive MAE.

Withheld and scored statuses are notes under `vault/claims/` (chat is not the database).

## What was not done

- Experiment 05’s 22 s confirmatory remains unrun (separate budget).
- No srsRAN oracle, no new CfC, no SPARQL, no VSA runtime.
- No LLM-shaped stub was executed; none should be cited as confirmatory.
