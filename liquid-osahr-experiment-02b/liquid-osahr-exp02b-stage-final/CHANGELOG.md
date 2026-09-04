# Changelog

## 0.2.0: 2026-08-18

Liquid-OSAHR Experiment 02B replaces the unconstrained 02A learned-world formulation with a standards-informed mechanism plus globally bounded topology-coupled CfC residual and explicit neural trust coefficient.

Highlights:

- 3GPP TR 38.901-informed FR1 UMi radio surrogate with mobility, spatial shadow/fading surrogates, interference, SINR/CQI/throughput/drop and handover-pressure features.
- Exact OSAHR thinning preserved by analytic global event-rate bounds.
- `alpha=0` is an exact, neural-arithmetic-free mechanistic fallback.
- Intervention calibration selects trust using policy-effect recovery rather than predictive loss alone.
- Frozen 400-trajectory confirmatory holdout across ID, high mobility, high stress and weak channel regimes.
- Native srsRAN scheduler JSON, O-RAN-KPM-like JSON and 5G-LENA CSV telemetry adapters.
- 24 Experiment-02B tests plus all 36 OSAHR reference tests.

Release hardening also fixed an `alpha=0` candidate-cache edge case: a prior rate-only cache entry could contain no cached liquid state, causing a later state-hash query at the identical time/graph epoch to dereference `None`. The corrected cache preserves any rate entry while recomputing the missing state; a dedicated regression test covers the sequence.
