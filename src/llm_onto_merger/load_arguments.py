import argparse
import os

from pydantic import BaseModel

from .logger import get_logger

log = get_logger(__name__)


class LoadedArguments(BaseModel):
    base_path: str
    candidate_path: str
    alignment_tool: str = "aml"
    output_path: str
    merge_env_max_chars: int = 10_000


def load_arguments() -> LoadedArguments:
    parser = argparse.ArgumentParser(
        description="Ontology Merging System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run llm-onto-merger --base base.owl --candidate cand.owl\n"
            "  uv run llm-onto-merger --base base.owl --candidate cand.owl "\
            "--alignment-tool aml --output merged.owl\n"
        ),
    )
    parser.add_argument("--base", required=True, help="Path to base ontology")
    parser.add_argument(
        "--candidate", required=True, help="Path to candidate ontology"
    )
    parser.add_argument(
        "--alignment-tool",
        default="aml",
        help="Alignment tool to use (default: aml)",
    )
    parser.add_argument(
        "--output", default="merged_ontology.owl", help="Output file path"
    )
    parser.add_argument(
        "--max-env-chars",
        type=int,
        default=10_000,
        help="Max characters per MergeEnvironment string (default: 10000)",
    )
    args = parser.parse_args()

    # Validation
    for path_attr in ["base", "candidate"]:
        path = getattr(args, path_attr)
        if not os.path.exists(path):
            parser.error(f"File not found for --{path_attr}: {path}")
        if not os.path.isfile(path):
            parser.error(f"Path for --{path_attr} is not a file: {path}")

    loaded = LoadedArguments(
        base_path=args.base,
        candidate_path=args.candidate,
        alignment_tool=args.alignment_tool,
        output_path=args.output,
        merge_env_max_chars=args.max_env_chars,
    )
    log.info(
        "Arguments loaded | base: %s | candidate: %s | alignment_tool: %s (default: aml)"
        " | output: %s | max_env_chars: %d (default: 10000)",
        loaded.base_path,
        loaded.candidate_path,
        loaded.alignment_tool,
        loaded.output_path,
        loaded.merge_env_max_chars,
    )
    return loaded
