# Experiment 03 Architecture

## 1. What is new

OSAHR 0.2 and Liquid-OSAHR 02B already expose a scalar residual trust \(\alpha\). Experiment 03 adds an **answering policy** over that scalar:

```text
(q, I, r, h)  →  α  →  02B twin with that residual trust
```

Neural models still estimate likelihood. Typed graph rewriting still determines possibility. The scheduler still realizes the declared process. \(T\) is epistemic authority: how much residual correction is licensed **for this query**.

## 2. Why T is not another learned rate

02B showed that predictive NLL and intervention-effect recovery disagree. A second neural map \(\alpha = f_\theta(q, I, r, h)\) would repeat that failure mode. Experiment 03 therefore uses an explicit, auditable lookup:

1. structural cell key \((q, I, r)\);
2. 02B intervention objective inside the cell;
3. conservative default \(\alpha = 0\) off the calibrated support.

That is a trust **field**, not a trust **network**.

## 3. Module map

| Module | Responsibility |
|---|---|
| `liquid_osahr03.trust` | `QueryContext`, `TrustField`, cell fitting, fallback cascade |
| `liquid_osahr03.calibration` | Read frozen 02B calibration JSON only |
| `liquid_osahr03.confirmatory` | Read 02B confirmatory trajectories; select arms; LOSO |
| `liquid_osahr03.statistics` | Scenario bootstrap and paired deltas |

The 02B runtime is not modified. Vendored OSAHR is not copied.

## 4. Invariants

1. `select` never returns an \(\alpha\) outside the declared grid.
2. Fitting functions accept calibration structures only; they have no confirmatory path argument.
3. Unknown cells return \(\alpha = 0\) with an explicit source tag, not a silent neighbor interpolation.
4. `alpha = 0` retains 02B's meaning: exact mechanistic identity.
5. Query-conditioned selection is an answering policy. It does not mutate rewrite legality.

## 5. Relation to the kernel augmented state

Kernel 0.2 state remains

```text
X = (G, B, R, Θ, Z, t, n)
```

Liquid-OSAHR layers \(H_t\) outside the kernel. \(T\) is **not** part of \(X_t\). It is an operator-facing choice of which residual field to instantiate before a counterfactual ensemble. Putting \(T\) inside the stochastic state would make trust a physical process, which this experiment does not claim.
