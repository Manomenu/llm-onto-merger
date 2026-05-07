import random
from collections import deque
from collections.abc import Callable

from rdflib import Graph, URIRef

from .alignment.alignment import Alignment
from .ontology import KG2CODE_PREAMBLE, graph_to_string, local_name, move_entity_triples

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
        return (
            f"{KG2CODE_PREAMBLE}\n\n"
            f"Ontology_1:\n{graph_to_string(self.onto_1)}\n\n"
            f"Entities that need to keep their names and exist in Merged_Ontology: {border1_str}\n"
            f"\nOntology_2:\n{graph_to_string(self.onto_2)}\n\n"
            f"Entities that need to keep their names and exist in Merged_Ontology: {border2_str}\n"
            f"\nAlignments:\n{alignments_str}"
        )


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


class _GraphSide:
    def __init__(
        self,
        source: Graph,
        sub: Graph,
        seen: set[URIRef],
        border: deque[URIRef],
    ) -> None:
        self.source = source
        self.sub = sub
        self.seen = seen
        self.border = border


def _new_border_candidates(triples: list[tuple], seen: set[URIRef]) -> list[URIRef]:
    """Extract unseen URIRef nodes from both subject and object positions,
    shuffled to avoid predicate bias."""
    candidates = {
        node
        for (subj, _, obj) in triples
        for node in (subj, obj)
        if isinstance(node, URIRef) and node not in seen
    }
    result = list(candidates)
    random.shuffle(result)
    return result


def _expand_border(
    side: _GraphSide,
    partner: _GraphSide,
    pop_by_entity: Callable[[str], Alignment | None],
    get_partner_entity: Callable[[Alignment], str],
    alignments: list[Alignment],
) -> None:
    candidate = side.border.popleft()
    new_triples = move_entity_triples(candidate, side.source, side.sub)
    new_candidates = _new_border_candidates(new_triples, side.seen)
    side.border.extend(new_candidates)
    side.seen.update(new_candidates)

    al = pop_by_entity(str(candidate))
    if al is not None:
        alignments.append(al)
        partner_entity = URIRef(get_partner_entity(al))
        if partner_entity not in partner.seen:
            partner.seen.add(partner_entity)
            partner_triples = move_entity_triples(
                partner_entity, partner.source, partner.sub
            )
            partner_candidates = _new_border_candidates(partner_triples, partner.seen)
            partner.border.extend(partner_candidates)
            partner.seen.update(partner_candidates)


def _build_merge_environment(
    source_1: Graph,
    source_2: Graph,
    alignment_pool: _AlignmentPool,
    config: MergeEnvironmentConfig,
) -> MergeEnvironment:
    seed_alignment = alignment_pool.pop()
    seed1 = URIRef(seed_alignment.entity1)
    seed2 = URIRef(seed_alignment.entity2)

    sub1, sub2 = Graph(), Graph()
    seen1, seen2 = {seed1}, {seed2}

    seed_triples1 = move_entity_triples(seed1, source_1, sub1)
    seed_triples2 = move_entity_triples(seed2, source_2, sub2)

    init_border1 = _new_border_candidates(seed_triples1, seen1)
    init_border2 = _new_border_candidates(seed_triples2, seen2)
    seen1.update(init_border1)
    seen2.update(init_border2)

    env = MergeEnvironment(
        onto_1=sub1,
        onto_2=sub2,
        alignments=[seed_alignment],
        border1=deque(init_border1),
        border2=deque(init_border2),
    )

    if env.chars_count > config.max_chars:
        return env

    side1 = _GraphSide(source_1, sub1, seen1, env.border1)
    side2 = _GraphSide(source_2, sub2, seen2, env.border2)

    while env.border1 or env.border2:
        if env.chars_count > config.max_chars:
            return env

        if env.border1:
            _expand_border(
                side1,
                side2,
                alignment_pool.pop_by_entity1,
                lambda a: a.entity2,
                env.alignments,
            )

        if env.border2:
            _expand_border(
                side2,
                side1,
                alignment_pool.pop_by_entity2,
                lambda a: a.entity1,
                env.alignments,
            )

    return env


def extract_environments(
    onto_1: Graph,
    onto_2: Graph,
    alignments: list[Alignment],
    config: MergeEnvironmentConfig,
) -> tuple[list[MergeEnvironment], Graph, Graph]:
    """Extract merge environments and return leftover graphs.

    Returns:
        (environments, leftover_1, leftover_2) where leftover_* are the triples
        from onto_1/onto_2 that were not absorbed into any MergeEnvironment.
    """
    # Work on copies — consumed triples are removed as environments are built
    source_1 = Graph()
    source_2 = Graph()
    for triple in onto_1:
        source_1.add(triple)
    for triple in onto_2:
        source_2.add(triple)

    alignment_pool = _AlignmentPool(alignments)
    environments: list[MergeEnvironment] = []

    while not alignment_pool.is_empty():
        env = _build_merge_environment(source_1, source_2, alignment_pool, config)
        environments.append(env)

    return environments, source_1, source_2
