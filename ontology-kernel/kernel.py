"""Detached admission preview: external RDF -> existing GrokCell rule -> RDF.

No source execution, stochastic scheduling, approval authority, or live writes.
Run from the repository with PYTHONPATH containing `grokcell;ontology-kernel`.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import platform

from pyshacl import validate
from rdflib import Graph, Literal, Namespace, RDF, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import OWL, PROV

from grokcell.construction import construction_model
from osahr import Matcher, Model
from osahr.canonical import stable_hash
from osahr.rewrite import RewriteEngine, RewriteResult

EX = Namespace("urn:osahr:admission:")
HERE = Path(__file__).resolve().parent
# Locality is proved for this exact additive rule and schema, not arbitrary rules.
ASSEMBLY_RULE_HASH = "eb478689144821a428961fea0f7f8285de8672ef645b6fcd9be58bfa4c471856"
ASSEMBLY_SCHEMA_HASH = "9c623d8c1ae28b0136834a36e60b25a84832d54c4fed71a8ca7d76fce5a170a1"


def rdf_fingerprint(graph: Graph) -> str:
    """Use RDFLib's blank-node canonicalization and OSAHR's existing hash codec."""
    return stable_hash(sorted(
        tuple(term.n3() for term in triple) for triple in to_canonical_graph(graph)
    ))


@dataclass
class Preview:
    candidate: Graph
    provenance: Graph
    receipt: dict
    rewrite: RewriteResult


class AdmissionProfile:
    """A fixed local profile. Treat its configuration as owner-controlled."""

    def __init__(self) -> None:
        self.shapes = Graph().parse(HERE / "shapes.ttl", format="turtle")
        ontology_bytes = (HERE / "vendor" / "prov-o.ttl").read_bytes()
        self.ontology = Graph().parse(data=ontology_bytes, format="turtle")
        for term in (PROV.Entity, PROV.Collection, PROV.Activity):
            if (term, RDF.type, OWL.Class) not in self.ontology:
                raise ValueError(f"External PROV-O class is missing: {term}")
        if (PROV.hadMember, RDF.type, OWL.ObjectProperty) not in self.ontology:
            raise ValueError("External PROV-O membership property is missing")
        self.ontology_digest = sha256(ontology_bytes).hexdigest()

    def check(self, graph: Graph) -> None:
        # No network imports, rules, JS, or inferred authorization.
        conforms, _, report = validate(
            graph, shacl_graph=self.shapes, inference="none",
            advanced=False, do_owl_imports=False, inplace=False,
        )
        if not conforms:
            raise ValueError(f"Ontology profile violation:\n{report}")

    def prepare(self, data: Graph, proposal: URIRef, module: bytes, evidence: bytes) -> Model:
        self.check(data)
        cells = list(data.subjects(RDF.type, EX.Cell))
        if len(cells) != 1 or (proposal, RDF.type, EX.Proposal) not in data:
            raise ValueError("Exactly one cell and an explicitly typed proposal are required")
        for predicate, content in ((EX.moduleDigest, module), (EX.evidenceDigest, evidence)):
            if str(data.value(proposal, predicate)) != sha256(content).hexdigest():
                raise ValueError(f"Exact bytes do not match {predicate}")
        members = sorted(set(data.objects(cells[0], PROV.hadMember)), key=str)
        dependencies = set(data.objects(proposal, EX.dependsOn))
        if not dependencies <= set(members):
            raise ValueError("A dependency is absent from the declared complete cell membership")
        names = [str(data.value(member, EX.name)) for member in members]
        name = str(data.value(proposal, EX.name))
        component = data.value(proposal, EX.component)
        if len(set(names)) != len(names) or name in names:
            raise ValueError("Component names must be unique within this cell")
        # The proposal's own component pointer is the one permitted reference.
        refs = set(data.triples((None, None, component)))
        if (any(data.triples((component, None, None)))
                or any(data.triples((None, component, None)))
                or refs != {(proposal, EX.component, component)}):
            raise ValueError("Proposed component IRI is already in use")

        # This rule reads Cell + Slot only and deletes nothing. Existing components
        # are an untouched frame, so do not copy them into a temporary DPO graph.
        # The RDF checks above still inspect declared membership and dependencies.
        model = construction_model()
        if model.rules[0].hash != ASSEMBLY_RULE_HASH or model.graph.schema.hash != ASSEMBLY_SCHEMA_HASH:
            raise ValueError("The assembly rule/schema changed; re-establish the locality proof")
        slot = model.boundary.handles["proposal"].binding
        model.graph.set_vertex_attributes(slot, {"pending": True, "name": name, "constraint": "preview_only"})
        return Model(model.graph, model.boundary, model.rules,
                     parameters=model.parameters, memory=model.memory,
                     model_id="ontology-preview", version="1")

    @staticmethod
    def rewrite(model: Model, *, bound: bool = True) -> RewriteResult:
        rule = model.rules[0]
        if bound:
            matches = Matcher().find_pattern_matches(
                model.graph, rule.left, rule_id=rule.rule_id,
                prebound_vertices={
                    "cell": next(iter(model.graph.vertices_by_type["Cell"])),
                    "slot": model.boundary.handles["proposal"].binding,
                },
                prebound_edges={},
            )
        else:
            # Existing exhaustive implementation is the differential oracle.
            matches = Matcher().find_rule_matches(
                model.graph, rule, parameters=model.parameters, memory=model.memory, time=0.0,
            )
        if len(matches) != 1:
            raise ValueError("The profile requires exactly one assembly match")
        return RewriteEngine().apply(
            graph=model.graph, boundary=model.boundary, parameters=model.parameters,
            memory=model.memory, rule=rule, match=matches[0],
            time=0.0, delta_time=0.0, event_index=1, event_id="ontology-preview",
        )

    def preview(self, data: Graph, proposal: URIRef, module: bytes, evidence: bytes) -> Preview:
        model = self.prepare(data, proposal, module, evidence)
        result = self.rewrite(model)
        # Export only the result of the existing rule, preserving all input triples.
        component_vertex = result.graph.vertices[result.post_vertex_map["comp"]]
        cell = next(data.subjects(RDF.type, EX.Cell))
        component = data.value(proposal, EX.component)
        candidate = Graph()
        for prefix, namespace in data.namespaces():
            candidate.bind(prefix, namespace)
        candidate += data
        for triple in (
            (component, RDF.type, EX.Component), (component, RDF.type, PROV.Entity),
            (component, EX.name, Literal(component_vertex.attributes["name"])),
            (component, EX.moduleDigest, data.value(proposal, EX.moduleDigest)),
            (component, PROV.wasDerivedFrom, proposal), (cell, PROV.hadMember, component),
        ):
            candidate.add(triple)
        self.check(candidate)
        receipt = {
            "profile": "osahr-ontology-admission-preview/1",
            "claim": "candidate_transition_only", "live_action_executed": False,
            "proposal": str(proposal), "revision": str(data.value(cell, EX.snapshotRevision)),
            "input_rdf": rdf_fingerprint(data), "candidate_rdf": rdf_fingerprint(candidate),
            "shapes": rdf_fingerprint(self.shapes), "external_ontology_sha256": self.ontology_digest,
            "module_sha256": sha256(module).hexdigest(), "evidence_sha256": sha256(evidence).hexdigest(),
            "rule": model.rules[0].hash, "schema": model.graph.schema.hash,
            "profile_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "environment": {"python": platform.python_version(),
                            "rdflib": version("rdflib"), "pyshacl": version("pyshacl")},
            "pre_graph": model.graph.state_hash, "post_graph": result.graph.state_hash,
            "graph_scope": "Cell + Slot footprint; existing memberships are retained in RDF",
        }
        receipt_id = stable_hash(receipt)
        provenance = Graph()
        provenance.bind("prov", PROV)
        provenance.bind("ex", EX)
        activity = URIRef(f"urn:osahr:preview:{receipt_id}")
        before = URIRef(f"urn:osahr:snapshot:{receipt['input_rdf']}")
        after = URIRef(f"urn:osahr:snapshot:{receipt['candidate_rdf']}")
        proof = URIRef(f"urn:sha256:{receipt['evidence_sha256']}")
        module_entity = URIRef(f"urn:sha256:{receipt['module_sha256']}")
        for triple in (
            (activity, RDF.type, PROV.Activity), (activity, RDF.type, EX.Preview),
            (before, RDF.type, PROV.Entity), (after, RDF.type, PROV.Entity),
            (after, RDF.type, EX.CandidateSnapshot), (proof, RDF.type, PROV.Entity),
            (module_entity, RDF.type, PROV.Entity), (activity, PROV.used, module_entity),
            (activity, PROV.used, before), (activity, PROV.used, proof),
            (after, PROV.wasGeneratedBy, activity), (after, PROV.wasDerivedFrom, before),
        ):
            provenance.add(triple)
        return Preview(candidate, provenance, receipt, result)
