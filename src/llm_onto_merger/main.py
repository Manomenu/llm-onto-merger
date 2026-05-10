from llm_onto_merger.alignment import alignment_modules_dict
from llm_onto_merger.merger import LLMOntologyMerger

from .load_arguments import load_arguments


async def _main():
    loaded_args = load_arguments()

    await LLMOntologyMerger.merge(
        loaded_args,
        alignment_modules_dict[loaded_args.alignment_tool](),
    )


def main():
    import asyncio

    asyncio.run(_main())


if __name__ == "__main__":
    main()
