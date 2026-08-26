from __future__ import annotations

import ast
from pathlib import Path

from osahr.boundary import ExternalEvent

from osahr_cell.anlf import (
    AbnormalBehavior,
    LoadLevel,
    kpm_outage_series,
    load_handle,
    outage_handle,
)
from osahr_cell.protocol import ANLF_LOAD_VERSION, ANLF_OUTAGE_VERSION
from osahr_cell.twin import build_stub_runtime
from osahr_cell.vault import SemanticVault


def test_anlf_source_does_not_call_runtime_or_rewrite():
    source = (Path(__file__).resolve().parents[1] / "osahr_cell" / "anlf.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])
            imported.extend(alias.name for alias in node.names)
    assert "Runtime" not in imported
    assert "RewriteEngine" not in imported
    assert "rewrite" not in imported
    assert "runtime" not in imported


def test_load_payload_validates_against_boundary_handle():
    handle = load_handle()
    payload = LoadLevel(capacity=6).infer([0.0, 1.2, 2.0, 2.4])
    handle.validate_payload(payload)
    assert payload == {"load": int(payload["load"])}
    assert LoadLevel().version == ANLF_LOAD_VERSION


def test_outage_payload_validates_against_boundary_handle():
    handle = outage_handle()
    detector = AbnormalBehavior()
    up = detector.infer([1.0, 1.0, 0.98])
    down = detector.infer([1.0, 1.0, 0.0])
    handle.validate_payload(up)
    handle.validate_payload(down)
    assert up == {"available": True}
    assert down == {"available": False}
    assert detector.version == ANLF_OUTAGE_VERSION


def test_boundary_injection_on_1s_stub_does_not_go_through_anlf_runtime():
    vault = SemanticVault.load()
    runtime = build_stub_runtime(vault, root_seed=3)
    fast = next(v for v in runtime.graph.vertices.values() if v.attributes["name"] == "MEC-fast")
    before_hash = runtime.graph.state_hash
    payload = LoadLevel(capacity=4).infer([0.0, 1.0, 3.0])
    load_handle("fast-edge-load").validate_payload(payload)
    runtime.inject(
        ExternalEvent(0.2, "anlf-load", 1, "load-1", "fast-edge-load", payload)
    )
    runtime.run_until_time(1.0)
    after = runtime.graph.vertices[fast.entity_id]
    assert after.attributes["load"] == payload["load"]
    assert runtime.time == 1.0
    assert runtime.graph.state_hash != before_hash


def test_outage_kpm_series_marks_window():
    series = kpm_outage_series(horizon=5.0, dt=1.0, outage_start=2.0, outage_end=4.0)
    assert series[2] == 0.0
    assert series[4] == 1.0
