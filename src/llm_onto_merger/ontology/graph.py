from pathlib import Path

from rdflib import Graph, URIRef

from ..logger import get_logger

log = get_logger(__name__)

_OWL_DISJOINT_WITH = URIRef("http://www.w3.org/2002/07/owl#disjointWith")


def create_ontology(ontology_path: Path) -> Graph:
    """Load an OWL/RDF ontology from the given path.

    disjointWith triples are stripped on load — they are structural symmetry
    constraints that add up to O(N^2) noise and confuse the LLM merge step.
    """
    g = Graph()
    g.parse(str(ontology_path))
    disjoint_triples = list(g.triples((None, _OWL_DISJOINT_WITH, None)))
    for triple in disjoint_triples:
        g.remove(triple)
    if disjoint_triples:
        log.info(
            "Ontology loaded from %s (%d triples, %d disjointWith removed)",
            ontology_path, len(g), len(disjoint_triples),
        )
    else:
        log.info("Ontology loaded from %s (%d triples)", ontology_path, len(g))
    return g


def save_ontology(graph: Graph, out_dir: Path, name: str = "merged_ontology") -> Path:
    """Serialize *graph* as OWL (RDF/XML) to *out_dir*/<name>.owl."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.owl"
    graph.serialize(destination=str(out), format="xml")
    log.info("Saved %s to %s (%d triples)", name, out, len(graph))
    return out


def get_entity(graph: Graph, entity_id: URIRef) -> URIRef | None:
    """Return entity_id if it exists in the graph, else None."""
    if (entity_id, None, None) in graph or (None, None, entity_id) in graph:
        return entity_id
    return None


def get_neighbors(graph: Graph, entity_id: URIRef) -> list[URIRef]:
    """Return all URIRef nodes directly connected to entity_id (in or out)."""
    neighbors: set[URIRef] = set()
    for _, _, obj in graph.triples((entity_id, None, None)):
        if isinstance(obj, URIRef):
            neighbors.add(obj)
    for subj, _, _ in graph.triples((None, None, entity_id)):
        if isinstance(subj, URIRef):
            neighbors.add(subj)
    return list(neighbors)


def move_entity_triples(entity: URIRef, source: Graph, target: Graph) -> list[tuple]:
    """Move all triples where entity is subject or object from source to target."""
    triples = (
        list(source.triples((entity, None, None)))
        + list(source.triples((None, None, entity)))
    )
    for triple in triples:
        target.add(triple)
        source.remove(triple)
    return triples


def get_border(entity_ids: list[URIRef], graph: Graph) -> list[URIRef]:
    """Return nodes in graph that are not in entity_ids but are directly
    connected to at least one node that is."""
    entity_set = set(entity_ids)
    border: set[URIRef] = set()
    for eid in entity_ids:
        for neighbor in get_neighbors(graph, eid):
            if neighbor not in entity_set:
                border.add(neighbor)
    return list(border)
