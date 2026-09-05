from __future__ import annotations

import copy

import pytest

from grokcell.construction import (
    build_runtime,
    construction_model,
    graph_component_names,
    licensed_assemble,
    runtime_from_snapshot,
)
from osahr import Runtime


@pytest.mark.parametrize("names", [("core.api",), ("core.api", "app.ui")])
def test_admissions_replay_to_authoritative_state(names):
    runtime = build_runtime()
    initial = runtime.snapshot()
    for seq, name in enumerate(names, start=1):
        licensed_assemble(runtime, name=name, constraint="critical_module", seq=seq)
        assert runtime.event_log[-1].post_state_hash == runtime.state_hash
    replayed = Runtime.replay_deltas(construction_model(), initial, runtime.event_log)
    assert replayed.state_hash == runtime.state_hash
    assert graph_component_names(replayed) == list(names)


def test_membership_order_is_derived_from_graph_after_restore():
    runtime = build_runtime()
    for seq, name in enumerate(("z.first", "a.second"), start=1):
        licensed_assemble(runtime, name=name, constraint="critical_module", seq=seq)
    restored = runtime_from_snapshot(runtime.snapshot())
    assert graph_component_names(restored) == ["z.first", "a.second"]


def test_legacy_cache_is_not_authoritative_or_rewritten():
    runtime = build_runtime()
    licensed_assemble(runtime, name="z.first", constraint="critical_module", seq=1)
    # A historical checkpoint may still contain the old redundant cache.
    runtime.memory["components"] = ["stale.name"]
    restored = runtime_from_snapshot(runtime.snapshot())
    assert graph_component_names(restored) == ["z.first"]
    initial = restored.snapshot()
    old_memory = copy.deepcopy(restored.memory)
    licensed_assemble(restored, name="a.second", constraint="critical_module", seq=2)
    assert restored.memory == old_memory
    replayed = Runtime.replay_deltas(construction_model(), initial, restored.event_log)
    assert replayed.state_hash == restored.state_hash
    assert graph_component_names(replayed) == ["z.first", "a.second"]
