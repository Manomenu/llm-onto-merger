from pathlib import Path

from llm_onto_merger.alignment.alignment import AlignmentModule
from llm_onto_merger.extract_environments import (
    ExtractEnvironmentsModule,
    MergeEnvironmentConfig,
)
from llm_onto_merger.load_arguments import LoadedArguments
from llm_onto_merger.ontology import create_ontology


class LLMOntologyMerger:
    @staticmethod
    async def run(
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
