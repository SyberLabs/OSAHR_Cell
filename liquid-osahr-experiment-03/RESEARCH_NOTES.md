# Research notes — Experiment 03

## Established (02B)

Predictive hazard accuracy and intervention-effect recovery are empirically separable. A global residual trust \(\alpha\) chosen on 18 calibration scenarios was \(\alpha=0\). The confirmatory holdout then showed that the best executed \(\alpha\) depends on regime and estimand. 02B therefore already **measured** the inadequacy of scalar trust; it did not **operationalize** a query-conditioned alternative.

## This experiment's claim

The smallest non-mystical object that answers 02B is a lookup field

```text
T(q, I, r, h) ∈ {0, 0.25, 0.5, 1.0}
```

fitted with the same objective 02B already froze, applied inside each \((q,I,r)\) cell, with \(\alpha=0\) off-support.

That is closer to a calibrated answering policy than to a new neural authority \(\alpha=f_\theta(\cdot)\). A learned trust head would need its own counterfactual calibration, which is the problem we are trying to avoid.

## What would falsify the idea

1. Cell-wise \(T\) fitted on the 02B calibration is identical to global \(\alpha=0\) **and** cannot improve any confirmatory estimand. Then query-conditioning is unidentified at the current calibration design, not refuted as a concept.
2. Cell-wise \(T\) improves the calibrated estimand/regime and **reliably degrades** uncalibrated cells even with the conservative fallback. Then the field leaks; fallbacks are insufficient.
3. Leave-one-scenario-out on confirmatory also fails to beat global \(\alpha=0\). Then the apparent query/regime dependence in the 02B report is a small-sample ranking artifact.

## Adjacent literature used as design pressure, not decoration

- 3GPP TS 28.561 / Network Digital Twin management: a twin is used to assess configuration/policy changes **before** live application. That is an intervention query, not a next-KPM prediction query.
- Digital-twin counterfactual frameworks (e.g. Laudy, 2026) treat intervention evaluation as a distinct epistemic task.
- 02B's own exactness envelope: \(\alpha=0\) is an identity, not a numerical limit.

## Deliberate non-features

- per-event-head \(\alpha\) (service/failure/handover) — 02B recommended it; it needs new rollouts, not this reanalysis;
- neural \(\mathcal T_\theta\);
- interpolating uncalibrated regimes from neighbors;
- putting \(T\) inside the OSAHR state hash.
