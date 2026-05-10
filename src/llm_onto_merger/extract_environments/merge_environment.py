from collections import deque

from rdflib import Graph, URIRef

from ..alignment.alignment import Alignment
from ..ontology import KG2CODE_PREAMBLE, graph_to_string, local_name

_AVG_WORD = 6  # avg English word length excluding stopwords


class MergeEnvironmentConfig:
    def __init__(self, max_chars: int = 10_000) -> None:
        self.max_chars = max_chars


class MergeEnvironment:
    def __init__(
        self,
        onto_1: Graph,
        onto_2: Graph,
        alignments: list[Alignment],
        border1: deque[URIRef] | None = None,
        border2: deque[URIRef] | None = None,
    ) -> None:
        self.onto_1 = onto_1
        self.onto_2 = onto_2
        self.alignments = alignments
        self.border1: deque[URIRef] = border1 if border1 is not None else deque()
        self.border2: deque[URIRef] = border2 if border2 is not None else deque()

    @property
    def chars_count(self) -> int:
        onto_chars = (len(self.onto_1) + len(self.onto_2)) * 3 * _AVG_WORD
        border_chars = (len(self.border1) + len(self.border2)) * _AVG_WORD
        alignment_chars = len(self.alignments) * 2 * _AVG_WORD
        return onto_chars + border_chars + alignment_chars

    def to_string(self) -> str:
        border1_str = ", ".join(local_name(u) for u in self.border1)
        border2_str = ", ".join(local_name(u) for u in self.border2)
        alignments_str = "\n".join(al.to_string() for al in self.alignments)
        return f"""
            {KG2CODE_PREAMBLE}


            [Ontology_1]:
            {graph_to_string(self.onto_1)}
            [Border_1]:
            {border1_str}

            [Ontology_2]:
            {graph_to_string(self.onto_2)}
            [Border_2]:
            {border2_str}

            [Alignments]:
            {alignments_str}
        """
