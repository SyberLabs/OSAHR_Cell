# Experiment 06 Protocol — NetworkBrain control plane

**Status:** formulated. Confirmatory seed `260826` is declared here **before** any confirmatory trajectory is executed.

**Does not overwrite Experiments 01–05, the OSAHR kernel, or 6G `osahr/schema.py`.** Those remain the cited records. This descendant adds a vault, AnLF boundary tools, a route-task junction gate, and a v1 deterministic NetworkBrain that may request a rewrite only when Experiment 05 claim status is `hold_unresolved`.

## Question

Can a 6G control twin keep **meaning** in a file-backed vault, **observations** in NWDAF-like AnLF payloads on the boundary, and **one mouth** that acts only when an intervention claim is unresolved — without putting a language model inside OSAHR hazards?

## Hypothesis

1. Semantic legality is a **junction guard**, not a CTMC event type. Querying the vault on every occurrence would confuse a PKG with a kernel (KP7, KP8).
2. The 6G scalar `utility/deadline * reliability * fidelity` is **effectiveness**, not a language substrate (KP6). Vault-gated routing will disagree with that scalar on degraded-fidelity edges.
3. Experiment 05’s `admit | hold_unresolved | reject | outcome_unknown` is the junction law (KP11). A Brain that reports a directed effect matching oracle while the ensemble withholds **illegally promotes**.
4. One deterministic controller plus MCP recon tools is enough for v1. A generative LM, if added later, is a mouth on top of those tools (KP5, KP12).

## Frozen constants (declared before confirmatory execution)

| Quantity | Value |
|---|---|
| Confirmatory root seed | **260826** |
| Instrument seed | 260825 (1 s stub only) |
| Horizon | **60 s** (6G `ExperimentConfig` native; not the 3 s / 22 s assays) |
| Scenarios | 3 (`id`, `high_stress`, `long_outage`) |
| Replicates | 2 |
| Residual hypotheses \(H\) | `{0, 0.25, 0.5, 1.0}` as **load-penalty mix** on the scalar semantic hazard, not a new CfC and not an elected \(\alpha^*\) |
| Primary estimand | `goal_utility_ratio` |
| Intervention | `do(arm)` vs `do(throughput)` |
| Oracle | vault-greedy high-fidelity controller (`oracle_vault_greedy`) |
| Arms | (i) 6G scalar semantic (ii) vault-gated deterministic semantic (iii) Brain-at-hold |
| Claim grammar | Experiment 05 `osahr05_claim_v0` (imported, not copied) |
| Junction grammar | `osahr06_junction_v0` on `route-task` only |
| AnLF | `anlf.load.ema_v1`, `anlf.outage.threshold_cusum_v1` |
| Brain | `osahr06_brain_v1_deterministic` (no LLM import) |
| Park | `park.request_rewrite` refused unless `hold_unresolved` **and** currently matched **and** vault-legal |
| Runtime seed mixing | `(root_seed, scenario, replicate)` — not policy or \(\alpha\) |

## Decision rule at a junction

Reuse 05 `score_claim`. Then:

- `admit`: Brain idle; kernel fires the legal match.
- `hold_unresolved`: Brain picks among vault-legal `route-task` matches by frozen load penalty (`brain_load_weight = 2.0`).
- `reject` / `outcome_unknown`: withhold. Park refuses commit. A claim note is written under `vault/claims/` (chat is not the database).

## Primary endpoints

1. Policy-effect MAE vs oracle on `goal_utility_ratio`: \(\mathrm{mean}_s \lvert \Delta_{\mathrm{arm}}(s) - \Delta_{\mathrm{oracle}}(s) \rvert\).
2. Illegal-promotion rate: fraction of scenarios where the arm’s point \(\Delta\) **matches** oracle sign while ensemble status is `hold_unresolved` or `reject`.

## Explicitly out of scope

LLM on every hyperedge; new CfC training; real srsRAN as oracle \(do(\cdot)\); OWL/VSA/federated MTLF; Experiment 05’s unrun 22 s confirmatory; TOK handshake as rewrite discoverer.

## How to run

```text
python3 scripts/run_experiment_06.py freeze
python3 scripts/run_experiment_06.py instrument
python3 scripts/run_experiment_06.py confirm
python3 scripts/run_experiment_06.py analyze
```

Tests: `python3 -m pytest` from this directory (`py -3` on Windows). Confirmatory is refused if `artifacts/FROZEN.json` mismatches vault or grammar checksums.
