from collections import deque
from typing import Callable

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
# Expansion helper
# ---------------------------------------------------------------------------

def _expand_one(
    border: deque[URIRef],
    border_queued: set[URIRef],
    border_graph: Graph,
    interior: Graph,
    source: Graph,
    global_frozen: set[URIRef],
    is_wk: Callable[[URIRef], bool],
) -> bool:
    """Pop the next expandable node from *border*, move its triples into *interior*.

    A node is not expandable if it is in global_frozen (already interior
    somewhere) or is well-known.  Such nodes are silently discarded from the
    deque — frozen is monotone, so they will never become expandable again.

    New neighbours discovered via the moved triples are appended to *border*
    (if not already queued / frozen / well-known) and their source triples are
    copied into *border_graph* for context.

    Returns True if a node was expanded, False if the border is exhausted.
    """
    while border:
        node = border.popleft()
        if node in global_frozen or is_wk(node):
            continue

        triples = move_entity_triples(node, source, interior)
        global_frozen.add(node)

        # The node has moved to interior — remove its outgoing triples from
        # border_graph (they are now redundant; incoming edges from other border
        # nodes are left untouched because they still provide useful context).
        for triple in list(border_graph.triples((node, None, None))):
            border_graph.remove(triple)

        # Discover new neighbours and queue them as border candidates.
        for s, _, o in triples:
            for neighbour in (s, o):
                if (
                    isinstance(neighbour, URIRef)
                    and neighbour not in global_frozen
                    and not is_wk(neighbour)
                    and neighbour not in border_queued
                ):
                    border.append(neighbour)
                    border_queued.add(neighbour)
                    for triple in source.triples((neighbour, None, None)):
                        border_graph.add(triple)

        return True
    return False


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

    def expand_extracted(
        self,
        environments: list[MergeEnvironment],
        source_1: Graph,
        source_2: Graph,
        ns_to_code: dict[str, str],
        well_known_codes: frozenset[str],
    ) -> None:
        """Phase 2: round-robin border expansion into environment interiors.

        For each active environment, one border node from onto_1 side and one
        from onto_2 side are expanded per round: their triples are moved from
        source into the environment interior and their direct neighbours are
        queued as new border candidates.

        Environments are removed from the rotation when they exceed max_chars
        or have no more expandable border nodes.  The loop terminates when no
        environment can expand further.

        global_frozen tracks every node that has entered any environment
        interior — such nodes can no longer be promoted to an interior
        elsewhere (they may still appear in border_graph as context).

        Modifies *environments*, *source_1*, and *source_2* in-place.
        """
        def is_wk(u: URIRef) -> bool:
            return ns_to_code.get(_namespace_of(str(u))) in well_known_codes

        # Seed nodes (already in interiors after phase 1) start globally frozen.
        global_frozen: set[URIRef] = {
            s
            for env in environments
            for graph in (env.onto_1, env.onto_2)
            for s, _, _ in graph
            if isinstance(s, URIRef)
        }

        active = list(range(len(environments)))
        log.info(
            "Starting border expansion: %d environments  |  global_frozen=%d nodes",
            len(active), len(global_frozen),
        )

        round_num = 0
        while active:
            round_num += 1
            next_active: list[int] = []
            any_expanded = False

            for idx in active:
                env = environments[idx]

                did_1 = _expand_one(
                    env.border1, env._border1_queued, env.border1_graph,
                    env.onto_1, source_1, global_frozen, is_wk,
                )
                did_2 = _expand_one(
                    env.border2, env._border2_queued, env.border2_graph,
                    env.onto_2, source_2, global_frozen, is_wk,
                )

                if did_1 or did_2:
                    any_expanded = True

                still_has_border = bool(env.border1) or bool(env.border2)
                within_limit = env.interior_char_estimate() < self.config.max_chars

                if still_has_border and within_limit:
                    next_active.append(idx)
                else:
                    log.info(
                        "env #%d  leaving rotation after round %d"
                        "  |  has_border=%s  within_limit=%s",
                        idx, round_num, still_has_border, within_limit,
                    )

            active = next_active

            if not any_expanded:
                # Full round produced nothing — all remaining borders are exhausted or frozen.
                break

        log.info(
            "Expansion done: %d rounds  |  source_1=%d triples  source_2=%d triples remaining",
            round_num, len(source_1), len(source_2),
        )
