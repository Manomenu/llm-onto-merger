from rdflib import Graph, URIRef

from ..alignment.alignment import Alignment


def apply_alignments(onto_1: Graph, onto_2: Graph, alignments: list[Alignment]) -> Graph:
    """Naive alignment-based merge: union of both ontologies with each aligned
    entity2 collapsed into entity1 (all its triples re-pointed to entity1's URI).

    Useful as a baseline to compare against the LLM-merged ontology.
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
