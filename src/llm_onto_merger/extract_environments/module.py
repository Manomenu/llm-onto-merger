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

    def pop(self) -> Alignment:
        return self._sorted.pop()

    def is_empty(self) -> bool:
        return not self._sorted


# ---------------------------------------------------------------------------
# Environment builder
# ---------------------------------------------------------------------------

def _build_merge_environment(
    source_1: Graph,
    source_2: Graph,
    seed_al: Alignment,
    config: MergeEnvironmentConfig,
    env_idx: int,
    ns_to_code: dict[str, str],
    code_to_ns: dict[str, str],
    well_known_codes: frozenset[str],
) -> MergeEnvironment:
    is_wk = lambda u: ns_to_code.get(_namespace_of(str(u))) in well_known_codes  # noqa: E731

    seed1 = URIRef(seed_al.entity1)
    seed2 = URIRef(seed_al.entity2)

    log.info(
        "env #%d  seed: %s (onto1) ↔ %s (onto2)  measure=%.3f",
        env_idx, local_name(seed_al.entity1), local_name(seed_al.entity2), seed_al.measure,
    )

    sub1, sub2 = Graph(), Graph()
    seeds: set[URIRef] = {seed1, seed2}
    border_set1: set[URIRef] = set()
    border_set2: set[URIRef] = set()

    # Move direct triples of each seed into the environment sub-graph.
    for node, source, sub, border_set in (
        (seed1, source_1, sub1, border_set1),
        (seed2, source_2, sub2, border_set2),
    ):
        triples = move_entity_triples(node, source, sub)
        for s, _, o in triples:
            for neighbor in (s, o):
                if isinstance(neighbor, URIRef) and neighbor not in seeds and not is_wk(neighbor):
                    border_set.add(neighbor)

    # Copy (not move) triples of border nodes from source into border graphs.
    # Note: triples that connected a border node directly to a seed were already
    # moved by move_entity_triples above, so they will NOT appear here.
    border1_graph, border2_graph = Graph(), Graph()
    for node in border_set1:
        for triple in source_1.triples((node, None, None)):
            border1_graph.add(triple)
    for node in border_set2:
        for triple in source_2.triples((node, None, None)):
            border2_graph.add(triple)

    log.info(
        "env #%d  done  |  onto1: %d triples  onto2: %d triples"
        "  |  border1: %d  border2: %d",
        env_idx, len(sub1), len(sub2), len(border_set1), len(border_set2),
    )

    return MergeEnvironment(
        onto_1=sub1,
        onto_2=sub2,
        alignments=[seed_al],
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
        """Extract one MergeEnvironment per alignment pair.

        Each environment contains the direct triples of the two seed nodes plus
        their neighbourhood as border context (triples copied from source).
        Border nodes may appear in multiple environments — their triples are
        never consumed from source, only copied.

        Returns:
            (environments, leftover_1, leftover_2)
        """
        source_1 = Graph()
        source_2 = Graph()
        for triple in onto_1:
            source_1.add(triple)
        for triple in onto_2:
            source_2.add(triple)

        pool = _AlignmentPool(alignments)
        environments: list[MergeEnvironment] = []

        log.info(
            "Starting extraction: %d alignment pairs  (max border size: %d chars)",
            len(alignments), self.config.max_chars,
        )

        idx = 0
        while not pool.is_empty():
            env = _build_merge_environment(
                source_1, source_2, pool.pop(), self.config, idx,
                ns_to_code, code_to_ns, well_known_codes,
            )
            environments.append(env)
            idx += 1

        log.info(
            "Extraction done: %d environments"
            "  |  onto1=%d triples  onto2=%d triples remaining (no alignment → pass-through)",
            len(environments), len(source_1), len(source_2),
        )
        return environments, source_1, source_2
