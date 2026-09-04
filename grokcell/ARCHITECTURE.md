# GrokCell surface architecture

## Composition

```text
agent tool call
    -> bus (priority, seq)
        -> vault constraints (critical_module, unverified, spawn_bot)
            -> claim grammar: admit | hold_unresolved | reject | outcome_unknown
                admit: ExternalEvent on Slot, then kernel assemble-component
                hold: stay in the hold queue; park.request may resolve
                reject | unknown: vault note; no rewrite
```

Kernel state remains X = (G, B, R, Theta, Z, t, n). No first-class H.
The bus does not call RewriteEngine. assemble-component is a DPO rule.
park.request never bypasses DPO.

## Layers (do not collapse)

| Layer | Object | May rewrite G? |
|---|---|---|
| Messages | typed control-plane records | No |
| Vault | markdown + concept_id | No |
| Bus | priority + legality | No |
| ODA | spawn lock; skill on MOUTH | No |
| Park | license at hold | Request only |
| Kernel | assemble-component | Yes, after legality |

## Construction schema

Vertex types: Cell, Slot, Component.
Edge type: PartOf.
One proposal slot, bound to boundary handle `proposal`.
Sequential construction: one admit at a time; depends_on is a bus
gate, not a 6G occurrence type.

## Relation to 08

This is the 08 loop as a GrokCell runtime: one artifact type
(Component) on a checkable twin, park as Stabilize, one mouth.
It is not a confirmatory experiment and it is not an LLM SKU.
