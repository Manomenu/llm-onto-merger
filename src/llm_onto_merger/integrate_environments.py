from rdflib import Graph


def integrate_environments(merged_graphs: list[Graph]) -> Graph:
    """Combine all merged environment graphs into one Graph."""
    merged_onto = Graph()
    for graph in merged_graphs:
        for triple in graph:
            merged_onto.add(triple)
    return merged_onto
