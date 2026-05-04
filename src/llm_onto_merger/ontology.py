from pathlib import Path

from rdflib import Graph, URIRef

from .logger import get_logger

log = get_logger(__name__)


def create_ontology(ontology_path: Path) -> Graph:
    """Load an OWL/RDF ontology from the given path."""
    g = Graph()
    g.parse(str(ontology_path))
    log.info("Ontology loaded from %s (%d triples)", ontology_path, len(g))
    return g


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
