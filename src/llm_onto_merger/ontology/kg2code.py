from pydantic import BaseModel
from rdflib import Graph, Literal, URIRef

from ..logger import get_logger
from .uri import local_name

log = get_logger(__name__)

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
    "type":                "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
    "subClassOf":          "http://www.w3.org/2000/01/rdf-schema#subClassOf",
    "subPropertyOf":       "http://www.w3.org/2000/01/rdf-schema#subPropertyOf",
    "domain":              "http://www.w3.org/2000/01/rdf-schema#domain",
    "range":               "http://www.w3.org/2000/01/rdf-schema#range",
    "label":               "http://www.w3.org/2000/01/rdf-schema#label",
    "comment":             "http://www.w3.org/2000/01/rdf-schema#comment",
    "disjointWith":        "http://www.w3.org/2002/07/owl#disjointWith",
    "equivalentClass":     "http://www.w3.org/2002/07/owl#equivalentClass",
    "equivalentProperty":  "http://www.w3.org/2002/07/owl#equivalentProperty",
    "inverseOf":           "http://www.w3.org/2002/07/owl#inverseOf",
    "onProperty":          "http://www.w3.org/2002/07/owl#onProperty",
    "hasValue":            "http://www.w3.org/2002/07/owl#hasValue",
    "someValuesFrom":      "http://www.w3.org/2002/07/owl#someValuesFrom",
    "allValuesFrom":       "http://www.w3.org/2002/07/owl#allValuesFrom",
}

_INVALID_NAMES = frozenset({"", "merged"})


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
        uri_repr = (
            uri_to_code[subj_str]
            if uri_to_code and subj_str in uri_to_code
            else subj_str
        )
        tuple_strs = [
            f"('{local_name(subj)}', '{local_name(p)}', '{str(o) if isinstance(o, Literal) else local_name(o)}')"
            for _, p, o in graph.triples((subj, None, None))
        ]
        lines.append(
            f"Entity('{uri_repr}', name='{local_name(subj)}',"
            f" tuples=[{', '.join(tuple_strs)}])"
        )
    return "\n".join(lines)


def _is_valid_entity(e: Entity) -> bool:
    """Return False for placeholder/garbage entities the LLM sometimes emits."""
    name = e.name.strip()
    uri  = e.uri.strip()
    if not name or not uri:
        return False
    if name in _INVALID_NAMES:
        return False
    if not uri.startswith("http"):
        return False
    return True


def entities_to_graph(entities: list[Entity]) -> Graph:
    """Reconstruct an rdflib Graph from a list of Entity returned by the LLM.

    Tuple format is (subject_name, predicate_local, object_name_or_literal).
    Resolution strategy:
    - subject   → entity.uri (authoritative full URI)
    - predicate → WELL_KNOWN_PREDICATES lookup, else entity namespace + local
    - object    → matched entity URI by name, else Literal

    Entities with empty/invalid names or URIs are silently dropped.
    """
    valid_entities = [e for e in entities if _is_valid_entity(e)]
    if len(valid_entities) < len(entities):
        log.warning(
            "Dropped %d invalid/placeholder entities from LLM response "
            "(empty name, non-http URI, or known placeholder)",
            len(entities) - len(valid_entities),
        )

    name_to_uri = {e.name: e.uri for e in valid_entities}

    def _namespace(uri: str) -> str:
        return uri.rsplit("#", 1)[0] + "#" if "#" in uri else uri.rsplit("/", 1)[0] + "/"

    def _resolve_predicate(local: str, entity_ns: str) -> URIRef:
        if local in WELL_KNOWN_PREDICATES:
            return URIRef(WELL_KNOWN_PREDICATES[local])
        return URIRef(entity_ns + local)

    def _resolve_object(obj: str) -> URIRef | Literal:
        if obj in name_to_uri:
            return URIRef(name_to_uri[obj])
        return Literal(obj)

    graph = Graph()
    for entity in valid_entities:
        subj = URIRef(entity.uri)
        ns   = _namespace(entity.uri)
        for _, pred_local, obj_repr in entity.tuples:
            if not pred_local.strip():
                continue
            graph.add((subj, _resolve_predicate(pred_local, ns), _resolve_object(obj_repr)))
    return graph
