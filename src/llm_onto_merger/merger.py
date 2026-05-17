import asyncio
from pathlib import Path

from rdflib import Graph, URIRef

from llm_onto_merger.alignment.alignment import Alignment, AlignmentModule
from llm_onto_merger.debug import (
    save_diff_debug,
    save_post_merge_debug,
    save_pre_merge_debug,
)
from llm_onto_merger.extract_environments import (
    ExtractEnvironmentsModule,
    MergeEnvironmentConfig,
)
from llm_onto_merger.integrate_environments import integrate_environments
from llm_onto_merger.load_arguments import LoadedArguments
from llm_onto_merger.logger import get_logger
from llm_onto_merger.merge_environments.module import MergeEnvironmentsModule
from llm_onto_merger.ontology import create_ontology, save_ontology
from llm_onto_merger.settings import settings

log = get_logger(__name__)


def _build_applied_alignments_ontology(
    onto_1: Graph,
    onto_2: Graph,
    alignments: list[Alignment],
) -> Graph:
    """Naive alignment-based merge: union of both ontologies with each aligned
    entity2 collapsed into entity1 (all its triples re-pointed to entity1's URI).
    Useful as a baseline to compare against the LLM-merged ontology.
    """
    result = Graph()
    for t in onto_1:
        result.add(t)
    for t in onto_2:
        result.add(t)

    for al in alignments:
        e1 = URIRef(al.entity1)
        e2 = URIRef(al.entity2)
        if e1 == e2:
            continue
        for _, p, o in list(result.triples((e2, None, None))):
            result.remove((e2, p, o))
            result.add((e1, p, o))
        for s, p, _ in list(result.triples((None, None, e2))):
            result.remove((s, p, e2))
            result.add((s, p, e1))

    return result


class LLMOntologyMerger:
    @staticmethod
    async def merge(
        args: LoadedArguments,
        alignment_module: AlignmentModule,
    ) -> None:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        onto_1 = create_ontology(Path(args.base_path))
        onto_2 = create_ontology(Path(args.candidate_path))

        alignments = await alignment_module.create_alignment(
            args.base_path, args.candidate_path
        )

        applied_onto = _build_applied_alignments_ontology(onto_1, onto_2, alignments)
        save_ontology(applied_onto, out_dir, name="applied_alignments")
        log.info("Alignments applied: %d", len(alignments))

        extractor = ExtractEnvironmentsModule(
            MergeEnvironmentConfig(max_chars=args.merge_env_max_chars)
        )
        alignment_envs, leftover_envs = extractor.extract(onto_1, onto_2, alignments)

        all_envs   = alignment_envs + leftover_envs
        total      = len(all_envs)
        n_align    = len(alignment_envs)
        semaphore  = asyncio.Semaphore(settings.parallel_llm_request_count)
        merger     = MergeEnvironmentsModule()

        log.info(
            "Merging %d environments (%d alignment + %d leftover) | parallel_llm_requests: %d",
            total, n_align, len(leftover_envs), settings.parallel_llm_request_count,
        )

        async def _merge_one(env, idx):
            async with semaphore:
                result = await merger.merge(env, idx=idx + 1, total=total)
                log.info("Merged environment %d/%d", idx + 1, total)
                return result

        all_merged = list(await asyncio.gather(
            *[_merge_one(env, i) for i, env in enumerate(all_envs)]
        ))

        merged_alignment = all_merged[:n_align]
        merged_leftover  = all_merged[n_align:]

        if settings.debug:
            save_pre_merge_debug(
                alignment_envs,
                leftover_envs,
                out_dir,
                original_alignments=alignments,
                merged_graphs=merged_alignment,
                leftover_merged_graphs=merged_leftover,
            )
            save_post_merge_debug(
                merged_alignment,
                merged_leftover,
                out_dir,
                merge_environments=alignment_envs,
                leftover_environments=leftover_envs,
            )
            save_diff_debug(
                alignment_envs,
                merged_alignment,
                out_dir,
                leftover_environments=leftover_envs,
                leftover_merged_graphs=merged_leftover,
            )

        merged_onto = integrate_environments(all_merged)
        save_ontology(merged_onto, out_dir)
