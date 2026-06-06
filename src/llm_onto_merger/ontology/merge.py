from rdflib import OWL, Graph, URIRef

from ..alignment.alignment import Alignment


def apply_alignments(onto_1: Graph, onto_2: Graph, alignments: list[Alignment]) -> Graph:
    """Naive alignment-based merge: union of both ontologies with owl:equivalentClass
    links for each aligned pair.  Both namespaces are preserved so cross-ontology
    metrics can be computed correctly.
    """
    result = Graph()
    for t in onto_1:
        result.add(t)
    for t in onto_2:
        result.add(t)
    for al in alignments:
        e1 = URIRef(al.entity1)
        e2 = URIRef(al.entity2)
        if e1 != e2:
            result.add((e1, OWL.equivalentClass, e2))
    return result


def collapse_alignments(onto_1: Graph, onto_2: Graph, alignments: list[Alignment]) -> Graph:
    """Union of both ontologies with each aligned entity2 URI replaced by entity1.

    Used as a deterministic fallback when the LLM response cannot be parsed —
    guarantees a valid graph at the cost of losing onto2 namespace identity.
    """
    result = Graph()
    for t in onto_1:
        result.add(t)
    for t in onto_2:
        result.add(t)
    for al in alignments:
        e1 = URIRef(al.entity1)
        e2 = URIRef(al.entity2)
        if e1 == e2:
            continue
        for _, p, o in list(result.triples((e2, None, None))):
            result.remove((e2, p, o))
            result.add((e1, p, o))
        for s, p, _ in list(result.triples((None, None, e2))):
            result.remove((s, p, e2))
            result.add((s, p, e1))
    return result
