from pydantic import BaseModel
from rdflib import OWL, Graph, URIRef

from llm_onto_merger.extract_environments.merge_environment import MergeEnvironment
from llm_onto_merger.logger import get_logger
from llm_onto_merger.ontology import DropReport, Entity, entities_to_graph, local_name

log = get_logger(__name__)


class MergedOntology(BaseModel):
    Merged_Ontology: list[Entity]
    Was_Alignment_Applied: bool


_MERGED_ONTOLOGY_SCHEMA = MergedOntology.model_json_schema()


def _local_keys(g: Graph) -> set[tuple[str, str, str]]:
    return {
        (local_name(str(s)), local_name(str(p)), local_name(str(o)))
        for s, p, o in g
        if isinstance(s, URIRef) and isinstance(o, URIRef)
    }


def _audit_merge(idx: int, env: MergeEnvironment, merged: Graph) -> None:
    """Per-env sanity checks. Emits warnings for suspicious merge outcomes."""
    input_graph = Graph()
    for t in env.onto_1:
        input_graph.add(t)
    for t in env.onto_2:
        input_graph.add(t)

    input_keys = _local_keys(input_graph)
    merged_keys = _local_keys(merged)
    added = merged_keys - input_keys
    deleted = input_keys - merged_keys
    kept = input_keys & merged_keys

    input_disjoint = sum(1 for _ in input_graph.triples((None, OWL.disjointWith, None)))
    merged_disjoint = sum(1 for _ in merged.triples((None, OWL.disjointWith, None)))

    log.info(
        "env %d audit | input=%d kept=%d added=%d deleted=%d | disjointWith %d→%d",
        idx,
        len(input_keys),
        len(kept),
        len(added),
        len(deleted),
        input_disjoint,
        merged_disjoint,
    )

    if len(merged) == 0:
        log.error("env %d: LLM returned EMPTY merged graph", idx)
    if len(added) == 0 and len(input_keys) > 0:
        log.warning(
            "env %d: LLM added 0 new triples (deleted %d) — possible dead merge",
            idx,
            len(deleted),
        )
    if len(input_keys) and len(kept) / len(input_keys) < 0.5:
        log.warning(
            "env %d: kept only %.1f%% of input triples — suspicious shrinkage",
            idx,
            100 * len(kept) / len(input_keys),
        )
    if input_disjoint and merged_disjoint > input_disjoint * 5:
        log.warning(
            "env %d: disjointWith count exploded %d → %d (>5x) — likely over-generation",
            idx,
            input_disjoint,
            merged_disjoint,
        )


class MergeEnvironmentsModule:
    def __init__(self, agent) -> None:
        self._agent = agent
        self._instruction_len = len(agent.default_options.get("instructions") or "")

    async def merge(
        self, merge_environment: MergeEnvironment, idx: int = 0, total: int = 0
    ) -> tuple[Graph, DropReport, bool]:
        request, code_to_uri = merge_environment.to_string()
        n_triples = len(merge_environment.onto_1) + len(merge_environment.onto_2)
        log.info(
            "Passing %d triples from merge environment %d/%d to agent",
            n_triples,
            idx,
            total,
        )
        log.info(
            "Sending merge request | instruction: %d chars | request: %d chars | total: %d chars",
            self._instruction_len,
            len(request),
            self._instruction_len + len(request),
        )
        response = await self._agent.run(
            request,
            options={"response_format": _MERGED_ONTOLOGY_SCHEMA},
        )
        merged = MergedOntology.model_validate(response.value)
        log.info("Received %d entities in merged ontology", len(merged.Merged_Ontology))
        if not merged.Was_Alignment_Applied:
            seed_label = (
                merge_environment.alignments[0].to_string()
                if merge_environment.alignments
                else "<unknown>"
            )
            log.info(
                "env %d: alignment NOT applied by LLM (seed: %s) — pair kept as separate entities",
                idx,
                seed_label,
            )
        merged_graph, drop_report = entities_to_graph(
            merged.Merged_Ontology, code_to_uri
        )
        _audit_merge(idx, merge_environment, merged_graph)
        return merged_graph, drop_report, merged.Was_Alignment_Applied
