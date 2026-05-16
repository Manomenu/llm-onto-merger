from pathlib import Path

from pydantic import BaseModel
from rdflib import Graph, Literal, URIRef

from .logger import get_logger

log = get_logger(__name__)


def local_name(uri: URIRef | str) -> str:
    """Return the local fragment of a URI (after # or last /)."""
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]


# Preamble included once at the top of a prompt that uses KG2Code representation.
# Tuple format: (subject, relation, object) — only outgoing triples are stored,
# so subject is always the entity itself.
KG2CODE_PREAMBLE = """
An OWL ontology entity is defined as follows:

class Entity:
    def __init__(self, uri, name, tuples=[]):
        self.uri = uri
        self.name = name
        self.tuples = tuples

    def get_neighbors(self):
        neighbors = set()
        for subject, relation, obj in self.tuples:
            neighbors.add(obj)
            return list(neighbors)

    def get_relation_information(self):
        return [relation for subject, relation, obj in self.tuples]
"""

# Standard RDF/OWL/RDFS predicates resolvable from local name alone.
WELL_KNOWN_PREDICATES: dict[str, str] = {
    "type": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
    "subClassOf": "http://www.w3.org/2000/01/rdf-schema#subClassOf",
    "subPropertyOf": "http://www.w3.org/2000/01/rdf-schema#subPropertyOf",
    "domain": "http://www.w3.org/2000/01/rdf-schema#domain",
    "range": "http://www.w3.org/2000/01/rdf-schema#range",
    "label": "http://www.w3.org/2000/01/rdf-schema#label",
    "comment": "http://www.w3.org/2000/01/rdf-schema#comment",
    "disjointWith": "http://www.w3.org/2002/07/owl#disjointWith",
    "equivalentClass": "http://www.w3.org/2002/07/owl#equivalentClass",
    "equivalentProperty": "http://www.w3.org/2002/07/owl#equivalentProperty",
    "inverseOf": "http://www.w3.org/2002/07/owl#inverseOf",
    "onProperty": "http://www.w3.org/2002/07/owl#onProperty",
    "hasValue": "http://www.w3.org/2002/07/owl#hasValue",
    "someValuesFrom": "http://www.w3.org/2002/07/owl#someValuesFrom",
    "allValuesFrom": "http://www.w3.org/2002/07/owl#allValuesFrom",
}


class Entity(BaseModel):
    uri: str
    name: str
    tuples: list[tuple[str, str, str]]


def graph_to_string(
    graph: Graph,
    uri_to_code: dict[str, str] | None = None,
) -> str:
    """Render all entities in *graph* as KG2Code-style Entity(...) declarations.

    Does NOT include KG2CODE_PREAMBLE — prepend it once at the prompt level.

    uri_to_code — when provided, each subject URI is replaced with its short
    code (e.g. 'aa', 'ab') to reduce prompt size.  The caller is responsible
    for restoring full URIs from the reverse mapping after the LLM responds.
    """
    subjects = sorted(
        {s for s, _, _ in graph if isinstance(s, URIRef)},
        key=str,
    )
    lines = []
    for subj in subjects:
        subj_str = str(subj)
        uri_repr = uri_to_code[subj_str] if uri_to_code and subj_str in uri_to_code else subj_str
        tuple_strs = [
            f"('{local_name(subj)}', '{local_name(p)}', '{str(o) if isinstance(o, Literal) else local_name(o)}')"
            for _, p, o in graph.triples((subj, None, None))
        ]
        lines.append(
            f"Entity('{uri_repr}', name='{local_name(subj)}',"
            f" tuples=[{', '.join(tuple_strs)}])"
        )
    return "\n".join(lines)


def entities_to_graph(entities: list[Entity]) -> Graph:
    """Reconstruct an rdflib Graph from a list of Entity returned by the LLM.

    Tuple format is (subject_name, predicate_local, object_name_or_literal).
    Resolution strategy:
    - subject   → entity.uri (authoritative full URI)
    - predicate → WELL_KNOWN_PREDICATES lookup, else entity namespace + local
    - object    → matched entity URI by name, else Literal
    """
    name_to_uri = {e.name: e.uri for e in entities}

    def _namespace(uri: str) -> str:
        return (
            uri.rsplit("#", 1)[0] + "#" if "#" in uri else uri.rsplit("/", 1)[0] + "/"
        )

    def _resolve_predicate(local: str, entity_ns: str) -> URIRef:
        if local in WELL_KNOWN_PREDICATES:
            return URIRef(WELL_KNOWN_PREDICATES[local])
        return URIRef(entity_ns + local)

    def _resolve_object(obj: str) -> URIRef | Literal:
        if obj in name_to_uri:
            return URIRef(name_to_uri[obj])
        return Literal(obj)

    graph = Graph()
    for entity in entities:
        subj = URIRef(entity.uri)
        ns = _namespace(entity.uri)
        for _, pred_local, obj_repr in entity.tuples:
            graph.add(
                (subj, _resolve_predicate(pred_local, ns), _resolve_object(obj_repr))
            )
    return graph


def save_ontology(graph: Graph, out_dir: Path, name: str = "merged_ontology") -> Path:
    """Serialize *graph* as OWL (RDF/XML) to *out_dir*/<name>.owl."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.owl"
    graph.serialize(destination=str(out), format="xml")
    log.info("Saved %s to %s (%d triples)", name, out, len(graph))
    return out


_OWL_DISJOINT_WITH = URIRef("http://www.w3.org/2002/07/owl#disjointWith")


def create_ontology(ontology_path: Path) -> Graph:
    """Load an OWL/RDF ontology from the given path.

    disjointWith triples are stripped on load — they are structural symmetry
    constraints that add O(N²) noise and confuse the LLM merge step.
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
