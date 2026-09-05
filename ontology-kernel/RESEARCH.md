# First-principles specialization of OSAHR for an executable ontology

Research date: 2026-09-04, Pacific time. Repository baseline:
`fb366a5b835e2beb0062863b13e9b0adaac2f534`. The request's “OSR” is interpreted as
the OSAHR work present in this workspace; no unrelated OSR theory is assumed.

## 1. Product-market fit is a gate, not a research conclusion

The strongest available customer evidence is the workspace's prior
Grok Bot component-admission decision, `OSAHR_ISSUE_13_PRODUCT_DECISION.md`
(a local planning note outside this repository).
Its user job is independent review of an exact proposed Python component before
it enters the owner's cell. That is an owner-workflow hypothesis. Its own
evidence ledger distinguishes mechanical demonstrations from recurring value.
This investigation has no customer interview, willingness-to-pay observation,
measured review-time baseline, or voluntary repeat-use result.

Therefore the product decision is **no new platform; bounded compatibility
experiment only**. The owner is the provisional user, not a hypothetical network
operator or manufacturing customer inferred from the simulator. No general
ontology-foundry business is established by the existence of typed rewriting.

The actual comparison is an owner-controlled acceptance test, conventional CI
evidence, and human approval. For an existing Foundry customer, native Actions
are the default. A research kernel survives only if its state-transition evidence
removes additional recurring work or changes an important decision. Run two
real pending proposals with baseline effort recorded, then observe the next
eligible proposal without prompting. Failure to produce incremental value or
voluntary reuse is a reason to remove the integration, not add features.

## 2. What the local research establishes

The records were read as evidence with their declared limitations. Frozen
experiments were not retrained, retuned, or reclassified as new measurements.

- **Kernel:** `osahr/schema.py`, `matcher.py`, `rewrite.py`, `graph.py`,
  `canonical.py`, `model.py`, and the architecture/research notes already implement
  typed matching, DPO applicability, candidate-state transactions, canonical
  identities, and replay. The current core suite passes 105 tests. Test passage
  is evidence about covered cases, not a formal verification of every operation.
- **6G:** the policy experiment uses a synthetic twin. Its result is not measured
  radio-network performance or market demand. See
  [6G report](../osahr-6g/osahr_6g_experiment_release/EXPERIMENT_REPORT.md).
- **01:** learned-intensity performance varies with regime; better likelihood
  does not guarantee better policy-effect recovery.
  [Experiment 01](../liquid-osahr-experiment-01/EXPERIMENT_REPORT.md).
- **02A:** closed-loop learned feedback is not universally better than its
  ablations. Exact sampling of a specified model does not remove misspecification.
  [Experiment 02A](../liquid-osahr-experiment-02a/liquid-osahr-experiment-02a/EXPERIMENT_REPORT.md).
- **02B:** intervention calibration selects the mechanistic fallback despite
  improvements in factual hazard identification; counterfactual preference varies
  by query/regime. This is synthetic evidence.
  [Experiment 02B](../liquid-osahr-experiment-02b/liquid-osahr-exp02b-stage-final/EXPERIMENT_REPORT.md).
- **03:** query-conditioned arm selection is a reanalysis of frozen trajectories,
  not a new simulator run.
  [Experiment 03](../liquid-osahr-experiment-03/EXPERIMENT_REPORT.md).
- **04:** the frozen selector's primary paired difference against the mechanism
  is +0.00998 with a 95% interval [-0.00268, 0.02571]; superiority is unresolved.
  Identification on calibration did not establish transport to a new seed.
  [Experiment 04](../liquid-osahr-experiment-04/EXPERIMENT_REPORT.md).
- **05:** its declared 22-second confirmatory run is unexecuted. The 3-second
  instrument check cannot be promoted to confirmation.
  [Experiment 05](../liquid-osahr-experiment-05/EXPERIMENT_REPORT.md).
- **06:** the controller may act under unresolved evidence while the directional
  claim remains withheld. Legality and predictive error are distinct objectives.
  Its six runs do not establish broad external validity.
  [Experiment 06](../liquid-osahr-experiment-06/EXPERIMENT_REPORT.md).
- **GrokCell:** the existing assembly rule is reusable, but the live path changes
  `runtime.memory["components"]` after its recorded events. A fresh local probe
  confirmed that the last event hash and delta-replayed state both differ from
  the final live runtime hash. The subsequent
  [maintenance case](cases/admission-replay/README.md) repairs this path by
  removing the unrecorded cache write. It does not reconstruct old event logs.
  [Construction implementation](../grokcell/grokcell/construction.py).

The common result worth retaining is separation of structural validity, model
fitness for a specific decision, evidence truth, and authority to act. It does
not justify a neural controller, a universal trust scalar, or a new graph engine.
`research_directions/` remains proposed architecture, not executed science.

## 3. Mathematical foundation and the part to delete

For an existing stochastic rewrite model, OSAHR declares augmented state

    X = (G, B, R, Theta, Z, t, n).

The graph is finite, typed, directed, and has explicit role-labelled incidences.
A rule is a linear DPO span `L <- K -> R`; its injective match must satisfy
structural conditions before it is enabled. For declared occurrence intensities,
the generator has the form

    (Lf)(X) = sum_(r,m enabled) a_(r,m)(X) [f(T_(r,m)(X)) - f(X)].

These foundations already exist in stochastic rewriting research and the local
implementation. They are not new mathematics from this investigation.
[Behr, On Stochastic Rewriting and Combinatorics, §§2–3](https://arxiv.org/html/2102.02364v1).

For the present job, the owner has selected a concrete action and target. There
is no observed waiting-time mechanism to estimate. Introducing an exponential
clock would add arbitrary simulated time. The required operation is instead the
partial function

    T_r(G, m) = G' if the bound match and rewrite are valid; otherwise failure.

This deterministic profile is not an approximation to a CTMC and makes no CTMC
trajectory claim. It reuses `RewriteEngine.apply`, which already supports a
specified match. Its graph result is separate from the running `Runtime`.
No stochastic scheduler, neural state, online training, or dynamic rule creation
is added. A test deliberately uses an undefined hazard expression and verifies
that deterministic rewriting never evaluates it.

Even for a stochastic model, finite rates at each individual state would not by
themselves establish global non-explosion over an unbounded growing state space.
Floating-point sampling is also not a machine-checked real-arithmetic proof.
The repository's exactness claims must retain their declared model and runtime
limits; they cannot become a blanket claim about real-world correctness.

## 4. Locality derivation for this exact rule

The existing GrokCell rule reads a `Cell c` and a `Slot s` with `pending=True`,
preserves both, changes `s.pending` to false, creates `Component q` with the
slot's name, and creates `PartOf(q,c)`. It deletes no vertex or edge. It has no
negative application condition, no global graph query, and no global schema
invariant over component membership. Dependencies and name uniqueness are
checked on the supplied complete RDF snapshot before this structural operation.

Let `F` be the full temporary construction graph, and `S` its two-vertex cell/slot
footprint. Let `C` be the existing component context attached to the preserved
cell. The following argument is specific to this pinned rule and schema:

1. Binding `c` and `s` in `S` gives exactly the same local attributes and rule
   bindings as their corresponding vertices in `F`.
2. The rule reads no attribute or incidence in `C`; removing `C` cannot alter its
   guard or output expressions. There is no remote negative condition to change.
3. No vertex is deleted, so the dangling condition cannot be changed by unseen
   incidences in `C`. The proposal boundary remains attached to preserved `s`.
4. The new vertex and edge have fresh identities; every old context vertex and
   edge is unchanged. The schema validates the new types and ports locally.
5. Consequently the result on `F` is the result on `S` with `C` reattached, up to
   renaming newly allocated internal IDs. The resulting membership and slot
   update agree. Equality of full and small graph hashes is neither expected nor
   asserted, because they represent different state spaces.

The RDF exporter preserves every input triple and adds the six triples for the
new component and membership. The requested component IRI must be fresh in all
triple positions except its proposal pointer. Internal temporary IDs never become
external object IDs. Tests compare the full-context structural effect and
untouched context, and separately verify exact delta replay of the small graph.

The rule and schema content hashes are checked before projection. If either
changes, the profile refuses until this locality argument is reviewed. A deletion
rule, global condition, new invariant, or arbitrary imported ontology cannot
inherit this optimization automatically. This is a hand-derived specialization,
not an unimplemented claim of a general ontology-to-kernel compiler.

## 5. Efficiency with measured limits

The initial experiment kept every component in the temporary graph. Binding the
match alone did not materially improve its transaction time: full graph cloning
and validation dominated. The initial samples are retained in
[benchmark-before-locality.json](artifacts/benchmark-before-locality.json).

The justified deletion is the untouched component context. For a fixed rule and
bounded attribute sizes, the temporary DPO graph contains two vertices before
and three vertices/one edge afterward, independently of membership count. The
rewrite stage therefore does constant work with respect to that count.

The complete pipeline is **not constant time**. It validates and fingerprints
the full RDF input, checks complete membership, retains the RDF frame, validates
the candidate, and hashes exact module/evidence bytes. If `N` is RDF size and
`B` is byte-input size, its cost includes validation, RDF canonicalization,
`O(N log N)` sorting in this implementation, and `O(N+B)` copying/hashing work.
RDF blank-node canonicalization can be more expensive on symmetric graphs.
General SHACL or graph-pattern complexity is not bounded by this fixed profile.

In the recorded Windows/Python 3.12.14 run, seven alternating measurements at
1,000 existing components gave median rewrite-stage times of 0.564 ms for the
small bound graph, 33.028 ms for full-context bound execution, and 33.364 ms for
full-context exhaustive execution. The latter/local ratio is approximately 59,
**for this stage and synthetic workload only**. The complete warm preview of
5,011 RDF triples took 306.040 ms in one measurement. Initialization, network
access, code execution, approval, and platform writes are outside those timings.
[Raw samples and method](artifacts/benchmark.json).

Do not describe that as a 59-fold application speedup. The full preview is now
dominated by standard RDF work. Retain the existing libraries; optimize further
only after an owner supplies a latency target and a representative workload.
The benchmark is a local engineering comparison, not a confirmatory experiment
or performance comparison against a live Foundry tenant.

## 6. External ontology and existing technology

**Chosen now: W3C PROV-O with RDFLib and pySHACL.** A cell is represented using
`prov:Collection`, members and byte artifacts using `prov:Entity`, membership
using `prov:hadMember`, and the preview computation using `prov:Activity`.
This reuses an external vocabulary for provenance and collections.
[W3C PROV-O](https://www.w3.org/TR/prov-o/).

The actual W3C Turtle ontology was downloaded unmodified and pinned by SHA-256.
The executable checks its relevant declarations. The local `ex:` vocabulary adds
only proposal fields, digest fields, and snapshot-completeness/revision metadata
that the workflow needs. Those additions are an application profile, not new
universal ontological categories. See [source record](vendor/SOURCE.md).

RDF graphs are sets of triples and do not themselves define operational commit
semantics. RDFLib handles parsing, graph operations, SPARQL, and blank-node
canonicalization; none is reimplemented here.
[RDF 1.1 Concepts](https://www.w3.org/TR/rdf11-concepts/),
[RDFLib](https://github.com/RDFLib/rdflib).

SHACL provides data-graph validation against shapes. pySHACL executes the fixed
operational constraints, with rule execution and imports disabled. No full OWL
reasoning or comprehensive PROV constraint checking is claimed. In particular,
absence from an arbitrary RDF graph is not proof of absence in reality. The
profile requires an explicit complete-membership declaration; the host must
establish its truth and scope.
[W3C SHACL Recommendation](https://www.w3.org/TR/shacl/),
[pySHACL](https://github.com/RDFLib/pySHACL).

**Alternative for real software inventory:** SPDX already supplies software
component and relationship vocabulary. Use its existing tooling if the owner
actually needs SBOM import. This membership preview has no license-compliance or
SBOM job, so implementing an SPDX parser would add unused work.
[SPDX specifications](https://spdx.dev/use/specifications/).

**Alternative for model transformation:** Eclipse VIATRA already offers
incremental graph queries and model transformations. There is no evidence to
justify porting its functionality into a new Python query engine. Reuse the
existing OSAHR implementation for this repository's rules.
[VIATRA documentation](https://eclipse.dev/viatra/documentation/index.html).

**Alternative for evidence authenticity:** Sigstore already verifies signed
attestations and supports policy evaluation. The prototype's hashes only bind
content; they do not authenticate issuers or make evidence true. Do not build a
new signing or attestation service for this experiment.
[Sigstore attestation verification](https://docs.sigstore.dev/cosign/verifying/attestation/).

Most decisively, three independent tests show that RDFLib's existing SPARQL
INSERT operation produces exactly the same additive candidate RDF graph after
the stated preconditions. The addition itself is not unique to OSAHR. Its only
possible extra value here is reuse of an already-owned rule and its structural
transition evidence. That value still requires the customer test in section 1.

## 7. Foundry integration boundary

Foundry already provides transactional Actions, action-specific submission
criteria, and SDK access to ontology operations. An adapter should bind the
owner's actual object/link/action types instead of creating a competing platform.
[Actions](https://www.palantir.com/docs/foundry/action-types/overview),
[Submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria),
[Ontology SDK](https://www.palantir.com/docs/foundry/ontology-sdk/overview).

Its documented scenario capability already supports detached what-if edits and
has beta/access limitations. Rebuilding scenarios locally would duplicate a
product capability; a mock cannot validate tenant permissions, rebasing, or
actual commit behavior.
[Foundry scenarios](https://www.palantir.com/docs/foundry/ontology/overview-ontology-scenario).

No tenant, ontology identifier, or actual customer workflow beyond the prior
Grok Bot hypothesis was supplied. Consequently no live integration is claimed.
The next platform test should use an existing authorized nonproduction tenant,
or investigate [Build with AIP](https://build.palantir.com/) access. Access and
scenario availability are not assumed from the public documentation.

A future native action needs to check the current source revision, component
identity, current dependencies, exact evidence, and authenticated owner decision
at its commit boundary. A prior snapshot preview is not a concurrency lock.
Submission criteria must be checked against the platform's actual isolation
semantics; a separate read followed by a write cannot be assumed atomic. When
that cannot be guaranteed, the adapter must obtain a new preview or refuse.

The temporary OSAHR graph remains an evaluator. It must not become a second
authoritative store beside Foundry. Likewise, a successful preview is not a
human approval, code execution result, correctness theorem, or intervention
effect. The subsequent GrokCell repair supports replay of newly recorded admission
events from an initial checkpoint. It does not establish complete historical
replay or add historical event persistence to checkpoint restoration.

## 8. What has and has not been established

Established locally: real external vocabulary loading; a running RDF-to-OSAHR-
to-RDF profile; unchanged upstream schema/rule reuse; exact-byte mismatch refusal;
shape validation; a justified two-vertex footprint; structural agreement with
full-context execution; small-graph delta replay; and native-SPARQL equivalence
for the tested additive operation. The initial research run had 28 profile checks
alongside 105 kernel checks. Follow-up verification, including a failing-evidence
negative control and the GrokCell surface, is recorded in the maintenance case.

Not established: product-market fit, real-world causal accuracy, authenticated
approval, safe execution of generated source, full ontology logical consistency,
cross-platform commit atomicity, recovered historical GrokCell event logs, or a live
Foundry deployment. No new stochastic or neural claim has been introduced.

**Decision:** use a real external ontology and existing libraries with synthetic
operational fixtures now. Do not build a mock Foundry. Keep this small executable
specialization as a falsifiable engineering artifact; graduate it only if its
incremental value survives a real owner workflow against existing tools.
