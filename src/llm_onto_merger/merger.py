import asyncio
from pathlib import Path

from llm_onto_merger.alignment.alignment import AlignmentModule
from llm_onto_merger.debug import (
    save_diff_debug,
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
from llm_onto_merger.merge_environments.module import MergeEnvironmentsModule
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

        onto_1 = create_ontology(Path(args.base_path))
        onto_2 = create_ontology(Path(args.candidate_path))

        alignments = await alignment_module.create_alignment(
            args.base_path, args.candidate_path
        )

        applied_onto = apply_alignments(onto_1, onto_2, alignments)
        save_ontology(applied_onto, out_dir, name="applied_alignments")
        log.info("Alignments applied: %d", len(alignments))

        uri_to_code, code_to_ns, ns_to_code, well_known_codes = build_namespace_codec(onto_1, onto_2)

        extractor = ExtractEnvironmentsModule(
            MergeEnvironmentConfig(max_chars=args.merge_env_max_chars)
        )
        merge_environments, onto_1_leftover, onto_2_leftover = extractor.extract(
            onto_1, onto_2, alignments,
            uri_to_code, code_to_ns, ns_to_code, well_known_codes,
        )

        total     = len(merge_environments)
        semaphore = asyncio.Semaphore(settings.parallel_llm_request_count)
        merger    = MergeEnvironmentsModule()

        log.info(
            "Merging %d environments | parallel_llm_requests: %d",
            total,
            settings.parallel_llm_request_count,
        )

        async def _merge_one(env, idx):
            async with semaphore:
                result = await merger.merge(env, idx=idx + 1, total=total)
                log.info("Merged environment %d/%d", idx + 1, total)
                return result

        merged_environments = list(
            await asyncio.gather(
                *[_merge_one(env, i) for i, env in enumerate(merge_environments)]
            )
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

        merged_onto = integrate_environments(
            merged_environments, onto_1_leftover, onto_2_leftover, code_to_ns
        )
        save_ontology(merged_onto, out_dir)
