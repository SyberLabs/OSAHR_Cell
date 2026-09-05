# Ontology route control: initial result

Date: 2026-09-05. Status: **measured development probe; not independent product validation**.

Executed against clean revision `11261437a7c6ba811269c4663d7c0893bbf62364` on Python 3.12.13, RDFLib 7.6.0. Exact sources, fixture, seeds, environment and every raw timing trial are in [the JSON record](results/2026-09-05.json). The timed run followed completion of the test suite; no test suite was intentionally run alongside it. Other host load was not controlled.

## What passed

- All 8 projected states and 24 outgoing transitions matched the independently implemented generator, including rewritten targets and rates.
- First-jump regression alarms passed for both engines over 256 samples each. Expected mean waiting time: 1.25 simulation hours; observed means: 1.3118 for direct SSA and 1.3879 for OSAHR. These broad checks are not a powered equivalence test.
- Full repository suite: **145 passed**, including **22 ontology-probe tests**, in 29.05 s in this environment. This includes negative controls and live incremental-occurrence checks after real events.

## What did not win

Median total preparation + execution time for **100 events**, three trials per engine and size:

| Routes | Plain direct SSA | OSAHR | OSAHR / baseline |
|---|---:|---:|---:|
| 3 | 0.000176 s | 0.733 s | 4,163x |
| 12 | 0.000314 s | 1.322 s | 4,216x |
| 48 | 0.000688 s | 3.381 s | 4,916x |

**OSAHR loses the raw speed comparison decisively on this control.** Do not advertise this as an efficiency win. The sub-millisecond baseline and three repetitions make exact ratios noisy; the observations still show a large overhead at these sizes. No significance test or cross-hardware ranking is asserted.

This is deliberately an easy independent-route model. Both engines satisfy the common projected trace/final-state contract. OSAHR additionally performs native transactional validation and richer audit recording; the baseline does not implement those full guarantees. The experiment does not isolate how much cost comes from matching, graph copying, hashing, audit retention or other machinery. No profiling attribution is claimed.

## Decision

Keep this as a small regression/control harness. Do not optimize the kernel or expand the ontology adapter solely to improve these numbers. For this simple task, plain SSA is the practical choice unless a user actually requires and values additional guarantees.

The product hypothesis remains **unvalidated**: perhaps OSAHR reduces the effort and error involved in changing a useful topology-dependent model. Test that next against the user's existing workflow and a maintained external simulator, with equal required guarantees, realistic latency budgets, independent acceptance checks and untouched cases. If the proposed benefit does not outweigh the overhead, adopt the alternative or stop the product hypothesis.

This result demonstrates neither real-world predictive validity nor Foundry integration, security or performance. See [the protocol](README.md) and [the decision framework](../../docs/VALIDATION_FRAMEWORK.md).
