# Research Basis for OSAHR 0.2

This document records the conceptual sources used while designing the 0.2 kernel. OSAHR does not claim to be a direct implementation of any one paper; it combines established ideas under one typed hypergraph-rewrite runtime and makes the boundary between exact semantics and engineering choices explicit.

## 1. Stochastic rewriting as a CTMC

Nicolas Behr, **“On Stochastic Rewriting and Combinatorics via Rule-Algebraic Methods”** (EPTCS 334, 2021; arXiv:2102.02364) develops stochastic rewriting in continuous-time Markov-chain terms and connects rewriting events, embedded jump chains, and pattern-counting observables.

OSAHR's occurrence-level generator viewpoint follows the same core idea:

```text
(L f)(X) = sum_(r,m) a_(r,m)(X) [f(T_(r,m)(X)) - f(X)]
```

Engineering consequence: stochastic activity belongs to *enabled rule occurrences*, not merely rule names.

## 2. Incremental graph-query maintenance

Beyhl et al., **“Localized RETE for Incremental Graph Queries”** (arXiv:2405.01145) studies localized incremental maintenance of graph-query matches and motivates restricting recomputation to graph regions affected by edits.

OSAHR adopts the locality principle but keeps its own conservative proof boundary:

- the exhaustive matcher remains the oracle;
- ordinary local rules are maintained from entity dependencies and typed anchors;
- graph conditions fall back to exhaustive recomputation when remote extension changes are possible;
- randomized differential execution is used to test equivalence.

This is intentionally less ambitious than claiming every graph condition can be localized safely.

## 3. Modified next-reaction scheduling

David F. Anderson, **“A modified Next Reaction Method for simulating chemical systems with time dependent propensities and delays”** (J. Chem. Phys. 127, 2007; arXiv:0708.0370) formulates reaction channels using independent unit-rate Poisson processes and internal times.

OSAHR uses that random-time-change view for structural occurrence channels:

```text
channel identity = (rule_id, match_id)
internal time     = integral a_i(X_s) ds
threshold         = cumulative Exp(1) arrivals
```

When a graph delta leaves an occurrence untouched, its internal clock is left untouched. A channel that disappears loses its residual clock; a later structural reappearance is treated as a birth.

## 4. Exact simulation under dynamic/time-varying propensities

Voliotis et al., **“Stochastic Simulation of Biomolecular Networks in Dynamic Environments”** (PLoS Comput Biol 2016; arXiv:1511.01268) presents Extrande, a thinning-based exact approach for systems with dynamically varying propensities under an appropriate dominating process.

OSAHR's time-varying backend similarly requires a finite-window dominating hazard contract and uses rejection thinning. The exact engineering contract is intentionally strict:

- the user/model declares the bound;
- the runtime verifies the actual candidate hazard never exceeds it;
- a violated bound aborts rather than silently biasing the trajectory.

OSAHR additionally separates event-generation exactness from likelihood exactness. A closed-form per-occurrence integrated hazard may be declared for the latter; otherwise path-likelihood analysis refuses to invent a survival term.

## 5. DPO versus SqPO deletion semantics

Behr, **“Sesqui-Pushout Rewriting: Concurrency, Associativity and Rule Algebra Framework”** (EPTCS 309, 2019; arXiv:1904.08357) emphasizes the semantic distinction between DPO deletion, where incident edges must be explicitly accounted for, and SqPO/SPO-style deletion in unknown context.

OSAHR 0.2 chooses DPO semantics only. This matters probabilistically: a base pattern embedding that violates the DPO dangling condition is excluded from the enabled stochastic occurrence set *before* rate aggregation.

SqPO is intentionally listed as a future explicit backend rather than silently implemented as cascading deletion.

## 6. Design choices that are OSAHR-specific

The following are engineering/specification decisions of this implementation rather than claims copied from the cited work:

- stable `(namespace, counter)` entity IDs;
- a deterministic BLAKE2-priority treap for dynamic weighted sampling;
- domain-separated xoshiro256** random streams;
- dynamic rule repertoire included directly in state hashes;
- safe runtime meta-rewriting restricted to precompiled typed templates;
- explicit adaptive parameter constraint/projection contracts;
- a separate thinning planner cursor so stochastic peeks do not mutate authoritative simulation time;
- strict reference-vs-incremental differential verification mode.

## 7. Future research directions

A next research-grade sequence would be:

1. formal automorphism-orbit occurrence semantics;
2. SqPO backend with separately tested stochastic generator semantics;
3. nested-condition incremental discrimination networks;
4. delayed structural events / generalized semi-Markov scheduling;
5. critical-pair and rule-interference analysis;
6. moment-closure / pattern-observable analysis inspired by rule-algebraic methods;
7. stochastic message-channel composition and synchronized component rules;
8. rare-event trajectory methods and likelihood-ratio sensitivity estimators.

Each item should enter as a named semantic mode with differential/statistical tests rather than as an implicit optimization.
