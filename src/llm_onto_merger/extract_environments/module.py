import bisect
import random
from collections import deque

from rdflib import Graph, URIRef

from ..alignment.alignment import Alignment
from ..logger import get_logger
from ..ontology import local_name, move_entity_triples
from .merge_environment import (
    MergeEnvironment,
    MergeEnvironmentConfig,
    _CHARS_PER_BORDER_NODE,
    _CHARS_PER_TRIPLE_TERM,
)

log = get_logger(__name__)

# Namespaces whose nodes are infrastructure/vocabulary, not domain entities.
# They may appear as border references but must never be pulled into env interior.
_WELL_KNOWN_NS: tuple[str, ...] = (
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2001/XMLSchema#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2003/11/swrl#",
    "http://www.w3.org/2003/11/swrlb#",
    "http://www.owl-ontologies.com/2005/08/07/xsp.owl#",
    "http://protege.stanford.edu/plugins/owl/protege#",
)


def _is_well_known(uri: URIRef) -> bool:
    s = str(uri)
    return s.startswith(_WELL_KNOWN_NS)


# ---------------------------------------------------------------------------
# Pre-rename
# ---------------------------------------------------------------------------

def _pre_rename_onto2(
    onto_2: Graph,
    alignments: list[Alignment],
) -> tuple[Graph, list[Alignment]]:
    """REQ: before extraction, rename every entity2 URI → entity1 URI inside onto2
    for '=' alignments. Non-'=' alignments (e.g. subClassOf) are left untouched.
    Also updates the alignment objects so pool lookups stay consistent.
    """
    # REQ: only '=' relation triggers renaming
    uri_map: dict[str, str] = {
        al.entity2: al.entity1
        for al in alignments
        if al.relation == "=" and al.entity2 != al.entity1
    }
    if not uri_map:
        return onto_2, alignments

    log.info(
        "Pre-renaming %d entity2 URIs in onto2 (= alignments only)", len(uri_map)
    )

    # Rebuild onto2 with substituted URIs
    renamed: Graph = Graph()
    for s, p, o in onto_2:
        new_s = URIRef(uri_map[str(s)]) if isinstance(s, URIRef) and str(s) in uri_map else s
        new_o = URIRef(uri_map[str(o)]) if isinstance(o, URIRef) and str(o) in uri_map else o
        renamed.add((new_s, p, new_o))

    # REQ: update alignment entity2 so the pool seed uses the new URI
    updated: list[Alignment] = [
        al.model_copy(update={"entity2": uri_map[al.entity2]})
        if al.relation == "=" and al.entity2 in uri_map
        else al
        for al in alignments
    ]

    return renamed, updated


# ---------------------------------------------------------------------------
# Alignment pool
# ---------------------------------------------------------------------------

class _AlignmentPool:
    """Sorted pool of alignment pairs. pop() always yields the highest-measure pair."""

    def __init__(self, alignments: list[Alignment]) -> None:
        # sorted ascending — pop() from the end gives highest measure in O(1)
        self._sorted: list[Alignment] = sorted(alignments, key=lambda a: a.measure)
        self._by_entity1: dict[str, Alignment] = {a.entity1: a for a in self._sorted}
        self._by_entity2: dict[str, Alignment] = {a.entity2: a for a in self._sorted}

    def pop(self) -> Alignment:
        al = self._sorted.pop()
        self._by_entity1.pop(al.entity1, None)
        self._by_entity2.pop(al.entity2, None)
        return al

    # REQ: pop_by_entity1/2 used when BFS finds an alignment target in the border
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

    def push(self, al: Alignment) -> None:
        """Re-insert an alignment — used when a paired expansion is rejected."""
        keys = [a.measure for a in self._sorted]
        idx = bisect.bisect_left(keys, al.measure)
        self._sorted.insert(idx, al)
        self._by_entity1[al.entity1] = al
        self._by_entity2[al.entity2] = al

    def contains(self, uri: str) -> bool:
        return uri in self._by_entity1 or uri in self._by_entity2

    def is_empty(self) -> bool:
        return not self._sorted


# ---------------------------------------------------------------------------
# Size helpers
# ---------------------------------------------------------------------------

def _new_border_candidates(triples: list[tuple], seen: set[URIRef]) -> list[URIRef]:
    """Extract unseen URIRef nodes from subject and object positions, shuffled."""
    candidates = {
        node
        for (s, _, o) in triples
        for node in (s, o)
        if isinstance(node, URIRef) and node not in seen
    }
    result = list(candidates)
    random.shuffle(result)
    return result


def _estimate_delta(entity: URIRef, source: Graph, seen: set[URIRef]) -> int:
    """REQ: estimate the chars increase from expanding entity, WITHOUT moving triples.

    Mirrors the chars_count formula in MergeEnvironment:
        triples * 3 * AVG_WORD  +  new_border_nodes * AVG_WORD
    """
    triples = (
        list(source.triples((entity, None, None)))
        + list(source.triples((None, None, entity)))
    )
    new_border: set[URIRef] = {
        node
        for s, _, o in triples
        for node in (s, o)
        if isinstance(node, URIRef) and node not in seen
    }
    return len(triples) * 3 * _CHARS_PER_TRIPLE_TERM + len(new_border) * _CHARS_PER_BORDER_NODE


def _current_size(
    sub1: Graph,
    sub2: Graph,
    border1: set[URIRef],
    border2: set[URIRef],
    n_alignments: int,
) -> int:
    return (
        (len(sub1) + len(sub2)) * 3 * _CHARS_PER_TRIPLE_TERM
        + (len(border1) + len(border2)) * _CHARS_PER_BORDER_NODE
        + n_alignments * 2 * _CHARS_PER_TRIPLE_TERM
    )


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
) -> MergeEnvironment:
    # REQ: seed from the most relevant (highest-measure) alignment pair
    seed_al = alignment_pool.pop()
    seed1 = URIRef(seed_al.entity1)
    seed2 = URIRef(seed_al.entity2)

    log.info(
        "env #%d  seed: %s (onto1) ↔ %s (onto2)  measure=%.3f",
        env_idx, local_name(seed_al.entity1), local_name(seed_al.entity2), seed_al.measure,
    )

    sub1, sub2 = Graph(), Graph()
    seen1: set[URIRef] = {seed1}
    seen2: set[URIRef] = {seed2}
    border_set1: set[URIRef] = set()
    border_set2: set[URIRef] = set()
    env_alignments: list[Alignment] = [seed_al]

    # REQ: move seed triples into the env; their neighbors become the initial border
    seed_triples1 = move_entity_triples(seed1, source_1, sub1)
    seed_triples2 = move_entity_triples(seed2, source_2, sub2)

    init1 = _new_border_candidates(seed_triples1, seen1)
    init2 = _new_border_candidates(seed_triples2, seen2)
    seen1.update(init1)
    seen2.update(init2)

    expand_queue1: deque[URIRef] = deque(init1)
    expand_queue2: deque[URIRef] = deque(init2)

    stopped = False

    def _process(
        candidate: URIRef,
        source: Graph, sub: Graph, seen: set[URIRef],
        border_set: set[URIRef], queue: deque[URIRef],
        other_source: Graph, other_sub: Graph, other_seen: set[URIRef],
        other_queue: deque[URIRef],
        side: int,
    ) -> bool:
        """Process one border candidate. Returns True if building should stop."""
        nonlocal env_alignments

        # Well-known namespace nodes (owl, rdf, rdfs, xsd, swrl, …) are vocabulary,
        # not domain entities — keep as border reference, never expand into interior.
        if _is_well_known(candidate):
            border_set.add(candidate)
            return False

        # REQ: global_frozen node → border only, never expand
        if candidate in global_frozen:
            border_set.add(candidate)
            log.info(
                "  env #%d  %s (onto%d) frozen — keeping as border",
                env_idx, local_name(str(candidate)), side,
            )
            return False

        # REQ: if node is in alignment pool → paired expansion required
        al = (
            alignment_pool.pop_by_entity1(str(candidate)) if side == 1
            else alignment_pool.pop_by_entity2(str(candidate))
        )

        if al is not None:
            partner = URIRef(al.entity2 if side == 1 else al.entity1)
            partner_in_seen = partner in other_seen

            # REQ: estimate size for BOTH candidate + partner BEFORE committing
            delta_c = _estimate_delta(candidate, source, seen)
            delta_p = 0 if partner_in_seen else _estimate_delta(partner, other_source, other_seen)
            alignment_delta = 2 * _CHARS_PER_TRIPLE_TERM  # one more Alignment entry

            cur = _current_size(sub1, sub2, border_set1, border_set2, len(env_alignments))

            # REQ: if paired expansion exceeds limit → re-insert alignment, add to border, stop
            if cur + delta_c + delta_p + alignment_delta > config.max_chars:
                log.info(
                    "  env #%d  size limit — rejecting paired expansion %s ↔ %s, stopping",
                    env_idx, local_name(str(candidate)), local_name(str(partner)),
                )
                alignment_pool.push(al)  # REQ: re-insert so it can seed its own env later
                border_set.add(candidate)
                return True  # stop building

            # REQ: commit — expand candidate
            triples_c = move_entity_triples(candidate, source, sub)
            new_cands_c = _new_border_candidates(triples_c, seen)
            seen.update(new_cands_c)
            queue.extend(new_cands_c)

            # REQ: commit — expand partner (if not already in this env)
            if not partner_in_seen:
                other_seen.add(partner)
                triples_p = move_entity_triples(partner, other_source, other_sub)
                new_cands_p = _new_border_candidates(triples_p, other_seen)
                other_seen.update(new_cands_p)
                other_queue.extend(new_cands_p)

            # REQ: pop from pool was done above; record the alignment
            env_alignments.append(al)
            log.info(
                "  env #%d  pulled in aligned pair: %s ↔ %s  measure=%.3f",
                env_idx, local_name(str(candidate)), local_name(str(partner)), al.measure,
            )
            return False

        # Normal node — check size, then expand
        delta = _estimate_delta(candidate, source, seen)

        # Edge case: no triples in source (absorbed by an earlier env via another path)
        if delta == 0:
            border_set.add(candidate)
            return False

        cur = _current_size(sub1, sub2, border_set1, border_set2, len(env_alignments))

        # REQ: if expansion would exceed limit → reject this node, stop building
        if cur + delta > config.max_chars:
            log.info(
                "  env #%d  size limit at %s (onto%d) — stopping",
                env_idx, local_name(str(candidate)), side,
            )
            border_set.add(candidate)
            return True  # stop building

        # REQ: commit expansion
        triples = move_entity_triples(candidate, source, sub)
        new_cands = _new_border_candidates(triples, seen)
        seen.update(new_cands)
        queue.extend(new_cands)
        return False

    while (expand_queue1 or expand_queue2) and not stopped:
        if expand_queue1 and not stopped:
            stopped = _process(
                expand_queue1.popleft(),
                source_1, sub1, seen1, border_set1, expand_queue1,
                source_2, sub2, seen2, expand_queue2,
                side=1,
            )
        if expand_queue2 and not stopped:
            stopped = _process(
                expand_queue2.popleft(),
                source_2, sub2, seen2, border_set2, expand_queue2,
                source_1, sub1, seen1, expand_queue1,
                side=2,
            )

    # REQ: nodes left in queues after stop/natural end → border (not expanded)
    border_set1.update(expand_queue1)
    border_set2.update(expand_queue2)

    log.info(
        "env #%d  done  |  onto1: %d triples  onto2: %d triples"
        "  |  alignments: %d  |  border1: %d  border2: %d  |  stopped early: %s",
        env_idx, len(sub1), len(sub2), len(env_alignments),
        len(border_set1), len(border_set2), "YES" if stopped else "no",
    )

    return MergeEnvironment(
        onto_1=sub1,
        onto_2=sub2,
        alignments=env_alignments,
        border1=deque(border_set1),
        border2=deque(border_set2),
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
    ) -> tuple[list[MergeEnvironment], Graph, Graph]:
        """Extract merge environments from two ontologies.

        Returns:
            (environments, leftover_1, leftover_2) — leftover graphs contain triples
            that had no alignment and were never absorbed into any environment.
        """
        # REQ: pre-rename entity2 → entity1 in onto2 for '=' alignments
        renamed_onto_2, alignments = _pre_rename_onto2(onto_2, alignments)

        source_1 = Graph()
        source_2 = Graph()
        for triple in onto_1:
            source_1.add(triple)
        for triple in renamed_onto_2:
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
            )
            environments.append(env)

            # REQ: freeze border nodes of the completed env so they can't become
            # interior of any future env.
            # REQ exception: nodes still in alignment_pool are NOT frozen — they will
            # become seeds of their own environment and their neighbors can expand normally.
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
