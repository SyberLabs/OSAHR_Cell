---
concept_id: critical_module
excludes:
  - unverified
requires_fidelity: true
---

# Critical module

A construction component that requires a python_tests runner record
and a killed AST mutant before park may admit it onto the Cell graph.
Contrast [[unverified]]. `payload.verified` is ignored. Fail-closed
if the runner is absent or the mutant survives.
