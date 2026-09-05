# Incidence-constrained matching

## Foundation: preserve the relation, change how it is enumerated

For a pattern L and host graph G, the kernel needs the finite relation M(L,G)
of injective typed vertex and edge maps satisfying all incidence and attribute
constraints. Shared attribute variables must unify under canonical equality.
Rules then restrict this relation by guards and positive/negative graph conditions;
the occurrence layer applies DPO/boundary eligibility and computes hazards.

Every embedding remains a separate channel. In particular, permuting distinct
symbolic vertices across an unordered port can give distinct embeddings. Dividing
by an automorphism group would change channel multiplicities and hence the
stochastic generator. This implementation does not make that semantic change.

The useful abstraction here is a constrained relation: solve its incidence
constraints as early as possible instead of constructing a Cartesian product
and rejecting most of it afterward. No new graph store or persistent index is
needed. `IndexedMatcher` uses the host's existing type and incidence indices.

## Search and correctness argument

Assume a valid host graph whose indices agree with its entity store, held fixed
throughout a synchronous matching call, as required by normal graph operations.

Let p be a partial vertex assignment. For each pattern edge e, candidate host
edges C(e,p) are selected as follows:

1. If e is prebound, use its prescribed edge.
2. Otherwise, if any endpoint is bound, collect edges of the required type from
   the smallest incidence bucket of those bound endpoints.
3. Otherwise, use the edge-type index.

**Candidate containment.** If a complete valid embedding m extends p, then m(e)
belongs to C(e,p). In case 2, m(e) must be incident to every bound endpoint, so it
belongs to whichever bucket was chosen. Taking only one bucket can admit false
positives; it cannot remove a valid image edge.

To assign a vertex x adjacent to a constrained edge, project C(e,p) onto x's
required side and role. For an ordered role, also require its ordinal. For an
unordered role, admit every endpoint in that role. Intersect these projections
across the incidences of x. With no constrained adjacent edge, use compatible
vertex-type buckets. Honor prebindings, reject used vertex IDs, check subtype
compatibility, and unify attributes. Once all endpoints of an edge are assigned,
reject the branch if no candidate edge passes the complete incidence predicate.

**Completeness.** Induct on the number of assigned vertices. Every complete valid
embedding extending the current assignment supplies a vertex in every relevant
projection by candidate containment. That vertex survives type, injectivity and
attribute checks. Any newly closed edge constraint has its image edge as a
witness. Thus some branch reaches that embedding's full vertex map. The final
edge search contains each image edge and enumerates its injective edge map.

**Soundness.** At emission, all vertex type/attribute checks have passed. Each
edge passes the reference matcher’s complete side/role/ordinal or multiset
predicate and attribute unification. Separate used-ID sets enforce vertex and
edge injectivity. Prebindings are honored. Hence every emitted map is in M(L,G).

**Multiplicity and identity.** Deterministic choice of the next symbolic key and
set-valued candidate domains visit a complete map once. Distinct unordered-port
embeddings and parallel host edges remain distinct. The existing `Match.create`
computes IDs, and results retain canonical match-ID order.

The argument establishes search equivalence under the stated assumptions; it is
not a machine-checked proof. Shared final predicates deliberately preserve the
existing semantics. Independent hand-counted cases and the existing reference
tests remain necessary to detect a defect in those shared predicates.

## Incremental integration

The incremental backend uses indexed search for initial/full enumeration and
anchored local rematching. The `reference` backend and authoritative rewrite
revalidation retain the exhaustive `Matcher` implementation unchanged. Conditional
rules still perform full relation refreshes for relevant remote edits. This
change does not attempt a stronger locality theorem for negative conditions.

For local updates let C be the old cached ID set, I the invalidated IDs, and L
the locally rediscovered IDs. Existing reverse indices ensure I is a subset of C.
The classification is exactly:

```text
added       = L \ C
removed     = I \ L
revalidated = L intersect C
```

After removing I, membership probes for L recover `L intersect (C \ I)`.
Union with `L intersect I` recovers `L intersect C`. This avoids copying all of
C on each edit; classification uses O(|I| + |L|) expected set/dictionary work.
Untouched cached Match objects retain their identity and prior verification
epoch, preserving sparse scheduler clock behavior.

Verification now compares canonical attribute bindings as well as IDs. IDs encode
maps, not bindings: equal IDs alone cannot establish equality of future hazards.

## Computational limits

For the benchmark's directed n-vertex ring and two-vertex/one-edge pattern, the
reference search tries n(n-1) vertex maps and scans n edges for each: Theta(n^3)
incidence checks. Indexed search tries n root vertices and constant-degree local
extensions. Including canonical output sorting, it takes O(n log n) for this
fixed-size pattern. With either endpoint or the edge prebound, its search work
is independent of remote ring size at bounded degree.

These are fixture-specific bounds, not general polynomial-time graph matching.
Large degrees, large unordered roles, weak attribute selectivity, and disconnected
patterns can still require many branches. The number of embeddings itself may
be exponential in pattern size. Projection is deliberately conservative and can
leave false positives for the complete predicates to reject.

Whole simulation time also includes cloning, validation, hashing, occurrence
maintenance and scheduling. Matching speedups do not establish equivalent
end-to-end speedups, and indexed search may add overhead on tiny trivial patterns.

## Reproduction and evidence

From the repository root:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_indexed_matcher.py -p no:cacheprovider
& .\.venv\Scripts\python.exe -m benchmarks.benchmark_matching --vertices 24 48 96 --samples 3
```

`benchmarks/matching-results.json` records three alternating-order timing samples
per engine and case, medians, Python/platform details and source hashes. Graph
construction is excluded; both engines are warmed and their complete match
records compared before timing and after every sample. This synthetic fixture
is evidence of eliminating wasted search, not a production latency guarantee.

In the recorded Windows/Python 3.12.14 run, median full-search time on the
96-vertex ring was 1,650.6 ms for the reference and 3.31 ms for indexed search
(498.3x). Vertex-anchored and edge-anchored searches improved by 145.9x and
233.3x respectively. These measurements were taken separately from test execution.

Regression coverage includes all 512 directed graphs on three vertices for a
two-edge path; twelve generated multigraphs with loops, parallel edges, ordered
and unordered roles, repeated endpoints, nullary edges, disconnected vertices,
subtypes, shared variables, and anchors; positive/negative conditions with shared
edges and guarded extensions; changed-binding detection; exact local delta
classification; and eventwise/replay comparisons for all three schedulers.
A work-count regression checks that adding 1,000 isolated vertices does not
increase attribute checks in an anchored connected search.

Validation after implementation: 200 tests passed across `tests`,
`workbench/tests`, `ontology-kernel/test_profile.py`, and
`grokcell/tests/test_admission_replay.py`. The root-configured suite had 145
passing tests before the change; this change adds 22 matcher tests. Run the
combined suite with the repository root, `grokcell`, and `ontology-kernel` on
`PYTHONPATH`. `git diff --check` passed.
