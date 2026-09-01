---
concept_id: load
excludes: []
requires_fidelity: false
degraded_fidelity_edges:
  - MEC-fast
---

# Load

Resource utilization of an `EdgeNode`. In this vault the fast path `MEC-fast`
is the degraded-fidelity edge: the 6G scalar still scores it; [[critical]]
tasks that `requires_fidelity` must not use it.

AnLF `LoadLevel` emits a typed load observation. Related: [[outage]],
[[background]].
