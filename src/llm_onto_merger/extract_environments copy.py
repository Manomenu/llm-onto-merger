from collections import deque
from typing import Any

import owlready2
from pydantic import BaseModel, ConfigDict

from .alignment.alignment import Alignment
from .logger import get_logger

log = get_logger(__name__)

_KIND_CYCLE = ("axiom", "individual", "class")


class MergeEnvironment(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    onto1_entities: list[Any]
    onto2_entities: list[Any]
    alignments: list[Alignment]

    def to_string(self) -> str:
        from .ontology import stringify_entities

        align_lines = [
            f"  {a.entity1} {a.relation} {a.entity2} [{a.measure:.4f}]"
            for a in self.alignments
        ]
        return "\n".join([
            "=== Ontology 1 ===",
            stringify_entities(self.onto1_entities),
            "=== Ontology 2 ===",
            stringify_entities(self.onto2_entities),
            "=== Alignments ===",
            *align_lines,
        ])


def _entity_key(entity: Any) -> str:
    iri = getattr(entity, "iri", None)
    return iri if iri else str(entity)


def _kind(entity: Any) -> str:
    if isinstance(entity, owlready2.ThingClass):
        return "class"
    if isinstance(entity, owlready2.Thing):
        return "individual"
    return "axiom"


def _neighbors(entity: Any, onto: owlready2.Ontology) -> list[Any]:
    result: list[Any] = []
    if isinstance(entity, owlready2.ThingClass):
        result.extend(entity.is_a)
        result.extend(entity.subclasses())
        result.extend(entity.instances())
        result.extend(entity.equivalent_to)
    elif isinstance(entity, owlready2.Thing):
        result.extend(entity.is_a)
        for prop in onto.object_properties():
            result.extend(prop[entity])
    return result


def _build_entity_map(onto: owlready2.Ontology) -> dict[str, Any]:
    m: dict[str, Any] = {}
    for cls in onto.classes():
        m[cls.iri] = cls
    for ind in onto.individuals():
        m[ind.iri] = ind
    return m


def _enqueue_neighbors(
    entity: Any,
    onto: owlready2.Ontology,
    queues: dict[str, deque],
    seen: set[str],
) -> None:
    for neighbor in _neighbors(entity, onto):
        key = _entity_key(neighbor)
        if key not in seen:
            seen.add(key)
            queues[_kind(neighbor)].append(neighbor)


def _build_environment(
    seed1: Any,
    seed2: Any,
    seed_alignment: Alignment,
    onto1: owlready2.Ontology,
    onto2: owlready2.Ontology,
    alignment_map1: dict[str, Alignment],
    alignment_map2: dict[str, Alignment],
    entity_map1: dict[str, Any],
    entity_map2: dict[str, Any],
    used1: set[str],
    used2: set[str],
    max_chars: int,
) -> MergeEnvironment:
    entities1: list[Any] = [seed1]
    entities2: list[Any] = [seed2]
    env_alignments: list[Alignment] = [seed_alignment]

    # seen tracks what's already queued or added, seeded with globally-used entities
    # so we never re-queue them
    seen1: set[str] = set(used1) | {_entity_key(seed1)}
    seen2: set[str] = set(used2) | {_entity_key(seed2)}

    queues1: dict[str, deque] = {k: deque() for k in _KIND_CYCLE}
    queues2: dict[str, deque] = {k: deque() for k in _KIND_CYCLE}
    _enqueue_neighbors(seed1, onto1, queues1, seen1)
    _enqueue_neighbors(seed2, onto2, queues2, seen2)

    def size() -> int:
        return len(
            MergeEnvironment(
                onto1_entities=entities1,
                onto2_entities=entities2,
                alignments=env_alignments,
            ).to_string()
        )

    def try_add1(candidate: Any) -> bool:
        if size() >= max_chars:
            return False
        entities1.append(candidate)
        _enqueue_neighbors(candidate, onto1, queues1, seen1)
        # if this entity is part of an alignment, pull its partner into onto2
        key = _entity_key(candidate)
        if key in alignment_map1:
            al = alignment_map1[key]
            partner_iri = al.entity2
            if partner_iri not in seen2 and partner_iri in entity_map2:
                partner = entity_map2[partner_iri]
                seen2.add(partner_iri)
                entities2.append(partner)
                _enqueue_neighbors(partner, onto2, queues2, seen2)
                if al not in env_alignments:
                    env_alignments.append(al)
        return True

    def try_add2(candidate: Any) -> bool:
        if size() >= max_chars:
            return False
        entities2.append(candidate)
        _enqueue_neighbors(candidate, onto2, queues2, seen2)
        key = _entity_key(candidate)
        if key in alignment_map2:
            al = alignment_map2[key]
            partner_iri = al.entity1
            if partner_iri not in seen1 and partner_iri in entity_map1:
                partner = entity_map1[partner_iri]
                seen1.add(partner_iri)
                entities1.append(partner)
                _enqueue_neighbors(partner, onto1, queues1, seen1)
                if al not in env_alignments:
                    env_alignments.append(al)
        return True

    def done() -> MergeEnvironment:
        return MergeEnvironment(
            onto1_entities=entities1,
            onto2_entities=entities2,
            alignments=env_alignments,
        )

    while True:
        made_progress = False
        for kind in _KIND_CYCLE:
            for queue, try_add in (
                (queues1[kind], try_add1),
                (queues2[kind], try_add2),
            ):
                while queue:
                    candidate = queue.popleft()
                    if not try_add(candidate):
                        return done()  # size limit hit
                    made_progress = True
                    break  # one entity per (kind, ontology) per cycle
        if not made_progress:
            break

    return done()


def extract_environments(
    onto1: owlready2.Ontology,
    onto2: owlready2.Ontology,
    alignments: list[Alignment],
    max_chars: int = 10_000,
) -> list[MergeEnvironment]:
    sorted_alignments = sorted(alignments, key=lambda a: a.measure, reverse=True)
    entity_map1 = _build_entity_map(onto1)
    entity_map2 = _build_entity_map(onto2)
    alignment_map1: dict[str, Alignment] = {a.entity1: a for a in sorted_alignments}
    alignment_map2: dict[str, Alignment] = {a.entity2: a for a in sorted_alignments}

    used1: set[str] = set()
    used2: set[str] = set()
    environments: list[MergeEnvironment] = []

    for alignment in sorted_alignments:
        if alignment.entity1 in used1 or alignment.entity2 in used2:
            continue

        seed1 = entity_map1.get(alignment.entity1)
        seed2 = entity_map2.get(alignment.entity2)
        if seed1 is None or seed2 is None:
            log.warning(
                "Entity not found for alignment: %s <-> %s",
                alignment.entity1,
                alignment.entity2,
            )
            continue

        env = _build_environment(
            seed1, seed2, alignment,
            onto1, onto2,
            alignment_map1, alignment_map2,
            entity_map1, entity_map2,
            used1, used2,
            max_chars,
        )

        for e in env.onto1_entities:
            if hasattr(e, "iri"):
                used1.add(e.iri)
        for e in env.onto2_entities:
            if hasattr(e, "iri"):
                used2.add(e.iri)

        log.info(
            "MergeEnvironment built: %d onto1 entities, %d onto2 entities, "
            "%d alignments, ~%d chars",
            len(env.onto1_entities),
            len(env.onto2_entities),
            len(env.alignments),
            len(env.to_string()),
        )
        environments.append(env)

    return environments
