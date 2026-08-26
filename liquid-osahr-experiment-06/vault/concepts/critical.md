---
concept_id: critical
excludes:
  - outage
requires_fidelity: true
---

# Critical

Deadline-sensitive robot control. This concept **requires fidelity**: a
degraded-fidelity edge is not an admissible carrier for `critical` tasks.

During [[outage]] on a degraded path, do not route this class onto that edge.
Contrast [[background]], which may use leftover capacity. Related: [[load]].
