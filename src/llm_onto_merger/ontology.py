from pathlib import Path

from rdflib import Graph, URIRef

from .logger import get_logger

log = get_logger(__name__)


def local_name(uri: URIRef | str) -> str:
    """Return the local fragment of a URI (after # or last /)."""
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]


# Preamble included once at the top of a prompt that uses KG2Code representation.
# Tuple format: (subject, relation, object) — only outgoing triples are stored,
# so subject is always the entity itself.
KG2CODE_PREAMBLE = (
    "An OWL ontology entity is defined as follows: "
    "class Entity: "
    "   def __init__(self, uri, name, tuples=[]): "
    "       self.uri = uri; self.name = name; self.tuples = tuples; "
    "   def get_neighbors(self): "
    "       neighbors = set(); "
    "   for subject, relation, obj in self.tuples: neighbors.add(obj); "
    "       return list(neighbors) "
    "   def get_relation_information(self): "
    "       return [relation for subject, relation, obj in self.tuples] "
)


def graph_to_string(graph: Graph) -> str:
    """Render all entities in *graph* as KG2Code-style Entity(...) declarations.

    Each entity is represented by its outgoing triples only (subject == entity),
    so each declaration reads as a self-contained description of that entity.
    Does NOT include KG2CODE_PREAMBLE — prepend it once at the prompt level.
    """
    subjects = sorted(
        {s for s, _, _ in graph if isinstance(s, URIRef)},
        key=str,
    )
    lines = []
    for subj in subjects:
        tuple_strs = []
        for _, p, o in graph.triples((subj, None, None)):
            obj_repr = local_name(o) if isinstance(o, URIRef) else str(o)
            tuple_strs.append(
                f"('{local_name(subj)}', '{local_name(p)}', '{obj_repr}')"
            )
        lines.append(
            f"Entity('{subj}', name='{local_name(subj)}',"
            f" tuples=[{', '.join(tuple_strs)}])"
        )
    return "\n".join(lines)


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


def move_entity_triples(entity: URIRef, source: Graph, target: Graph) -> list[tuple]:
    """Move all triples where entity is subject or object from source to target."""
    triples = list(source.triples((entity, None, None))) + list(
        source.triples((None, None, entity))
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
