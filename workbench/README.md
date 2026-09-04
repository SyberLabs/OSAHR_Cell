# Decision workbench (issue 13)

One auditable loop over the frozen Experiment 06 corpus:

```text
scenario JSON → validate → pin freeze/analysis checksums
    → rescore claim grammar → action license ⊥ claim license
        → JSON + HTML packet → replay
```

This is not a new simulator. It will not mint a licensed packet from an
attacker-supplied ensemble, from `claims.score` MCP input, or from a
scenario that is not in the evaluation corpus. Unknown cases fail loud.

## Command

From the repository root:

```bash
python -m workbench decide workbench/scenarios/03-long-outage.json --out /tmp/osahr-packet
python -m workbench replay /tmp/osahr-packet/decision.json
python -m pytest workbench/tests
```

## Scenario schema (`osahr_workbench_scenario_v0`)

Required JSON fields: `schema`, `id`, `name`, `operator_role`, `decision`,
`horizon_s`, `root_seed`, `seed_mix`, `baseline_policy`, `semantic_policy`,
`estimand`.

`seed_mix` must be exactly `["root", "scenario", "replicate"]`. Putting
`policy` in the seed is refused. `semantic_policy` must be `vault_gated`.
`scalar_semantic` is a comparison arm in the confirmatory record, not an
intervention policy: it still uses the degraded-fidelity edge the vault
forbids for `critical`.

## Licenses

| Claim status | Action license | Claim license | Recommendation |
|---|---|---|---|
| `admit`, oracle sign &lt; 0 | kernel | directed effect | keep baseline |
| `admit`, oracle sign &gt; 0 | kernel | directed effect | adopt vault-gated semantic |
| `hold_unresolved` | select | **denied** | act under hold; do not report sign |
| `reject` / `outcome_unknown` | withhold | denied | withhold |

Replay recomputes licenses from the pinned corpus. Editing the packet
does not grant a claim.

## Grades

Every packet carries KNOWN / MEASURED / INFERRED / PROPOSED. Real-network
calibration is always PROPOSED. Promoting it to MEASURED fails replay.

## Product thesis this slice tests

For a network/reliability engineer operating a RAN/MEC twin under
degraded capacity, OSAHR turns a named scenario into a human-pending
action and a replayable evidence packet, without licensing a directed
effect the ensemble withholds.

Owner: the packet format (`workbench/packet.py`). The kernel, Experiment
06 freeze, and Experiment 05 claim grammar stay owned where they are.
