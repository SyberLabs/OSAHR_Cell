# Experiment 05 Protocol — Residual-Hypothesis Claim Status

**Status:** formulated and frozen. Confirmatory long-horizon trajectories are not part of formulation.

**Does not overwrite 02B, 03, or 04.** Those remain the cited records for residual identity, query-conditioned \(T\), and same-horizon non-transport.

This experiment changes the **object**. It does not fit another \(T(q,r)\).

## Question

At a horizon long enough that oracle policy contrast can be expressed, which semantic-versus-throughput **effect claims** are invariant across the residual-hypothesis set

```text
H = {0, 0.25, 0.5, 1.0}
```

and which must be withheld?

## Hypothesis

A point lookup \(T \to \alpha^*\) is the wrong answering object. The operational output is a claim status:

```text
admit | hold_unresolved | reject | outcome_unknown
```

Competing explanations for the long-horizon confirmatory (seed `110518`, \(h=22\) s), to be scored only after freeze:

1. **Window, not object.** At \(h=3\) s most claims are `outcome_unknown`; at \(h=22\) s a substantial expressed subset becomes sign-robust across \(H\) (`admit`).
2. **Residual is load-bearing.** Even when oracle \(\Delta\) is expressed, signs flip across \(\alpha\) (`hold_unresolved` dominates the expressed set). Then a point \(T\) would still be required, and 04 already showed that \(T\) does not transport.
3. **Structural miss.** Hypotheses agree with each other and disagree with oracle (`reject`): the mixer family cannot support the estimand.
4. **Still sparse.** Oracle contrast remains unexpressed at the twin's native horizon. Then this surrogate cannot license trust-selected intervention claims, regardless of \(\alpha\).

The \(h=3\) s 04 confirmatory table is an **instrument check** of the scorer, not a 05 confirmation. The scorer is expected to return mostly `outcome_unknown` there.

## Formal object

An instance-plane intervention claim, HLMG-shaped, not a simulator and not a pattern-plane promotion:

| HLMG analogue | OSAHR-05 field | Meaning |
|---|---|---|
| `response_activation` | `response_activation` | Policy-conditioned process counts differ (events, outages, handovers, reroutes) |
| `response_effect` | `effect_expressed` | Oracle \(\lvert\Delta\rvert > \varepsilon\) on the estimand |
| `unobserved_response_outcome` | `activation_without_effect` | Activation with no expressed estimand contrast |
| epistemic status | `status` | `admit` / `hold_unresolved` / `reject` / `outcome_unknown` |

Residuals are DYNDIV: they may widen, split, or withhold a claim. They must not rewrite the mechanistic graph and must not elect a single \(\alpha^*\).

```text
q ∈ {goal_utility_ratio, critical_success_rate, mean_latency}
I = do(semantic) vs do(throughput)
Δ = mean_q(semantic) − mean_q(throughput)   # replicates averaged first
sign(x; ε) = +1 if x>ε, −1 if x<−ε, else 0
```

Latency \(\Delta\) is a contrast direction, not “semantic is better.”

### Decision rule (frozen)

Require every \(\alpha \in H\) to have a realized \(\Delta_\alpha\). Incomplete ensembles are a protocol error, not a fallback. Let \(S=\{\mathrm{sign}(\Delta_\alpha;\varepsilon):\alpha\in H\}\).

1. If \(\mathrm{sign}(\Delta_{\mathrm{oracle}};\varepsilon)=0\): **`outcome_unknown`**.
2. Else if \(S=\{0\}\): **`reject`**. Every residual hypothesis is silent on an expressed oracle contrast.
3. Else if \(S\) is not a singleton \(\{s\}\) with \(s\in\{-1,+1\}\): **`hold_unresolved`**.
   - Mixed \(\{0,+1\}\) or \(\{0,-1\}\): some hypotheses do not express the contrast.
   - Mixed \(\{+1,-1\}\) (with or without \(0\)): ranking flip.
4. Else if that common \(s\) equals \(\mathrm{sign}(\Delta_{\mathrm{oracle}};\varepsilon)\): **`admit`**.
5. Else: **`reject`**. The ensemble agrees on a directed effect and disagrees with oracle.

### Illegal promotion (secondary, not an answering policy)

A point selector \(\alpha^*\) (04 `T_strict` cell, or global \(\alpha=1\)) **illegally promotes** when it would report a directed effect whose sign matches oracle, while the ensemble status is `hold_unresolved` or `reject`.

That is the 04 failure mode as an HLMG exclusion: a pattern-looking cell promoted off an instance table.

## Frozen constants (declared before confirmatory execution)

| Quantity | Value |
|---|---|
| Residual checkpoint | 02B `artifacts/residual_cfc.pt` (unchanged) |
| Horizon \(h\) | **22.0 s** (TwinConfig native; not the 3 s confirmatory assay) |
| Grid \(H\) | \(\{0, 0.25, 0.5, 1.0\}\) |
| \(\alpha=0\) | exact `mechanistic` field |
| Intervention | semantic vs throughput |
| Confirmatory root seed | `110518` |
| Regimes | id, high_mobility, high_stress, **weak_channel** |
| Scenarios × replicates | 6 × 2 |
| \(\varepsilon\) primary | `0.0` (strictly nonzero) |
| \(\varepsilon\) sensitivity | `0.02` on all three estimands |
| Independent unit | physical scenario |
| Claim grammar | `osahr05_claim_v0` in `liquid_osahr05/claims.py` |

There is **no calibration split** and **no freeze of \(T\)**. Freeze is a checksum of the claim grammar plus these constants, written to `artifacts/FROZEN.json` before confirmatory trajectories exist.

The 04 confirmatory seed `880419` is used only for the labeled instrument check.

## Endpoints

Primary estimand: `goal_utility_ratio`.

Primary confirmatory endpoints (after freeze, new seed, \(h=22\)):

- `unknown_rate`: fraction of scenarios with status `outcome_unknown`
- `expressed_robust_rate`: among expressed scenarios, fraction with status `admit`
- `expressed_hold_rate`: among expressed, `hold_unresolved`
- `expressed_reject_rate`: among expressed, `reject`

Secondary: the other estimands; \(\varepsilon=0.02\); width \(\max_\alpha\Delta_\alpha-\min_\alpha\Delta_\alpha\); illegal-promotion rate of 04 `T_strict` and of global \(\alpha=1\); activation-without-effect rate.

Instrument-check endpoints (04 table, \(h=3\), labeled): the same fractions. Success of the *instrument* is a high `unknown_rate`, not a winner \(\alpha\).

## Failure criteria

- Selecting or freezing an \(\alpha^*\) as the 05 answering object invalidates the experiment.
- Fitting \(T\) from 05 confirmatory rows invalidates the experiment.
- Running confirmatory before `artifacts/FROZEN.json`, or after changing `protocol.py` / `claims.py` without a new freeze, invalidates confirmation.
- Treating the 04 instrument check as a 05 confirmation invalidates the claim.
- A real-network efficacy claim is out of scope. Real RAN has no oracle \(do(\cdot)\) labels; it is a later factual-shadow question.

## Exactness boundary

OSAHR thinning is exact relative to declared bounded hazards. The RAN layer remains a standards-informed surrogate. Longer horizon changes the **assay window**, not the physics.
