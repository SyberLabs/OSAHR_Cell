"""Synthetic owner-workflow fixture using the real external PROV-O vocabulary."""
from hashlib import sha256
import json
from pathlib import Path

from rdflib import Graph, Literal, RDF, URIRef
from rdflib.namespace import PROV

from kernel import AdmissionProfile, EX
from osahr import Model

MODULE = b"def ping():\n    return 'pong'\n"
EVIDENCE = b'{"fixture":true,"scope":"synthetic evidence; no test execution or human approval"}'
PROPOSAL = URIRef("urn:fixture:proposal:ping")
CELL = URIRef("urn:fixture:cell")
COMPONENT = URIRef("urn:fixture:component:ping")


def fixture(count: int = 1) -> Graph:
    data = Graph()
    data.bind("ex", EX)
    data.bind("prov", PROV)
    for triple in (
        (CELL, RDF.type, EX.Cell), (CELL, RDF.type, PROV.Collection),
        (CELL, EX.membershipComplete, Literal(True)),
        (CELL, EX.snapshotRevision, Literal("synthetic-revision-1")),
        (PROPOSAL, RDF.type, EX.Proposal), (PROPOSAL, RDF.type, PROV.Entity),
        (PROPOSAL, EX.component, COMPONENT), (PROPOSAL, EX.name, Literal("edge.ping")),
        (PROPOSAL, EX.moduleDigest, Literal(sha256(MODULE).hexdigest())),
        (PROPOSAL, EX.evidenceDigest, Literal(sha256(EVIDENCE).hexdigest())),
    ):
        data.add(triple)
    for index in range(count):
        member = URIRef(f"urn:fixture:component:existing-{index:06d}")
        for triple in (
            (member, RDF.type, EX.Component), (member, RDF.type, PROV.Entity),
            (member, EX.name, Literal(f"existing.{index}")),
            (member, EX.moduleDigest, Literal(sha256(f"synthetic-{index}".encode()).hexdigest())),
            (CELL, PROV.hadMember, member),
        ):
            data.add(triple)
        if index == 0:
            data.add((PROPOSAL, EX.dependsOn, member))
    return data


def full_context(model: Model, data: Graph) -> Model:
    """Test oracle only: include the otherwise irrelevant existing components."""
    graph = model.graph.clone()
    cell = next(iter(graph.vertices_by_type["Cell"]))
    for member in sorted(data.objects(CELL, PROV.hadMember), key=str):
        vertex = graph.add_vertex("Component", {"name": str(data.value(member, EX.name))})
        graph.add_edge("PartOf", {"part": (vertex.entity_id,)}, {"cell": (cell,)})
    return Model(graph, model.boundary, model.rules, parameters=model.parameters, memory=model.memory)


if __name__ == "__main__":
    output = Path(__file__).resolve().parent / "artifacts"
    data = fixture()
    preview = AdmissionProfile().preview(data, PROPOSAL, MODULE, EVIDENCE)
    output.mkdir(exist_ok=True)
    for filename, graph in (("input.ttl", data), ("candidate.ttl", preview.candidate),
                            ("provenance.ttl", preview.provenance)):
        graph.serialize(output / filename, format="turtle")
    (output / "receipt.json").write_text(json.dumps(preview.receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(preview.receipt, indent=2))
