import asyncio
import json
from pathlib import Path

from llm_onto_merger.alignment.alignment import AlignmentModule
from llm_onto_merger.debug import (
    save_diff_debug,
    save_insights_debug,
    save_post_merge_debug,
    save_pre_merge_debug,
)
from llm_onto_merger.extract_environments import (
    ExtractEnvironmentsModule,
    MergeEnvironmentConfig,
    build_namespace_codec,
)
from llm_onto_merger.integrate_environments import integrate_environments
from llm_onto_merger.load_arguments import LoadedArguments
from llm_onto_merger.logger import get_logger
from llm_onto_merger.merge_environments.agent import build_merge_agent
from llm_onto_merger.merge_environments.module import MergeEnvironmentsModule
from llm_onto_merger.alignment.alignment import Alignment
from llm_onto_merger.ontology import apply_alignments, create_ontology, save_ontology
from llm_onto_merger.settings import settings

log = get_logger(__name__)


class LLMOntologyMerger:
    @staticmethod
    async def merge(
        args: LoadedArguments,
        alignment_module: AlignmentModule,
    ) -> None:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        onto_1, renames_1 = create_ontology(Path(args.base_path))
        onto_2, renames_2 = create_ontology(Path(args.candidate_path))

        alignments = await alignment_module.create_alignment(
            args.base_path, args.candidate_path
        )

        all_renames = {**renames_1, **renames_2}
        if all_renames:
            alignments = [
                Alignment(
                    entity1=all_renames.get(a.entity1, a.entity1),
                    entity2=all_renames.get(a.entity2, a.entity2),
                    measure=a.measure,
                    relation=a.relation,
                )
                for a in alignments
            ]
            log.info(
                "Alignment URIs updated after relabeling: %d renames available",
                len(all_renames),
            )

        applied_onto = apply_alignments(onto_1, onto_2, alignments)
        save_ontology(applied_onto, out_dir, name="applied_alignments")
        log.info("Alignments applied: %d", len(alignments))

        _, code_to_ns, ns_to_code, well_known_codes = build_namespace_codec(onto_1, onto_2)

        extractor = ExtractEnvironmentsModule(
            MergeEnvironmentConfig(max_chars=args.merge_env_max_chars)
        )
        merge_environments, onto_1_leftover, onto_2_leftover = extractor.extract(
            onto_1, onto_2, alignments,
            code_to_ns, ns_to_code, well_known_codes,
        )
        extractor.expand_extracted(
            merge_environments, onto_1_leftover, onto_2_leftover,
            ns_to_code, well_known_codes,
        )

        total     = len(merge_environments)
        semaphore = asyncio.Semaphore(settings.parallel_llm_request_count)
        merger    = MergeEnvironmentsModule(build_merge_agent(ns_to_code, code_to_ns))

        log.info(
            "Merging %d environments | parallel_llm_requests: %d",
            total,
            settings.parallel_llm_request_count,
        )

        async def _merge_single_env(env, idx):
            async with semaphore:
                result = await merger.merge(env, idx=idx + 1, total=total)
                log.info("Merged environment %d/%d", idx + 1, total)
                return result

        results = list(
            await asyncio.gather(
                *[_merge_single_env(env, i) for i, env in enumerate(merge_environments)]
            )
        )
        merged_environments = [graph for graph, _, _ in results]
        drop_reports = [report for _, report, _ in results]
        alignment_applied_flags = [applied for _, _, applied in results]

        applied_count = sum(alignment_applied_flags)
        total_alignments = len(alignment_applied_flags)
        log.info(
            "Alignment application summary: %d/%d applied by LLM (%d rejected)",
            applied_count,
            total_alignments,
            total_alignments - applied_count,
        )
        (out_dir / "alignment_stats.json").write_text(
            json.dumps(
                {
                    "total_alignments": total_alignments,
                    "applied_count": applied_count,
                    "per_env": alignment_applied_flags,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        if settings.debug:
            save_pre_merge_debug(
                merge_environments,
                onto_1_leftover,
                onto_2_leftover,
                out_dir,
                merged_graphs=merged_environments,
            )
            save_post_merge_debug(
                merged_environments,
                onto_1_leftover,
                onto_2_leftover,
                out_dir,
                merge_environments=merge_environments,
            )
            save_diff_debug(
                merge_environments,
                merged_environments,
                out_dir,
            )
            save_insights_debug(
                merge_environments, merged_environments, drop_reports,
                alignment_applied_flags, out_dir,
            )

        merged_onto = integrate_environments(
            merged_environments, onto_1_leftover, onto_2_leftover, code_to_ns
        )
        save_ontology(merged_onto, out_dir)
