from rdflib import Graph, URIRef

from .alignment.alignment import Alignment
from .ontology import get_border


class MergeEnvironmentConfig:
    def __init__(self, max_chars: int = 10_000) -> None:
        self.max_chars = max_chars


class MergeEnvironment:
    def __init__(
        self,
        onto_1: Graph,
        onto_2: Graph,
        alignments: list[Alignment],
        border1: list[URIRef] | None = None,
        border2: list[URIRef] | None = None,
    ) -> None:
        self.onto_1 = onto_1
        self.onto_2 = onto_2
        self.alignments = alignments
        self.border1: list[URIRef] = border1 if border1 is not None else []
        self.border2: list[URIRef] = border2 if border2 is not None else []

    @property
    def chars_count(self) -> int:
        return len(self.to_string())

    def to_string(self) -> str:
        pass


class _AlignmentPool:
    def __init__(self, alignments: list[Alignment]) -> None:
        # sorted ascending — pop() from the end gives highest measure in O(1)
        self._sorted: list[Alignment] = sorted(alignments, key=lambda a: a.measure)
        self._by_entity1: dict[str, Alignment] = {a.entity1: a for a in self._sorted}
        self._by_entity2: dict[str, Alignment] = {a.entity2: a for a in self._sorted}

    def pop(self) -> Alignment:
        alignment = self._sorted.pop()
        self._by_entity1.pop(alignment.entity1, None)
        self._by_entity2.pop(alignment.entity2, None)
        return alignment

    def pop_by_entity1(self, entity1: str) -> Alignment | None:
        alignment = self._by_entity1.pop(entity1, None)
        if alignment is not None:
            self._by_entity2.pop(alignment.entity2, None)
            self._sorted.remove(alignment)
        return alignment

    def pop_by_entity2(self, entity2: str) -> Alignment | None:
        alignment = self._by_entity2.pop(entity2, None)
        if alignment is not None:
            self._by_entity1.pop(alignment.entity1, None)
            self._sorted.remove(alignment)
        return alignment

    def is_empty(self) -> bool:
        return not self._sorted


def _build_merge_environment(
    onto_1: Graph,
    onto_2: Graph,
    alignment_pool: _AlignmentPool,
    config: MergeEnvironmentConfig,
) -> MergeEnvironment:
    seed_alignment = alignment_pool.pop()

    seed1 = URIRef(seed_alignment.entity1)
    seed2 = URIRef(seed_alignment.entity2)

    sub1 = Graph()
    for triple in onto_1.triples((seed1, None, None)):
        sub1.add(triple)

    sub2 = Graph()
    for triple in onto_2.triples((seed2, None, None)):
        sub2.add(triple)

    env = MergeEnvironment(
        onto_1=sub1,
        onto_2=sub2,
        alignments=[seed_alignment],
        border1=get_border([seed1], onto_1),
        border2=get_border([seed2], onto_2),
    )

    while True:
        # TODO: determine next candidate (border entity or alignment whose
        # entities appear in the current border)
        next_candidate_chars = 0  # TODO: estimate chars for next candidate

        if env.chars_count + next_candidate_chars > config.max_chars:
            return env

        # TODO: add next candidate to env (extend sub-graphs, borders, alignments)
        break  # placeholder — remove once loop body is implemented


def extract_environments(
    onto_1: Graph,
    onto_2: Graph,
    alignments: list[Alignment],
    config: MergeEnvironmentConfig,
) -> list[MergeEnvironment]:
    alignment_pool = _AlignmentPool(alignments)
    environments: list[MergeEnvironment] = []

    while not alignment_pool.is_empty():
        env = _build_merge_environment(onto_1, onto_2, alignment_pool, config)
        environments.append(env)

    return environments
