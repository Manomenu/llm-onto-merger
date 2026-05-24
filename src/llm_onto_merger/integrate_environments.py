from rdflib import Graph, URIRef

from .ontology.kg2code import build_alias_map


def integrate_environments(
    merged_graphs: list[Graph],
    leftover_1: Graph,
    leftover_2: Graph,
    code_to_ns: dict[str, str],
) -> Graph:
    """Combine all merged environment graphs and leftovers into one Graph.

    Alias triples produced by the LLM (predicate http://merged#alias) are used
    to build a substitution map: any triple whose subject or object is a known
    old URI is rewritten to the canonical merged URI before being added.
    """
    alias_map = build_alias_map(merged_graphs, code_to_ns)

    def _sub(uri: str) -> str:
        return alias_map.get(uri, uri)

    merged_onto = Graph()
    for graph in (*merged_graphs, leftover_1, leftover_2):
        for s, p, o in graph:
            s2 = URIRef(_sub(str(s))) if isinstance(s, URIRef) else s
            o2 = URIRef(_sub(str(o))) if isinstance(o, URIRef) else o
            merged_onto.add((s2, p, o2))
    return merged_onto
