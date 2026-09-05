# OSAHR 0.2 Architecture and Semantic Invariants

## 1. Authoritative augmented state

The authoritative committed state is

```text
X = (G, B, R, Theta, Z, t, n)
```

where:

- `G` is a finite typed directed hypergraph;
- `B` is typed open-boundary state;
- `R` is the current active rule repertoire;
- `Theta` is the adaptive parameter mapping;
- `Z` is explicit sufficient-statistic/history memory;
- `t` is simulation/observation time;
- `n` is the committed event index.

Any historical quantity consulted by a future transition law must live in `Theta` or `Z`. The graph alone need not be Markov; the augmented state used by the scheduler must be.

Dynamic rule hashes are part of the canonical state identity. A meta-transition that changes `R` is therefore a genuine state transition, not external configuration mutation.

## 2. Module map

| Module | Responsibility |
|---|---|
| `schema.py` | Types, subtype closure, attributes, hyperedge port signatures, invariants |
| `graph.py` | Stable entity store, explicit incidences, typed indices, canonical graph state, deltas |
| `model.py` | Model identity, canonical hash, runtime resource contracts |
| `pattern.py` | LHS patterns, RHS templates, graph conditions, rules, hazard contracts |
| `expr.py` | Restricted deterministic expression language |
| `matcher.py` | Exhaustive injective typed matching oracle |
| `indexed_matcher.py` | Incidence-constrained enumeration of the same embedding relation |
| `incremental.py` | Exact dependency-indexed localized match maintenance |
| `rewrite.py` | Atomic DPO applicability and rewrite transaction execution |
| `occurrence.py` | DPO-valid stochastic channels, hazards, bounds/integrals, weighted activity indices |
| `weighted.py` | Deterministic dynamic weighted order-statistics tree and one-shot inverse-CDF selection |
| `schedulers.py` | Modified-next-reaction clocks, thinning planner, thinning audit state |
| `adaptive.py` | Adaptive parameter contracts and reusable sufficient-statistic updates |
| `meta.py` | Typed finite precompiled rule-template instantiation and repertoire mutation |
| `runtime.py` | Authoritative event loop, scheduler selection, queues, state hashes, snapshots/replay |
| `commit.py` | Committed event publication invoked from Runtime (internal, external, adaptation, meta) |
| `analysis.py` | Path likelihood, deterministic ensembles, first passage |
| `boundary.py` | Typed handles and external/output events |
| `composition.py` | Structural open-model composition |
| `observables.py` | Deterministic observables |
| `causal.py` | Conservative event dependency reconstruction |
| `persistence.py` | Trusted checkpoints and canonical audit exports |

## 3. Typed directed hypergraph

A graph is represented as

```text
G = (V, E, I, tau_V, tau_E, alpha_V, alpha_E)
```

with explicit incidences

```text
(edge_id, side, role, ordinal, vertex_id)
```

rather than only adjacency arrays. This makes direction, repeated endpoints, role identity, and ordered/unordered role semantics explicit.

Graph-level indices include vertices/edges by type and incidences by vertex. Entity IDs are stable deterministic `(namespace, counter)` identities.

## 4. Rule semantics

A Python `Rule` encodes a typed linear DPO span through symbolic keys:

```text
L-only key  : delete
L ∩ R key   : preserve
R-only key  : create
```

Preserved vertices keep their type. Preserved edges keep both type and complete incidence structure; reconnection must be modeled as delete+create.

A match is an injective typed embedding from `L` into `G`. Match IDs depend only on the rule identity and symbolic-key -> entity-ID maps, never discovery order or graph epoch.

### 4.1 Enabled occurrence invariant

A stochastic occurrence exists iff all of the following hold:

1. the base typed match exists;
2. all PAC/NAC conditions hold;
3. the guard is true;
4. DPO dangling conditions hold;
5. boundary deletion/gluing constraints hold;
6. the hazard evaluates to a finite nonnegative number.

Critically, DPO applicability is checked before stochastic activity is constructed. A dangling-invalid match is not assigned a rate and cannot steal event-selection probability.

## 5. Atomic internal rewrite transaction

`RewriteEngine.apply` operates on cloned graph/boundary/adaptive state and publishes only the completed result.

Order:

1. verify rule/match identity and graph epoch;
2. DPO dangling validation;
3. boundary gluing validation;
4. remove explicitly deleted edges;
5. remove explicitly deleted vertices;
6. create RHS-only vertices with deterministic event-scoped IDs;
7. update preserved vertex attributes;
8. create RHS-only edges;
9. update preserved edge attributes;
10. apply boundary effects;
11. validate graph and boundary invariants;
12. evaluate adaptive assignments from one immutable post-rewrite/pre-adaptation view;
13. atomically apply adaptive assignments;
14. derive outputs from committed candidate state;
15. increment graph epoch once;
16. return a complete `RewriteResult` and deltas.

Any exception before publication discards the candidate state.

## 6. Exhaustive matcher as semantic oracle

`Matcher.find_rule_matches` is deliberately simple and complete. Optimization is not trusted as a new semantics.

Development mode can enable:

```text
incremental_verify = true
```

which checks after every incremental refresh:

```text
sorted(incremental_match_ids) == sorted(reference_match_ids)
```

A mismatch is release-blocking.

Verification also compares canonical variable bindings: identical match IDs
alone cannot detect bindings that would change guards or hazards. The incremental
backend now enumerates through `IndexedMatcher`, using existing type/incidence
indices to constrain partial assignments while retaining complete incidence and
attribute checks. The exhaustive backend remains unchanged. See
[the correctness argument, complexity bounds, and reproduction commands](docs/INCIDENCE_MATCHING.md).

## 7. Incremental match maintenance

### 7.1 Dependency signature

For each rule the compiler records:

- vertex type requirements, including whether subtypes are accepted;
- edge types;
- whether PAC/NAC graph conditions exist;
- whether expressions read parameters or memory.

Delta relevance uses the schema compatibility relation, not raw string equality, so a concrete subtype edit correctly invalidates a pattern that expects a supertype.

### 7.2 Cache

Each rule cache stores:

```text
match_id -> Match
entity_id -> {match_ids}
```

A local graph delta builds an affected neighborhood from:

- created/deleted/updated entities;
- endpoints of created/deleted edges.

Cached matches touching the neighborhood are invalidated and rematched from typed anchors. The result is:

```text
MatchDelta(added, removed, revalidated)
```

`revalidated` means the mapping existed before and after but local context changed, so DPO applicability and hazard must be reconsidered.

### 7.3 PAC/NAC fallback

A remote graph edit can create or destroy an extension satisfying a PAC/NAC without touching entities in the base match. Therefore a relevant edit for a conditional rule triggers exhaustive recomputation. This is a deliberate exactness fallback.

### 7.4 Epoch locality

Untouched cached `Match` objects retain the epoch when last structurally checked. They are not globally re-stamped after every graph mutation. Immediately before an occurrence is actually fired, runtime creates an equivalent mapping with the current graph epoch and the rewrite engine performs normal atomic revalidation.

This distinction is essential for sparse next-reaction scheduling: an unrelated graph commit does not manufacture a false stochastic-channel change.

## 8. Dynamic weighted activity index

Activities are indexed in two levels:

```text
rule_id -> total rule activity
rule_id -> (match_id -> occurrence activity)
```

`WeightedIndex` is a deterministic treap whose priority is a stable BLAKE2-derived function of the key, not Python's process-randomized hash. Each node stores subtree activity and size.

Expected operations:

```text
insert/update/remove: O(log n)
inverse-CDF selection: O(log n)
total activity: O(1)
```

Tree in-order semantics are canonical by key, independent of insertion order.

## 9. Direct SSA

For piecewise-constant hazards `a_i(X)`:

```text
A = sum_i a_i
Delta t = -log(U_wait) / A
P(i | jump) = a_i / A
```

OSAHR draws separate domain-keyed random values for waiting time, rule selection, and match selection. A deterministic event at or before the proposed jump preempts it and its proposal draws are marked discarded.

An observation horizon before a proposed event does not resample the proposal.

## 10. Modified next-reaction scheduler

Each occurrence key owns:

```text
hazard a_i
internal time T_i
next unit-Poisson threshold P_i
last update time
planned physical firing time
```

Between state changes:

```text
T_i(t + dt) = T_i(t) + a_i * dt
```

and firing occurs when `T_i` reaches `P_i`.

When an occurrence's hazard changes, the scheduler first advances its internal clock to current time using the old hazard, updates the hazard, and replans from its remaining internal threshold. Unchanged channels are not touched.

After firing, the threshold is incremented by a fresh independent `Exp(1)` variate. Disappearing channels lose residual clocks; reappearing channels are births with fresh thresholds.

The minimum planned time is held in a lazy versioned heap.

## 11. Time-varying hazards by exact thinning

A continuously time-varying hazard may depend on absolute `time`. It must supply `hazard_upper_bound`, evaluated at a planner window start with the finite `horizon`.

For total dominating activity `B` over a window:

1. propose a candidate from `Exp(B)`;
2. if outside the window, cross the window and continue;
3. evaluate actual total activity `A(t_c)` at candidate time;
4. verify every actual occurrence hazard is <= its declared bound;
5. accept with probability `A(t_c)/B`;
6. choose the accepted occurrence proportionally to its actual hazard.

The thinning planner owns a separate cursor. Planning or peeking does not change authoritative `Runtime.time`.

### 11.1 Likelihood integral contract

A time-dependent rule may additionally supply `hazard_integral`, interpreted as the exact integral of that occurrence's frozen-state hazard from `time` to `horizon`.

The planner accumulates total survival activity over rejected candidates, crossed windows, and observation horizons. If every active time-dependent rule has an integral contract, a committed event carries exact `survival_integral`; otherwise event generation remains exact while likelihood metadata is explicitly incomplete.

## 12. Adaptive-state contracts

`AdaptiveRegistry` validates initial and post-update parameter values.

Constraint modes:

```text
FREE
POSITIVE
NONNEGATIVE
BOUNDED
PROBABILITY
```

Policies:

```text
STRICT   -> reject invalid update
PROJECT  -> deterministic explicitly declared projection
```

All assignments in a single adaptation clock are evaluated against the same pre-update mapping, preventing mutation-order dependence.

## 13. Meta-rewriting

`RuleTemplate` contains an already compiled prototype plus typed `MetaParameter` declarations. Runtime instantiation only substitutes validated data into `rule.meta` and assigns a new stable rule ID/version.

Allowed repertoire operations:

```text
INSTANTIATE
ENABLE
DISABLE
REMOVE
```

Template instance limits are enforced. The repertoire is included in canonical runtime state hashes, snapshots, and delta replay.

Arbitrary runtime source compilation is forbidden.

## 14. Path likelihood

For a trajectory conditioned on exogenous deterministic events:

```text
log p(omega) = sum_internal log a_e(X_t) - integral A(X_s,s) ds
```

Direct SSA and modified-next-reaction records have exact piecewise-constant survival terms. Thinning records have exact survival terms only when the analytic integral contract is complete.

`path_log_likelihood` refuses records lacking exact survival metadata rather than approximating it from sampled thinning candidates.

## 15. Deterministic ensembles

Replicate seed `j` is derived from a root seed and the stable domain string `ensemble:j`. Ensemble execution is serial in the reference layer so numerical results do not depend on worker scheduling. External parallelism can partition replicate IDs without changing seed identity.

## 16. Determinism contract

A trajectory is fixed by:

```text
model hash
initial canonical graph
root seed
runtime semantic version
scheduler backend
matcher backend
deterministic external events
deterministic scheduled adaptations
deterministic meta-events
```

Additional invariants:

- canonical sorted rule/match semantics;
- `float.hex` canonical float representation;
- xoshiro256** with deterministic SplitMix64 seeding;
- domain-separated random streams;
- deterministic entity allocation;
- deterministic external-event ordering;
- no dependence on Python dictionary insertion order for stochastic selection.

## 17. Snapshots and replay

Snapshots preserve:

- graph, boundary, active rules, parameters, memory;
- simulation and last-commit times;
- event index;
- all RNG stream states;
- deterministic queues;
- pending internal proposal;
- next-reaction channels/heap/audit draws;
- thinning planner audit/cursor;
- output events and run identity.

Delta replay verifies canonical pre-state and post-state hashes for each committed event. Dynamic meta-rule payloads are restored during in-memory replay.

## 18. Resource and failure safety

Hard limits cover:

- events;
- vertices;
- edges;
- incidences;
- matches per rule;
- total stochastic activity;
- simulation time;
- event density in a tiny time window;
- thinning planning windows;
- template instance counts.

Exact modes never silently:

- truncate a match relation;
- clamp a hazard;
- insert a minimum stochastic timestep;
- switch to tau leaping;
- accept a violated thinning bound;
- replace a missing hazard integral with a numerical guess.

## 19. Verification strategy

The test suite combines:

1. hand-computed graph/rewrite cases;
2. stochastic distribution checks;
3. replay and snapshot invariants;
4. adversarial DPO eligibility cases;
5. incremental-vs-reference differential execution;
6. subtype invalidation cases;
7. time-varying integrated-hazard transforms;
8. meta-repertoire state/replay tests;
9. adaptive constraint failure tests.

The optimized matcher is never its own oracle.

## 20. Semantics deliberately not implemented in 0.2

The following would change the formal process and require their own explicit backend/specification:

- automorphism-orbit occurrence counting;
- SqPO/SPO cascading deletion;
- non-injective matches;
- delayed rule completion / semi-Markov clocks;
- synchronized cross-runtime atomic rewrites;
- stochastic message channels;
- approximate accelerated simulation.

They are not emulated by ad hoc behavior in the current kernel.
