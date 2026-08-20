# Changelog

## 0.2.0

### Added

- exact incremental match cache with typed dependency signatures;
- local `MatchDelta` maintenance and PAC/NAC reference fallback;
- DPO applicability filtering before stochastic activity aggregation;
- deterministic dynamic weighted order-statistics tree;
- modified-next-reaction scheduler with independent internal Poisson clocks;
- exact finite-window thinning backend for time-varying hazards;
- optional exact integrated-hazard contracts for thinning path likelihoods;
- separate thinning planner cursor; peeking no longer advances authoritative time;
- adaptive parameter scopes, constraints, and explicit projection policies;
- reusable exponential, eligibility, and Robbins-Monro update primitives;
- safe precompiled typed `RuleTemplate` meta-rewriting;
- dynamic rule repertoire in canonical runtime state hashes;
- exact path log-likelihood analysis;
- deterministic ensemble and first-passage utilities;
- scheduler state in snapshots and replay;
- locality benchmark and expanded differential/statistical test suite.

### Corrected

- DPO-invalid embeddings are no longer assigned stochastic probability mass and rejected only after selection.
- subtype-compatible patterns now participate correctly in incremental delta relevance.
- unchanged incremental matches are no longer globally re-stamped after every graph epoch.

### Semantics

- runtime semantic version: `osahr-python-0.2.0`;
- time-dependent hazards may reference absolute `time` only and require a declared upper bound;
- `horizon` is reserved for hazard bound/integral contracts;
- exact path likelihood for time-dependent rules requires analytic integral contracts.
