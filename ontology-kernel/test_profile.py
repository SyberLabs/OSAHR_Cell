from dataclasses import replace
from hashlib import sha256

import pytest
from rdflib import BNode, Graph, Literal, RDF, URIRef
from rdflib.namespace import PROV

from demo import CELL, COMPONENT, EVIDENCE, MODULE, PROPOSAL, fixture, full_context
from kernel import AdmissionProfile, EX, rdf_fingerprint
from osahr import Expr, Matcher
from osahr.errors import MatchError
from osahr.rewrite import RewriteEngine


@pytest.fixture(scope="module")
def profile():
    return AdmissionProfile()


def test_external_ontology_is_real_and_pinned(profile):
    assert len(profile.ontology) > 1000
    assert profile.ontology_digest == "7d203989f67b38bca572253942acc5a1bf24ce3ccfece16f072dcb4be2b79a96"


def test_pure_preview_preserves_input_and_unrelated_rdf(profile):
    data = fixture()
    annotation = (CELL, URIRef("urn:unrelated:note"), Literal("keep me"))
    data.add(annotation)
    before = rdf_fingerprint(data)
    preview = profile.preview(data, PROPOSAL, MODULE, EVIDENCE)
    assert rdf_fingerprint(data) == before
    assert set(data) <= set(preview.candidate)
    assert (CELL, PROV.hadMember, COMPONENT) in preview.candidate
    assert (CELL, PROV.hadMember, COMPONENT) not in data
    assert preview.receipt["claim"] == "candidate_transition_only"
    assert preview.receipt["live_action_executed"] is False
    assert len(set(preview.candidate) - set(data)) == 6


@pytest.mark.parametrize("count", [0, 1, 4, 17, 100])
def test_bound_matches_exhaustive_and_existing_delta_replay(profile, count):
    data = fixture(count)
    model = profile.prepare(data, PROPOSAL, MODULE, EVIDENCE)
    before = model.graph.state_hash
    bound = profile.rewrite(model)
    reference = profile.rewrite(model, bound=False)
    assert bound.graph.state_hash == reference.graph.state_hash
    assert model.graph.state_hash == before
    replay = model.graph.clone()
    replay.apply_delta(bound.graph_delta)
    assert replay.state_hash == bound.graph.state_hash
    assert len(bound.graph_delta.created_vertices) == 1
    assert len(bound.graph_delta.created_edges) == 1
    assert len(bound.graph.vertices_by_type["Component"]) == 1
    # A separate full-context model has different allocated entity IDs. Compare
    # its relational effect, not hashes of intentionally different state spaces.
    complete = full_context(model, data)
    full_result = profile.rewrite(complete, bound=False)
    assert [v.attributes for v in bound.graph_delta.created_vertices.values()] == [
        v.attributes for v in full_result.graph_delta.created_vertices.values()]
    assert len(full_result.graph.vertices_by_type["Component"]) == count + 1
    for vertex_id in complete.graph.vertices_by_type["Component"]:
        assert full_result.graph.vertices[vertex_id] == complete.graph.vertices[vertex_id]
    assert all(full_result.graph.edges[key] == edge for key, edge in complete.graph.edges.items())
    added = next(iter(full_result.graph_delta.created_edges.values()))
    assert added.type_id == "PartOf"
    assert added.tail[0].vertex_id == full_result.post_vertex_map["comp"]
    assert added.head[0].vertex_id == full_result.post_vertex_map["cell"]
    assert full_result.graph.vertices[full_result.post_vertex_map["slot"]].attributes == \
        bound.graph.vertices[bound.post_vertex_map["slot"]].attributes


def test_projection_cost_does_not_grow_with_unread_components(profile):
    small = profile.prepare(fixture(0), PROPOSAL, MODULE, EVIDENCE)
    large = profile.prepare(fixture(100), PROPOSAL, MODULE, EVIDENCE)
    assert small.graph.state_hash == large.graph.state_hash
    assert len(large.graph.vertices) == 2
    assert len(large.graph.edges) == 0


def test_changed_rule_refuses_locality_assumption(profile, monkeypatch):
    import kernel
    monkeypatch.setattr(kernel, "ASSEMBLY_RULE_HASH", "different")
    with pytest.raises(ValueError, match="locality proof"):
        profile.prepare(fixture(), PROPOSAL, MODULE, EVIDENCE)


@pytest.mark.parametrize("predicate", [EX.moduleDigest, EX.evidenceDigest])
def test_changed_bytes_refuse(profile, predicate):
    data = fixture()
    data.set((PROPOSAL, predicate, Literal("0" * 64)))
    with pytest.raises(ValueError, match="Exact bytes"):
        profile.preview(data, PROPOSAL, MODULE, EVIDENCE)


def test_matching_failed_test_evidence_does_not_become_code_approval(profile):
    # Negative control: byte binding says nothing about evidence quality. Neither
    # an exception-raising module nor explicitly failed tests stop a pure preview.
    module = b"raise RuntimeError('must never execute during preview')\n"
    evidence = b'{"test_exit_code": 1, "passed": false}'
    data = fixture()
    data.set((PROPOSAL, EX.moduleDigest, Literal(sha256(module).hexdigest())))
    data.set((PROPOSAL, EX.evidenceDigest, Literal(sha256(evidence).hexdigest())))
    result = profile.preview(data, PROPOSAL, module, evidence)
    assert result.receipt["claim"] == "candidate_transition_only"
    assert result.receipt["live_action_executed"] is False
    assert (CELL, PROV.hadMember, COMPONENT) in result.candidate


@pytest.mark.parametrize("predicate,value", [
    (EX.name, Literal(12)), (EX.moduleDigest, Literal("bad")),
    (EX.component, BNode()),
])
def test_shacl_rejects_malformed_proposals(profile, predicate, value):
    data = fixture()
    data.set((PROPOSAL, predicate, value))
    with pytest.raises(ValueError, match="profile violation"):
        profile.preview(data, PROPOSAL, MODULE, EVIDENCE)


def test_missing_field_does_not_become_default(profile):
    data = fixture()
    data.remove((PROPOSAL, EX.name, None))
    with pytest.raises(ValueError, match="profile violation"):
        profile.preview(data, PROPOSAL, MODULE, EVIDENCE)


def test_missing_membership_completeness_refuses(profile):
    data = fixture()
    data.remove((CELL, EX.membershipComplete, None))
    with pytest.raises(ValueError, match="profile violation"):
        profile.preview(data, PROPOSAL, MODULE, EVIDENCE)


def test_dependency_must_belong_to_cell(profile):
    data = fixture()
    member = next(data.objects(CELL, PROV.hadMember))
    data.remove((CELL, PROV.hadMember, member))
    with pytest.raises(ValueError, match="dependency is absent"):
        profile.preview(data, PROPOSAL, MODULE, EVIDENCE)


def test_name_collision_refuses(profile):
    data = fixture()
    member = next(data.objects(CELL, PROV.hadMember))
    data.set((member, EX.name, Literal("edge.ping")))
    with pytest.raises(ValueError, match="unique"):
        profile.preview(data, PROPOSAL, MODULE, EVIDENCE)


def test_existing_iri_cannot_be_overwritten(profile):
    data = fixture()
    data.add((COMPONENT, URIRef("urn:external:property"), Literal("existing")))
    with pytest.raises(ValueError, match="already in use"):
        profile.preview(data, PROPOSAL, MODULE, EVIDENCE)


def test_iri_used_as_property_is_not_fresh(profile):
    data = fixture()
    data.add((CELL, COMPONENT, Literal("already a property")))
    with pytest.raises(ValueError, match="already in use"):
        profile.preview(data, PROPOSAL, MODULE, EVIDENCE)


def test_rdf_order_and_blank_node_labels_do_not_change_receipt(profile):
    one, two = fixture(), fixture()
    one.add((CELL, URIRef("urn:external:note"), BNode("a")))
    two.add((CELL, URIRef("urn:external:note"), BNode("b")))
    reordered = Graph()
    for triple in reversed(list(two)):
        reordered.add(triple)
    left = profile.preview(one, PROPOSAL, MODULE, EVIDENCE)
    right = profile.preview(reordered, PROPOSAL, MODULE, EVIDENCE)
    assert left.receipt == right.receipt


def test_changed_revision_or_unprojected_fact_changes_receipt(profile):
    one, two = fixture(), fixture()
    two.set((CELL, EX.snapshotRevision, Literal("synthetic-revision-2")))
    first = profile.preview(one, PROPOSAL, MODULE, EVIDENCE)
    second = profile.preview(two, PROPOSAL, MODULE, EVIDENCE)
    assert first.receipt["input_rdf"] != second.receipt["input_rdf"]
    assert first.receipt["post_graph"] == second.receipt["post_graph"]


def test_repeated_preview_deterministic_but_candidate_cannot_be_admitted_twice(profile):
    data = fixture()
    first = profile.preview(data, PROPOSAL, MODULE, EVIDENCE)
    assert first.receipt == profile.preview(data, PROPOSAL, MODULE, EVIDENCE).receipt
    with pytest.raises(ValueError, match="unique"):
        profile.preview(first.candidate, PROPOSAL, MODULE, EVIDENCE)


def test_no_random_hazard_evaluation(profile):
    model = profile.prepare(fixture(), PROPOSAL, MODULE, EVIDENCE)
    # A deterministic action has no waiting-time distribution. The hazard is unused.
    model.rules = (replace(model.rules[0], hazard=Expr("1 / 0")),)
    assert len(profile.rewrite(model).graph_delta.created_vertices) == 1


def test_authoritative_engine_refuses_forged_binding(profile):
    model = profile.prepare(fixture(), PROPOSAL, MODULE, EVIDENCE)
    rule = model.rules[0]
    match = Matcher().find_rule_matches(model.graph, rule, parameters=model.parameters,
                                        memory=model.memory, time=0.0)[0]
    match.bindings["comp_name"] = "forged.name"
    before = model.graph.state_hash
    with pytest.raises(MatchError):
        RewriteEngine().apply(graph=model.graph, boundary=model.boundary,
                              parameters=model.parameters, memory=model.memory,
                              rule=rule, match=match, time=0.0, delta_time=0.0,
                              event_index=1, event_id="forged")
    assert model.graph.state_hash == before


@pytest.mark.parametrize("count", [0, 1, 17])
def test_native_sparql_can_express_same_additive_transition(profile, count):
    # Existing native RDF functionality is a product baseline. This guards against
    # claiming that the additive membership operation itself requires OSAHR.
    data = fixture(count)
    result = profile.preview(data, PROPOSAL, MODULE, EVIDENCE)
    native = Graph()
    native += data
    native.update("""
        PREFIX ex: <urn:osahr:admission:>
        PREFIX prov: <http://www.w3.org/ns/prov#>
        INSERT {
            ?component a ex:Component, prov:Entity ;
                ex:name ?name ; ex:moduleDigest ?digest ; prov:wasDerivedFrom ?proposal .
            ?cell prov:hadMember ?component .
        } WHERE {}
    """, initBindings={"component": COMPONENT, "name": data.value(PROPOSAL, EX.name),
                       "digest": data.value(PROPOSAL, EX.moduleDigest),
                       "proposal": PROPOSAL, "cell": CELL})
    assert rdf_fingerprint(native) == rdf_fingerprint(result.candidate)
