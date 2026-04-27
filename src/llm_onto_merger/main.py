from llm_onto_merger.alignment import AlignmentModule, alignment_modules_dict

from .load_arguments import load_arguments


class LLMOntologyMerger:
    @staticmethod
    async def run(
        base_ontology_path: str,
        candidate_ontology_path: str,
        alignment_module: AlignmentModule,
    ) -> None:
        await alignment_module.create_alignment(
            base_ontology_path,
            candidate_ontology_path,
        )


async def _main():
    loaded_args = load_arguments()

    await LLMOntologyMerger.run(
        loaded_args.base_path,
        loaded_args.candidate_path,
        alignment_modules_dict[loaded_args.alignment_tool](),
    )


def main():
    import asyncio

    asyncio.run(_main())


if __name__ == "__main__":
    main()
