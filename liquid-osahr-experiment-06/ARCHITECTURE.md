# Experiment 06 Architecture

## Composition

```text
telemetry KPM
    → AnLF load / outage (MCP tools, BoundaryHandle payloads)
        → OSAHR twin (DPO + thinning clocks; α=0 identity)
            → vault query only at route-task junctions
                → Experiment 05 claim status
                    → admit: fire legal match
                    → hold_unresolved: one NetworkBrain, load-penalty select
                    → reject | outcome_unknown: withhold + park refusal
```

Kernel state remains \(X=(G,B,R,\Theta,Z,t,n)\). No first-class \(H_t\) in the hash. AnLF does not call `Runtime` rewrite APIs. `park.request_rewrite` never bypasses DPO.

## Layers (do not collapse)

| Layer | Object | May rewrite \(G\)? |
|---|---|---|
| PKG vault | markdown + YAML `concept_id` | No (pattern-plane notes need a freeze to promote) |
| AnLF | `LoadLevel`, `AbnormalBehavior` | No (payloads only) |
| MTLF | `scripts/mtlf_refit.py` | No (off the event clock) |
| Junction | `route-task` Expr guard + pre-filter | No (filters matches) |
| Claims | 05 `score_claim` | No |
| Brain v1 | deterministic park controller | Request only |
| Kernel | typed DPO + clocks | Yes, after legality |

MCP “edges” are **control-plane tool ports**, not radio links and not LLM callers on every hyperedge.

## 6G schema extension

`Task.concept_id` is optional on the **experiment** schema (`osahr_cell/twin.py`). `osahr/schema.py` and 6G `build_schema` are not modified. AttributeSpec already allows a string field; the kernel is not the place to mint 6G vocabulary.

## Residual hypothesis

02B CfC is **not** retrained. \(H=\{0,0.25,0.5,1\}\) appears here as a **load-penalty mix** on the scalar semantic hazard so 05’s ensemble grammar can be scored. This is not an elected \(\alpha^*\) and is not claimed to be the 02B residual field.

## Files

- `vault/concepts/*.md` — `critical`, `background`, `outage`, `load`
- `osahr_cell/vault.py` — `admissible(task_kind, edge_name, outage)`
- `osahr_cell/anlf.py` — boundary payloads
- `osahr_cell/junction.py` — `route-task` gate
- `osahr_cell/mcp_tools.py` — JSON schemas
- `osahr_cell/brain.py` — v1, no LLM
- `scripts/run_experiment_06.py` — freeze / instrument / confirm / analyze
