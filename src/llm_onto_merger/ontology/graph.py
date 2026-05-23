import re
from pathlib import Path

from rdflib import RDFS, Graph, URIRef

from ..logger import get_logger

log = get_logger(__name__)

_OWL_DISJOINT_WITH = URIRef("http://www.w3.org/2002/07/owl#disjointWith")


def _relabel_entities(g: Graph) -> int:
    """For every URI that carries an rdfs:label, replace its local name (the
    fragment after '#', or the last path segment after '/') with the label
    value — whitespace is replaced by '_'.  The label triple is removed after
    the rename.  Entities whose computed target URI is already occupied are
    skipped to avoid silent merges.  Returns the count of renamed entities."""
    renames: dict[URIRef, tuple[URIRef, object]] = {}
    seen_new: set[URIRef] = set()
    existing: frozenset[URIRef] = frozenset(
        s for s in g.subjects() if isinstance(s, URIRef)
    )

    for s, _, label_o in g.triples((None, RDFS.label, None)):
        if not isinstance(s, URIRef) or s in renames:
            continue
        label_str = str(label_o).strip()
        if not label_str:
            continue

        safe = re.sub(r"\s+", "_", label_str)
        uri_str = str(s)

        if "#" in uri_str:
            new_uri = URIRef(uri_str.rsplit("#", 1)[0] + "#" + safe)
        elif "/" in uri_str:
            new_uri = URIRef(uri_str.rsplit("/", 1)[0] + "/" + safe)
        else:
            continue

        if new_uri == s or new_uri in seen_new or new_uri in existing:
            continue

        renames[s] = (new_uri, label_o)
        seen_new.add(new_uri)

    for old, (new, label_o) in renames.items():
        for s, p, o in list(g.triples((old, None, None))):
            g.remove((s, p, o))
            g.add((new, p, o))
        for s, p, o in list(g.triples((None, None, old))):
            g.remove((s, p, o))
            g.add((s, p, new))
        g.remove((new, RDFS.label, label_o))

    return len(renames)


def create_ontology(ontology_path: Path) -> Graph:
    """Load an OWL/RDF ontology from the given path.

    Post-load preprocessing:
    - disjointWith triples are stripped — O(N²) symmetry constraints that add
      noise to the LLM merge step.
    - Each entity with an rdfs:label has its URI local name replaced with the
      label (whitespace → '_'), and the label triple is removed so the name is
      not duplicated in the serialised representation.
    """
    g = Graph()
    g.parse(str(ontology_path))

    disjoint_triples = list(g.triples((None, _OWL_DISJOINT_WITH, None)))
    for triple in disjoint_triples:
        g.remove(triple)

    renamed = _relabel_entities(g)

    log.info(
        "Ontology loaded from %s (%d triples, %d disjointWith removed, %d entities relabelled)",
        ontology_path,
        len(g),
        len(disjoint_triples),
        renamed,
    )
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
