"""Differential checks against the unchanged exhaustive search."""

from __future__ import annotations

import random
from unittest.mock import patch

import pytest

from osahr import (
    AttributeSpec, BoundaryState, ConditionPolarity, Expr, GraphCondition,
    HyperedgeType, Hypergraph, Matcher, Model, PatternEdge, PatternGraph,
    PatternVertex, PortSpec, Rule, Runtime, RuntimeConfig, Schema, SchedulerKind,
    TemplateEdge, TemplateGraph, TemplateVertex, ValueKind, Var, VertexType,
)
from osahr.canonical import canonical_equal
from osahr.errors import MatchError
from osahr.graph import GraphDelta
from osahr.incremental import IncrementalMatcher
from osahr.indexed_matcher import IndexedMatcher


def fixture(seed=0):
    rng = random.Random(seed)
    attr = {"x": AttributeSpec(ValueKind.INT, required=True)}
    schema = Schema(
        [VertexType("V", attr), VertexType("Sub", attr, parents=frozenset({"V"}))],
        [HyperedgeType("Arc", {"s": PortSpec("s", "V")},
                       {"t": PortSpec("t", "V")}, attr),
         HyperedgeType("Bag", {"items": PortSpec(
             "items", "V", minimum=3, maximum=3, ordered=False, repeated_vertices=True,
         )}, {}, attr),
         HyperedgeType("Tuple", {"items": PortSpec(
             "items", "V", minimum=3, maximum=3, ordered=True, repeated_vertices=True,
         )}, {}, attr),
         HyperedgeType("Null", {}, {}, attr)],
    )
    graph = Hypergraph(schema)
    ids = [graph.add_vertex("Sub" if i % 2 else "V", {"x": i % 2}).entity_id
           for i in range(5)]
    for i in range(8):
        graph.add_edge("Arc", {"s": (rng.choice(ids),)}, {"t": (rng.choice(ids),)},
                       {"x": i % 2})
    for type_id in ("Bag", "Tuple"):
        for endpoints in ((ids[0], ids[1], ids[0]), (ids[2], ids[3], ids[4])):
            graph.add_edge(type_id, {"items": endpoints}, {}, {"x": 0})
    for _ in range(2):
        graph.add_edge("Null", {}, {}, {"x": 0})
    return graph, ids


def equivalent(graph, pattern, **kwargs):
    expected = Matcher().find_pattern_matches(graph, pattern, **kwargs)
    actual = IndexedMatcher().find_pattern_matches(graph, pattern, **kwargs)
    assert [m.match_id for m in actual] == [m.match_id for m in expected]
    for a, b in zip(actual, expected):
        assert a.vertex_map == b.vertex_map and a.edge_map == b.edge_map
        assert a.graph_epoch == b.graph_epoch
        assert canonical_equal(a.bindings, b.bindings)
    return actual


@pytest.mark.parametrize("seed", range(12))
def test_small_multigraph_relations_and_all_single_anchors(seed):
    graph, ids = fixture(seed)
    a, b, c = (PatternVertex(key, "V") for key in "abc")
    arc = PatternEdge("e", "Arc", {"s": ("a",)}, {"t": ("b",)})
    patterns = [
        PatternGraph(()), PatternGraph((a,)), PatternGraph((a, b)),
        PatternGraph((PatternVertex("a", "V", allow_subtypes=False),)),
        PatternGraph((a, b), (arc,)),
        PatternGraph((a, b, c), (arc,)),  # disconnected vertex
        PatternGraph((a, b, c), (arc, PatternEdge("f", "Arc", {"s": ("b",)}, {"t": ("c",)}))),
        PatternGraph((a, b), (arc, PatternEdge("f", "Arc", {"s": ("a",)}, {"t": ("b",)}))),
        PatternGraph((a,), (PatternEdge("e", "Arc", {"s": ("a",)}, {"t": ("a",)}),)),
        PatternGraph((), (PatternEdge("e", "Null", {}, {}), PatternEdge("f", "Null", {}, {}))),
        PatternGraph((PatternVertex("a", "V", {"x": Var("shared")}),
                      PatternVertex("b", "V", {"x": Var("shared")})), (arc,)),
    ]
    for type_id in ("Bag", "Tuple"):
        patterns.extend([
            PatternGraph((a, b), (PatternEdge("e", type_id, {"items": ("a", "b", "a")}, {}),)),
            PatternGraph((a, b, c), (PatternEdge("e", type_id, {"items": ("c", "a", "b")}, {}),)),
            PatternGraph((a, b), (PatternEdge("e", type_id, {"items": ("a", "b")}, {}),)),
        ])
    for pattern in patterns:
        matches = equivalent(graph, pattern)
        for vertex in pattern.vertices:
            for entity_id in ids:
                equivalent(graph, pattern, prebound_vertices={vertex.key: entity_id})
        for edge in pattern.edges:
            for entity_id in graph.edges_by_type[edge.type_id]:
                equivalent(graph, pattern, prebound_edges={edge.key: entity_id})
        if matches:
            equivalent(graph, pattern, prebound_vertices=matches[0].vertex_map,
                       prebound_edges=matches[0].edge_map)
        equivalent(graph, pattern, initial_bindings={"shared": 0})
        equivalent(graph, pattern, initial_bindings={"shared": 0.0})


def test_invalid_and_noninjective_anchors():
    graph, ids = fixture()
    pattern = PatternGraph((PatternVertex("a", "V"), PatternVertex("b", "V")))
    assert equivalent(graph, pattern, prebound_vertices={"a": ids[0], "b": ids[0]}) == []
    assert equivalent(graph, pattern, prebound_vertices={"a": next(iter(graph.edges))}) == []
    for matcher in (Matcher(), IndexedMatcher()):
        with pytest.raises(MatchError):
            matcher.find_pattern_matches(graph, pattern, prebound_vertices={"unknown": ids[0]})
        with pytest.raises(MatchError):
            matcher.find_pattern_matches(graph, pattern, prebound_edges={"unknown": ids[0]})


def test_every_directed_graph_on_three_vertices():
    schema = Schema([VertexType("V")], [HyperedgeType(
        "Arc", {"s": PortSpec("s", "V")}, {"t": PortSpec("t", "V")},
    )])
    pattern = PatternGraph(tuple(PatternVertex(key, "V") for key in "abc"), (
        PatternEdge("e", "Arc", {"s": ("a",)}, {"t": ("b",)}),
        PatternEdge("f", "Arc", {"s": ("b",)}, {"t": ("c",)}),
    ))
    for mask in range(1 << 9):
        graph = Hypergraph(schema)
        ids = [graph.add_vertex("V").entity_id for _ in range(3)]
        for index in range(9):
            if mask & (1 << index):
                graph.add_edge("Arc", {"s": (ids[index // 3],)}, {"t": (ids[index % 3],)})
        equivalent(graph, pattern)


def test_local_delta_classification_birth_death_and_untouched_matches():
    graph, ids = fixture()
    rule = Rule("zero", PatternGraph((PatternVertex("a", "V", {"x": 0}),)),
                TemplateGraph((TemplateVertex("a", "V"),)), Expr("1.0"))
    matcher = IncrementalMatcher()
    kwargs = dict(parameters={}, memory={}, time=0.0)
    cache = matcher.update_rule(graph, rule, **kwargs)
    untouched = next(m for m in cache.matches.values() if m.vertex_map["a"] == ids[2])
    for entity_id, value in ((ids[0], 1), (ids[1], 0), (ids[1], 0)):
        before_ids = set(cache.matches)
        before_attrs = dict(graph.vertices[entity_id].attributes)
        graph.set_vertex_attributes(entity_id, {"x": value})
        # Explicitly report the edit; even an equal value may need revalidation.
        delta = GraphDelta(updated_vertices_before={entity_id: before_attrs},
                           updated_vertices_after={entity_id: {"x": value}})
        cache = matcher.update_rule(graph, rule, delta=delta, **kwargs)
        after_ids = set(cache.matches)
        change = matcher.last_deltas[rule.rule_id]
        assert change.added == after_ids - before_ids
        assert change.removed == before_ids - after_ids
        assert change.revalidated == {
            match_id for match_id in after_ids & before_ids
            if cache.matches[match_id].vertex_map["a"] == entity_id
        }
        assert cache.matches[untouched.match_id] is untouched
        matcher.assert_equivalent(graph, rule, **kwargs)


@pytest.mark.parametrize("polarity", list(ConditionPolarity))
def test_condition_extensions_shared_vertices_edges_and_guard(polarity):
    graph, _ = fixture(4)
    left = PatternGraph((PatternVertex("a", "V"), PatternVertex("b", "V")),
                        (PatternEdge("e", "Arc", {"s": ("a",)}, {"t": ("b",)}),))
    condition = GraphCondition(
        PatternGraph((*left.vertices, PatternVertex("c", "V")), left.edges),
        polarity, shared_vertices={"a": "a", "b": "b"}, shared_edges={"e": "e"},
        guard=Expr("v.c.x == p.wanted"),
    )
    rule = Rule("conditional", left, TemplateGraph(()), Expr("1.0"), conditions=(condition,))
    for wanted in (0, 1, 9):
        kwargs = dict(parameters={"wanted": wanted}, memory={}, time=0.0)
        assert IndexedMatcher().find_rule_matches(graph, rule, **kwargs) == (
            Matcher().find_rule_matches(graph, rule, **kwargs)
        )


def test_verifier_detects_binding_drift_even_when_ids_are_unchanged():
    graph, _ = fixture()
    rule = Rule("read", PatternGraph((PatternVertex("a", "V", {"x": Var("x")}),)),
                TemplateGraph((TemplateVertex("a", "V"),)), Expr("1.0"))
    matcher = IncrementalMatcher()
    kwargs = dict(parameters={}, memory={}, time=0.0)
    cache = matcher.update_rule(graph, rule, **kwargs)
    next(iter(cache.matches.values())).bindings["x"] = "corrupted"
    with pytest.raises(AssertionError, match="bindings diverged"):
        matcher.assert_equivalent(graph, rule, **kwargs)


@pytest.mark.parametrize("scheduler", list(SchedulerKind))
def test_edge_rewrites_preserve_eventwise_trajectory_and_replay(scheduler):
    graph, _ = fixture(2)
    left = PatternGraph((PatternVertex("a", "V", {"x": Var("x")}), PatternVertex("b", "V")),
                        (PatternEdge("e", "Arc", {"s": ("a",)}, {"t": ("b",)}),))
    right = TemplateGraph((TemplateVertex("a", "V", {"x": Expr("x + 1")}), TemplateVertex("b", "V")),
                          (TemplateEdge("e", "Arc", {"s": ("a",)}, {"t": ("b",)}),))
    rule = Rule("tick", left, right, Expr("1.0 + x"))
    model = Model(graph, BoundaryState(), (rule,))
    reference = Runtime(model, root_seed=41, config=RuntimeConfig(matcher_backend="reference", scheduler=scheduler))
    indexed = Runtime(model, root_seed=41, config=RuntimeConfig(incremental_verify=True, scheduler=scheduler))
    initial = indexed.snapshot()
    for _ in range(12):
        expected, actual = reference.step().event, indexed.step().event
        assert expected.cause["match_id"] == actual.cause["match_id"]
        assert expected.post_time == actual.post_time
        assert indexed.state_hash == reference.state_hash
    assert Runtime.replay_deltas(model, initial, indexed.event_log).state_hash == indexed.state_hash


def test_anchored_sparse_search_does_not_enumerate_remote_vertex_pairs():
    graph, ids = fixture()
    pattern = PatternGraph((PatternVertex("a", "V"), PatternVertex("b", "V")),
                           (PatternEdge("e", "Arc", {"s": ("a",)}, {"t": ("b",)}),))
    import osahr.indexed_matcher as module

    counts = []
    for remote_count in (0, 1000):
        for _ in range(remote_count):
            graph.add_vertex("V", {"x": 0})
        with patch.object(module, "_match_attributes", wraps=module._match_attributes) as predicate:
            IndexedMatcher().find_pattern_matches(graph, pattern, prebound_vertices={"a": ids[0]})
            counts.append(predicate.call_count)
    assert counts[0] > 0 and counts[0] == counts[1]
