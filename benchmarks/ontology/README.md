# Open-ontology execution control - v1

Status: **development probe**, not a production adapter or a competitive win.
This directory tests the proposed role of OSAHR as an executable stochastic
mechanism layer behind an organization's ontology. It does not build another
ontology store, agent framework, or Foundry replacement.

## Run from a repository checkout

```sh
python -m pip install -e '.[benchmark]' pytest
python -m pytest tests/test_ontology_benchmark.py
python -m benchmarks.ontology --copies 1 4 16 --events 100 --samples 256
```

The last command prints a JSON report containing raw trials, source hashes,
fixture, seeds and environment. It raises on a failed correctness gate. This
repository-only harness is not shipped in the `osahr` wheel. The core kernel
remains dependency-free; RDFLib 7.6.0 is an optional, tested benchmark dependency.

## Minimal ontology contract

`routes.ttl` is a local RDF/Turtle snapshot with URI identities, Site and Route
types, typed properties, and source/target relationships. Parsing uses RDFLib;
explicit projection validation checks the narrow application contract. This is
**not OWL inference or SHACL conformance**, and does not claim to accept arbitrary
RDF. Unknown predicates/types, missing or multivalued properties, blank entity
identities, invalid rates and unresolved/self endpoints are rejected.

| Organization concept | Probe representation | OSAHR representation |
|---|---|---|
| Object identity and type | URI + RDF type | Typed vertex with URI property |
| Route endpoints | source/target URI references | Route properties + typed hyperedge incidences |
| Currently available route | Boolean property | Available hyperedge; deleted on failure, recreated on repair |
| Mechanism/action definition | Versioned Python model compiler | Two rewrite rules with nonnegative event rates |
| Scenario assumption | Local fixture values | Compiled initial graph and hazards |
| Result | URI-indexed event trace and final state | Projected native events; simulation only |

Do not dereference RDF URIs, connect production systems, or write simulated
results back as facts. Rates are invented, per simulation hour. A production
adapter would need snapshot provenance, schema migration, scenario isolation,
authorization, provenance-preserving output and explicitly approved actions.
None of those platform capabilities is delivered by this probe.

## Law and independent comparator

For each route i, availability x_i is a two-state continuous-time Markov chain:

- If x_i = 1, failure flips it to 0 at rate lambda_i.
- If x_i = 0, repair flips it to 1 at rate mu_i.
- All other off-diagonal generator entries are zero. The diagonal is the negative
  sum of outgoing rates. Routes are independent in this **easy control**.

Thus Q(x, flip_i(x)) is lambda_i or mu_i according to x_i. The first wait has
mean 1 / sum(rates), and the next channel probability is its rate / sum(rates).
The stationary up probability is mu_i / (lambda_i + mu_i), when the denominator
is positive. Stationarity is an available oracle, **not a measured result here**.

`baseline.py` independently implements direct Gillespie SSA with plain Python
state. It does not import OSAHR or call the compiler. The validated snapshot is
shared deliberately: both engines must answer exactly the same input question.
This is a meaningful simple alternative, not a comprehensive commercial
competitor evaluation. External library baselines remain a later gate.

## Frozen development protocol

1. Enumerate all 8 states of the base three-route fixture. Compare every outgoing
   target state and rate with relative/absolute tolerance 1e-12. OSAHR targets
   come from actually applying each enabled rewrite, then checking URI identity,
   fixed properties, edge presence and endpoints. Sum rates for duplicate target
   states. Comparing this full off-diagonal generator establishes equivalence
   **on this finite projected fixture**, not for arbitrary OSAHR models.
2. Independently check first-jump mean and channel frequencies, using 256 samples
   per engine with seeds 730000–730255. Waiting-time mean tolerance is six
   standard errors; channel tolerance is sqrt(log(4k/1e-6)/(2n)). These are broad
   regression alarms, not evidence of distributional equivalence by themselves.
3. Mutation tests must reject a doubled hazard, lost/duplicate availability edge,
   or changed endpoint property. Test zero-rate absorption, trace replay,
   within-engine reproducibility and disjoint-copy initialization too.
4. Only then measure 1, 4 and 16 disjoint copies (3, 12, 48 routes), 100 events
   per engine. Fixed event count tests event-processing cost; it is **not** an
   equal-horizon policy/outcome comparison. Different engines use different random
   generators; identical numerical seeds do not imply paired trajectories.
5. One discarded 10-event warmup per engine per size; then seeds 26090501,
   26090502, 26090503. Alternate engine order. Include compilation and runtime
   construction in total time, and also report preparation and execution
   separately. Common RDF parsing is reported once. Trace projection is timed;
   JSON serialization and independent replay checks are not.
6. Retain every raw trial. Report OSAHR/baseline total-time ratio (>1 means OSAHR
   slower). Three repetitions yield descriptive medians only: no p-value,
   confidence claim, “mathematical superiority,” or cross-hardware ranking.
   Short baseline runtimes are timer/noise sensitive. Do not tune the kernel
   against these development seeds and subsequently call them a holdout.

Both engines emit event time, route index, new availability and final state;
the trace must replay to that state. OSAHR additionally retains its full native
audit records, hashing and transactional checks. The baseline does not supply
equivalent tamper evidence/checkpoint machinery. The timing comparison therefore
answers “what does this task cost with the actual engine?”; it does not isolate
matcher cost or show that the systems have equal operational guarantees.
No memory, model-authoring effort, calibrated prediction, real user outcomes,
or Foundry overhead is measured. Source hashes cover kernel and harness; git
dirty status discloses uncommitted runs. Machine load is not controlled.

## Advance / stop

If any generator or oracle gate fails, stop interpretation and fix the model or
harness first. Passing is a license to test a harder scenario, not to ship a
platform. The default expectation is that plain SSA wins this easy control.
If a user's actual problem remains this simple, use the simpler alternative.

Next use a real owner's read-only ontology snapshot and one disruption decision.
Add a topology-coupled workload, a maintained external event-simulation baseline,
an equal-horizon outcome ensemble, and a model-change task. Predeclare latency,
error and effort thresholds **before** touching held-out inputs. Measure memory
in separate runs so allocation tracing does not distort the speed measurement.
See [the research/product framework](../../docs/VALIDATION_FRAMEWORK.md).

## Primary references

- [RDF 1.1 concepts](https://www.w3.org/TR/rdf11-concepts/): shared graph/data primitives.
- [RDFLib](https://rdflib.readthedocs.io/): reuse a parser instead of creating a store.
- [SHACL](https://www.w3.org/TR/shacl/): possible later schema-validation interoperability;
  not implemented here.
- [Foundry Ontology overview](https://palantir.com/docs/foundry/ontology/overview/)
  and [action types](https://palantir.com/docs/foundry/action-types/overview/):
  conceptual interfaces only; Foundry access is neither used nor simulated.
