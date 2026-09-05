# SyberLabs: evidence before expansion

Status: proposed operating framework plus an implemented OSAHR development probe.
Owner of product/funding decisions: SyberLabs director; technical and study
execution owners must be named before each funded phase. This document does not
reassign issue #13 or rewrite historical experiment conclusions.

## Product direction

**Hypothesis:** OSAHR can make changing, stochastic organizational mechanisms
executable against an ontology snapshot, so an analyst can compare interventions
without rebuilding a bespoke simulator for every structural change.

The ontology describes what exists. OSAHR describes an explicit proposed law of
how it changes. A simulation estimates consequences **conditional on that law**.
It does not infer the law's truth, discover causality, or authorize a real action.

This is a proposed component **inside a Foundry-type ontological system**, not a
Foundry competitor. An organization's adapter supplies stable object identities,
types, relationships, properties and a versioned snapshot. A separately versioned
model supplies hazards and rewrite rules. Scenario execution returns projected
events, observables, uncertainty and provenance. An external authorization layer
decides whether any operational action may follow. Simulation must not mutate
source-of-truth objects or turn hypothetical results into observed facts.

Reuse RDF/Turtle and RDFLib now. SHACL is a possible later validation interface;
OWL reasoning, a new graph database, broad schema auto-mapping, tenant security,
a generic workflow engine and multi-agent orchestration are out of scope.
Data/action/security interfaces in [Foundry's Ontology](https://www.palantir.com/docs/foundry/ontology/overview)
are a conceptual reference, not capabilities that RDF alone provides.

## What we are trying to falsify

| Claim | Comparator and evidence | Failure / consequence |
|---|---|---|
| Correct execution of a declared mechanism | Independent SSA and analytical oracle; full finite transition generator | Any mismatch blocks performance interpretation |
| Better raw simulation efficiency | Same law, workload, outputs and stopping condition; actual simpler alternatives | A slower result defeats a speed claim for that workload; report it |
| Lower cost of changing a useful model | Independently scored, counterbalanced model-change tasks against maintained alternatives | No practical effort reduction means use the simpler tool |
| Useful organizational decisions | Held-out real observations/interventions and the user's current decision process | Miscalibration or no decision improvement blocks product promotion |
| RISE solves an external user's problem | Independent sessions against the user's current reading workflow | Recurrent failure or no concrete reason to switch means simplify, reposition or stop |

Neither a repository, a demo, test coverage nor a mathematically well-defined
process is evidence of customer value. No theoretical novelty or general
efficiency superiority is established by this framework.

## OSAHR execution sequence

### A — implemented cheap control

[The executable protocol](../benchmarks/ontology/README.md) loads a local RDF
snapshot, compiles actual typed hypergraph rules, and independently simulates
route failure/repair using direct SSA. The rules delete/recreate availability
edges. All eight base states and their outgoing transitions are checked against
the independent generator. First-jump statistics, negative controls and trace
replay guard the harness. Raw timings include preparation and execution costs.

This workload is deliberately easy and structurally shallow. A simple simulator
is expected to be faster. Passing it says the adapter and narrow model are
coherent; it says nothing about an advantage on coupled topology or real data.
No kernel optimization should precede learning whether anyone needs the proposed
mechanism layer. There is no Foundry dependency and no claim of Foundry fidelity.

### B — next decision: one user, one decision, one harder workload

Before further platform work, a domain owner supplies three recent decisions
with their current artifacts, effort and pain. Select one where *changing
relationships or constraints* actually matters. A candidate, not a validated
market: rerouting work after route/service loss with limited repair capacity.
If a spreadsheet or a straightforward event simulator is sufficient, keep it.

Then freeze a small test contract:

1. **Data:** approved read-only snapshot, units, version, provenance, train/test
   split and intervention assumptions. Separate measured rates from invented
   rates. No live organizational credentials in the harness.
2. **Model:** coupled topology or contention; illegal-action conditions and
   requested outputs. Hand-check a small reachable state space. Include controls
   with no topology changes and a simpler exact model wherever available.
3. **Alternatives:** existing user workflow, independent direct SSA, and at least
   one maintained external simulator suited to the task (evaluate SimPy for
   event workflows, Mesa for agent-based cases; do not add both by default).
   Freeze versions, implementations and fairness requirements before timing.
4. **Simulation experiment:** equal simulation horizon and estimator accuracy,
   independent trajectories; analytical/exhaustive oracle where possible,
   held-out data where not. Report uncertainty, bias and calibration, not just
   mean output. Choose sample size from desired precision and a pilot variance,
   then reserve new seeds and cases for the untouched comparison.
5. **Engineering experiment:** have evaluators implement the same three unseen
   changes, such as route addition, shared repair limit and a forbidden reroute.
   Counterbalance tool order and record expertise, time to passing independent
   acceptance tests, defects and model-specific code. Log training/adapter costs
   separately. A single AI author comparing its own implementations is not an
   independent productivity study.
6. **Costs:** wall time (median/p95 when enough repetitions exist), peak memory
   in separate instrumented runs, model-update effort and audit/replay capability.
   Decompose graph matching, rewrite/copy/hash and scheduling costs only after
   the end-to-end result identifies a bottleneck. Count failed/time-out trials.

Suggested **decision thresholds to approve before Phase B**, not observed wins:
at least 30% less median model-change effort with no more correctness defects,
and no more than 2x end-to-end runtime versus the best accepted simple baseline,
while also meeting the domain owner's absolute latency/memory budget. If an
audit capability is the value, test that separately and include the comparator's
cost to provide the required guarantee. If no benefit survives these gates,
retain OSAHR as research infrastructure or archive this product hypothesis.
These cutoffs need owner approval; they are not statistically justified constants.

### C — only after B earns it

Validate a real user's decision quality and integration burden. Implement a
read-only adapter to their actual ontology, not necessarily Foundry. Foundry
contract tests, authorization and operational action execution require real
access and separate approval. A fake adapter cannot establish these properties.

## RISE: external study, not internal applause

Use the [contractor brief](RISE_EXTERNAL_VALIDATION_BRIEF.md). Start with one
experienced human moderator and three independent adults for a diagnostic pilot.
Assess the product alongside an ordinary reading workflow; pay equally for
negative findings. A larger effectiveness study requires a specified outcome,
power/precision planning and a separate decision to fund it.

No researcher has been engaged or paid by creating these documents. Outreach,
contractor selection, fees and access await the director's budget/channel
approval. RISE's device, acoustic and privacy release gates remain separate.

## Reusable decision record — one per bet, not one more platform

Copy this checklist into an existing issue. Keep one accountable person and one
next falsifiable test. Do not create another service to track it.

- Beneficiary and repeated job; evidence they already have the problem.
- Current alternative and why adopting it is insufficient.
- Smallest differentiated claim; explicit null hypothesis.
- Owner, timebox and maximum spend; what is authorized now.
- Frozen inputs, acceptance test, baseline and stop rule.
- Evidence status: proposed / implemented / measured / independently validated.
- Raw results and adverse outcomes, exact revision and relevant limitations.
- Decision: continue narrowly / change hypothesis / adopt alternative / stop.

Keep study identities, recordings, private customer data, quotes and contracts
outside public repositories. Publish only approved anonymized findings. Do not
turn an unperformed gate green because a plan or test harness exists.
