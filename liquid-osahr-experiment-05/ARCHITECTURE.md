# Experiment 05 Architecture

## Composition

```text
telemetry
    → instance claims (what may be said)
        → OSAHR twin under each α ∈ H (legal rewrites)
            → DYNDIV residual (width / split / withhold)
                → admit | hold_unresolved | reject | outcome_unknown
```

The kernel state remains \(X=(G,B,R,\Theta,Z,t,n)\). Trust is not in the state hash. \(H_t\) is not first-class. Residuals do not rewrite \(G\).

Experiment 05 lives in the SGR slot: it executes legal twins. It does not extract a TOK LLM HLMG. It imports the **edge grammar** (`response_activation` vs `response_effect`) and the **layer split** (instance claim vs pattern promotion).

## Data flow

```text
02B residual checkpoint (frozen)
        │
        ├─► 04 confirmatory CSV, h=3 s  ──► instrument check (labeled)
        │
        └─► freeze claims.py + protocol.py
                │
                ▼
            05 confirmatory seed 110518, h=22 s
                │
                ▼
            ensemble Δ_α, no α*
                │
                ▼
            claim status table
```

## Invariants

1. Every scored scenario has oracle plus all four residual hypotheses. Missing arms are errors, not \(\alpha=0\) fill-ins.
2. Replicates are averaged inside `(regime, scenario, model, policy)` before \(\Delta\).
3. Physical and runtime seeds depend on `(root_seed, scenario, replicate)`, not on model or policy (02B `run_counterfactual`).
4. `α=0` is the mechanistic field, not residual-at-zero arithmetic.
5. The answering artifact is a status, never a selected \(\alpha\).
6. 04 `T_strict` and global \(\alpha=1\) appear only as illegal-promotion foils.

## Why 22 s

TwinConfig's default horizon is 22 s. Experiments 02B confirmatory, 03, and 04 evaluated at 3 s, where many oracle \(\Delta=0\). TOK's probe-window result is the warning: changing the window changes which motifs are visible. 05 uses the model's native horizon rather than inventing a third assay. If 22 s is still sparse, that is competing explanation (4), not a license to retune \(h\) on the confirmatory seed.
