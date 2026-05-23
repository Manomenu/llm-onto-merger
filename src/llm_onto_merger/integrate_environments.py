from rdflib import Graph


def integrate_environments(
    merged_graphs: list[Graph],
    leftover_1: Graph,
    leftover_2: Graph,
) -> Graph:
    """Combine all merged environment graphs and leftovers into one Graph."""
    merged_onto = Graph()
    for graph in (*merged_graphs, leftover_1, leftover_2):
        for triple in graph:
            merged_onto.add(triple)
    return merged_onto
