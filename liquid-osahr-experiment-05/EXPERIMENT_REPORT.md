# Experiment 05 Report: Residual-Hypothesis Claim Status

**Answering object:** claim status, not a point T to alpha*.
**Confirmatory seed (declared):** `110518`. **Horizon:** 22.0 s.

**Confirmatory status:** not executed. This report is formulation plus the labeled h=3 s instrument check.

## Instrument check (04 holdout, h=3 s), not confirmatory

Source SHA-256 `73227e650d18322b…`. Independent units: 20. Expressed: 12.

Goal-utility status counts at eps=0:

| Status | Count | Macro rate (95% CI) |
|---|---:|---|
| outcome_unknown | 8 | 0.40000  [0.20000, 0.60000] |
| admit | 4 | 0.20000  [0.05000, 0.35000] |
| hold_unresolved | 6 | 0.30000  [0.10000, 0.50000] |
| reject | 2 | 0.10000  [0.00000, 0.20000] |

Activation without effect: `0.00000  [0.00000, 0.00000]`.
Illegal promotion of 04 `T_strict` among expressed: `0.08333  [0.00000, 0.25000]`.
Illegal promotion of global alpha=1 among expressed: `0.16667  [0.00000, 0.41667]`.

Other estimands (unknown / admit / hold / reject):

| Estimand | eps | Unknown | Admit | Hold | Reject | Expressed |
|---|---:|---:|---:|---:|---:|---:|
| goal_utility_ratio | 0.00 | 8 | 4 | 6 | 2 | 12 |
| goal_utility_ratio | 0.02 | 9 | 2 | 7 | 2 | 11 |
| critical_success_rate | 0.00 | 14 | 0 | 3 | 3 | 6 |
| critical_success_rate | 0.02 | 14 | 0 | 3 | 3 | 6 |
| mean_latency | 0.00 | 0 | 9 | 9 | 2 | 20 |
| mean_latency | 0.02 | 10 | 1 | 6 | 3 | 10 |

Latency at eps=0 is saturated (every scenario has a nonzero contrast). Read latency at eps=0.02.
This table tests the instrument. It is not a 05 confirmation.

## Scope

- KNOWN: grammar and seeds frozen; 04 3 s table used as a labeled instrument check.
- MEASURED: 3 s claim-status mix under the 05 decision rule.
- INFERRED: not yet. Confirmatory is the 22 s seed `110518`.

