import bisect
from collections import deque

from rdflib import Graph, URIRef

from ..alignment.alignment import Alignment
from ..logger import get_logger
from ..ontology import local_name, move_entity_triples
from .merge_environment import (
    MergeEnvironment,
    MergeEnvironmentConfig,
    _namespace_of,
    build_namespace_codec,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Alignment pool
# ---------------------------------------------------------------------------

class _AlignmentPool:
    """Sorted pool of alignment pairs. pop() always yields the highest-measure pair."""

    def __init__(self, alignments: list[Alignment]) -> None:
        self._sorted: list[Alignment] = sorted(alignments, key=lambda a: a.measure)
        self._by_entity1: dict[str, Alignment] = {a.entity1: a for a in self._sorted}
        self._by_entity2: dict[str, Alignment] = {a.entity2: a for a in self._sorted}

    def pop(self) -> Alignment:
        al = self._sorted.pop()
        self._by_entity1.pop(al.entity1, None)
        self._by_entity2.pop(al.entity2, None)
        return al

    def pop_by_entity1(self, entity1: str) -> Alignment | None:
        al = self._by_entity1.pop(entity1, None)
        if al is not None:
            self._by_entity2.pop(al.entity2, None)
            self._sorted.remove(al)
        return al

    def pop_by_entity2(self, entity2: str) -> Alignment | None:
        al = self._by_entity2.pop(entity2, None)
        if al is not None:
            self._by_entity1.pop(al.entity1, None)
            self._sorted.remove(al)
        return al

    def contains(self, uri: str) -> bool:
        return uri in self._by_entity1 or uri in self._by_entity2

    def is_empty(self) -> bool:
        return not self._sorted


# ---------------------------------------------------------------------------
# Environment builder
# ---------------------------------------------------------------------------

def _build_merge_environment(
    source_1: Graph,
    source_2: Graph,
    alignment_pool: _AlignmentPool,
    config: MergeEnvironmentConfig,
    env_idx: int,
    global_frozen: set[URIRef],
    code_to_ns: dict[str, str],
    ns_to_code: dict[str, str],
    well_known_codes: frozenset[str],
) -> MergeEnvironment:
    is_wk = lambda u: ns_to_code.get(_namespace_of(str(u))) in well_known_codes  # noqa: E731

    seed_al = alignment_pool.pop()
    seed1 = URIRef(seed_al.entity1)
    seed2 = URIRef(seed_al.entity2)

    log.info(
        "env #%d  seed: %s (onto1) ↔ %s (onto2)  measure=%.3f",
        env_idx, local_name(seed_al.entity1), local_name(seed_al.entity2), seed_al.measure,
    )

    sub1, sub2 = Graph(), Graph()
    seeds1: set[URIRef] = {seed1}
    seeds2: set[URIRef] = {seed2}
    border_set1: set[URIRef] = set()
    border_set2: set[URIRef] = set()
    env_alignments: list[Alignment] = [seed_al]

    # Queue of (node, side) pairs whose direct triples need to be moved into the env.
    seed_queue: deque[tuple[URIRef, int]] = deque([(seed1, 1), (seed2, 2)])

    while seed_queue:
        node, side = seed_queue.popleft()
        source = source_1 if side == 1 else source_2
        sub = sub1 if side == 1 else sub2
        seeds = seeds1 if side == 1 else seeds2
        other_seeds = seeds2 if side == 1 else seeds1
        other_side = 2 if side == 1 else 1
        other_source = source_2 if side == 1 else source_1
        other_sub = sub2 if side == 1 else sub1

        triples = move_entity_triples(node, source, sub)

        for s, _, o in triples:
            for neighbor in (s, o):
                if not isinstance(neighbor, URIRef):
                    continue
                if neighbor in seeds or neighbor in other_seeds:
                    continue
                if is_wk(neighbor):
                    border_set1.add(neighbor) if side == 1 else border_set2.add(neighbor)
                    continue
                if neighbor in global_frozen:
                    border_set1.add(neighbor) if side == 1 else border_set2.add(neighbor)
                    log.info(
                        "  env #%d  %s (onto%d) frozen — keeping as border",
                        env_idx, local_name(str(neighbor)), side,
                    )
                    continue

                al = (
                    alignment_pool.pop_by_entity1(str(neighbor)) if side == 1
                    else alignment_pool.pop_by_entity2(str(neighbor))
                )
                if al is not None:
                    partner = URIRef(al.entity2 if side == 1 else al.entity1)
                    seeds.add(neighbor)
                    other_seeds.add(partner)
                    seed_queue.append((neighbor, side))
                    seed_queue.append((partner, other_side))
                    env_alignments.append(al)
                    log.info(
                        "  env #%d  pulled in aligned pair: %s ↔ %s  measure=%.3f",
                        env_idx, local_name(str(neighbor)), local_name(str(partner)), al.measure,
                    )
                else:
                    border_set1.add(neighbor) if side == 1 else border_set2.add(neighbor)

    # Copy (not move) triples of non-well-known border nodes from source into border graphs.
    border1_graph, border2_graph = Graph(), Graph()
    for node in border_set1:
        if not is_wk(node):
            for triple in source_1.triples((node, None, None)):
                border1_graph.add(triple)
    for node in border_set2:
        if not is_wk(node):
            for triple in source_2.triples((node, None, None)):
                border2_graph.add(triple)

    log.info(
        "env #%d  done  |  onto1: %d triples  onto2: %d triples"
        "  |  alignments: %d  |  border1: %d  border2: %d",
        env_idx, len(sub1), len(sub2), len(env_alignments),
        len(border_set1), len(border_set2),
    )

    return MergeEnvironment(
        onto_1=sub1,
        onto_2=sub2,
        alignments=env_alignments,
        border1=deque(border_set1),
        border2=deque(border_set2),
        border1_graph=border1_graph,
        border2_graph=border2_graph,
        ns_to_code=ns_to_code,
        code_to_ns=code_to_ns,
        max_chars=config.max_chars,
    )


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

class ExtractEnvironmentsModule:
    def __init__(self, config: MergeEnvironmentConfig) -> None:
        self.config = config

    def extract(
        self,
        onto_1: Graph,
        onto_2: Graph,
        alignments: list[Alignment],
        uri_to_code: dict[str, str],
        code_to_ns: dict[str, str],
        ns_to_code: dict[str, str],
        well_known_codes: frozenset[str],
    ) -> tuple[list[MergeEnvironment], Graph, Graph]:
        """Extract merge environments from two ontologies.

        Returns:
            (environments, leftover_1, leftover_2) — leftover graphs contain triples
            that had no alignment and were never absorbed into any environment.
        """
        source_1 = Graph()
        source_2 = Graph()
        for triple in onto_1:
            source_1.add(triple)
        for triple in onto_2:
            source_2.add(triple)

        alignment_pool = _AlignmentPool(alignments)
        environments: list[MergeEnvironment] = []
        global_frozen: set[URIRef] = set()

        log.info(
            "Starting extraction: %d alignment pairs  (max env size: %d chars)",
            len(alignments), self.config.max_chars,
        )

        idx = 0
        while not alignment_pool.is_empty():
            env = _build_merge_environment(
                source_1, source_2, alignment_pool, self.config, idx, global_frozen,
                code_to_ns, ns_to_code, well_known_codes,
            )
            environments.append(env)

            for node in (*env.border1, *env.border2):
                if not alignment_pool.contains(str(node)):
                    global_frozen.add(node)

            idx += 1

        log.info(
            "Extraction done: %d environments  |  %d nodes frozen"
            "  |  onto1=%d triples  onto2=%d triples remaining (no alignment → pass-through)",
            len(environments), len(global_frozen), len(source_1), len(source_2),
        )
        return environments, source_1, source_2
