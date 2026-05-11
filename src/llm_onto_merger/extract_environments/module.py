import random
from collections import deque
from collections.abc import Callable

from rdflib import Graph, URIRef

from ..alignment.alignment import Alignment
from ..logger import get_logger
from ..ontology import move_entity_triples
from .merge_environment import MergeEnvironment, MergeEnvironmentConfig

log = get_logger(__name__)


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


class ExtractEnvironmentsModule:
    def __init__(self, config: MergeEnvironmentConfig) -> None:
        self.config = config

    def extract(
        self,
        onto_1: Graph,
        onto_2: Graph,
        alignments: list[Alignment],
    ) -> tuple[list[MergeEnvironment], Graph, Graph]:
        """Extract merge environments from two ontologies.

        Returns:
            (environments, leftover_1, leftover_2) where leftover_* are the triples
            from onto_1/onto_2 that were not absorbed into any MergeEnvironment.
        """
        source_1 = Graph()
        source_2 = Graph()
        for triple in onto_1:
            source_1.add(triple)
        for triple in onto_2:
            source_2.add(triple)

        alignment_pool = _AlignmentPool(alignments)
        environments: list[MergeEnvironment] = []

        log.info(
            "Extracting environments | alignments: %d | max_chars: %d",
            len(alignments),
            self.config.max_chars,
        )

        while not alignment_pool.is_empty():
            env = _build_merge_environment(
                source_1, source_2, alignment_pool, self.config
            )
            environments.append(env)

        log.info("Extracted %d environments", len(environments))
        return environments, source_1, source_2


# TODO change extraction, so it is forbidded to extract border into another environment,
# Also forbid a node from alignment pair to be a part of border.
# It should either be outside of all environments or fully inside one environment.
# It means, that if a node is added to the border, immediatelly add its peer fro alignment pair and add all their triple to the environment, no matter the limit.
