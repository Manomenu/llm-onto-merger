import asyncio
from pathlib import Path

from llm_onto_merger.alignment.alignment import AlignmentModule
from llm_onto_merger.extract_environments import (
    ExtractEnvironmentsModule,
    MergeEnvironmentConfig,
)
from llm_onto_merger.integrate_environments import integrate_environments
from llm_onto_merger.load_arguments import LoadedArguments
from llm_onto_merger.debug import save_diff_debug, save_post_merge_debug, save_pre_merge_debug
from llm_onto_merger.logger import get_logger
from llm_onto_merger.merge_environments.module import MergeEnvironmentsModule
from llm_onto_merger.ontology import create_ontology, save_ontology
from llm_onto_merger.settings import settings

log = get_logger(__name__)


class LLMOntologyMerger:
    @staticmethod
    async def merge(
        args: LoadedArguments,
        alignment_module: AlignmentModule,
    ) -> None:
        onto_1 = create_ontology(Path(args.base_path))
        onto_2 = create_ontology(Path(args.candidate_path))

        alignments = await alignment_module.create_alignment(
            args.base_path, args.candidate_path
        )

        extractor = ExtractEnvironmentsModule(
            MergeEnvironmentConfig(max_chars=args.merge_env_max_chars)
        )
        merge_environments, onto_1_leftover, onto_2_leftover = extractor.extract(
            onto_1, onto_2, alignments
        )

        total = len(merge_environments)
        semaphore = asyncio.Semaphore(settings.max_concurrent_merges)
        merger = MergeEnvironmentsModule()

        log.info(
            "Merging %d environments | max_concurrent: %d",
            total,
            settings.max_concurrent_merges,
        )

        async def _merge_one(env, idx):
            async with semaphore:
                result = await merger.merge(env)
                log.info("Merged environment %d/%d", idx + 1, total)
                return result

        merged_environments = await asyncio.gather(
            *[_merge_one(env, i) for i, env in enumerate(merge_environments)]
        )

        if settings.debug:
            save_pre_merge_debug(
                merge_environments, onto_1_leftover, onto_2_leftover,
                settings.save_location,
            )
            save_post_merge_debug(
                list(merged_environments), onto_1_leftover, onto_2_leftover,
                settings.save_location,
            )
            save_diff_debug(
                merge_environments, list(merged_environments),
                settings.save_location,
            )

        merged_onto = integrate_environments(
            list(merged_environments), onto_1_leftover, onto_2_leftover
        )

        save_ontology(merged_onto)
