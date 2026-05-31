import argparse
import os
from pathlib import Path

from pydantic import BaseModel

from .logger import get_logger
from .settings import settings

log = get_logger(__name__)


class LoadedArguments(BaseModel):
    base_path: str
    candidate_path: str
    alignment_tool: str = "aml"
    output_dir: str
    merge_env_max_chars: int = 10_000
    parallel_llm_request_count: int = 4


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
        "--output", default=None, help="Output directory (merged_ontology.owl and debug files are saved here)"
    )
    parser.add_argument(
        "--max-env-chars",
        type=int,
        default=10_000,
        help="Max characters per MergeEnvironment string (default: 10000)",
    )
    parser.add_argument(
        "--parallel-llm-request-count",
        type=int,
        default=None,
        help=(
            f"Number of concurrent LLM requests.  When omitted, falls back to "
            f"the PARALLEL_LLM_REQUEST_COUNT value from .env / settings "
            f"(current: {settings.parallel_llm_request_count})."
        ),
    )
    args = parser.parse_args()

    # Validation
    for path_attr in ["base", "candidate"]:
        path = getattr(args, path_attr)
        if not os.path.exists(path):
            parser.error(f"File not found for --{path_attr}: {path}")
        if not os.path.isfile(path):
            parser.error(f"Path for --{path_attr} is not a file: {path}")

    if args.output is not None:
        output_dir = args.output
    elif settings.use_vllm:
        output_dir = f"tests/vllm_outputs/{Path(args.base).parent.name}"
    else:
        output_dir = "tests/outputs"

    parallel_llm_request_count = (
        args.parallel_llm_request_count
        if args.parallel_llm_request_count is not None
        else settings.parallel_llm_request_count
    )

    loaded = LoadedArguments(
        base_path=args.base,
        candidate_path=args.candidate,
        alignment_tool=args.alignment_tool,
        output_dir=output_dir,
        merge_env_max_chars=args.max_env_chars,
        parallel_llm_request_count=parallel_llm_request_count,
    )
    log.info(
        "Arguments loaded | base: %s | candidate: %s | alignment_tool: %s"
        " | output_dir: %s | max_env_chars: %d | parallel_llm_request_count: %d",
        loaded.base_path,
        loaded.candidate_path,
        loaded.alignment_tool,
        loaded.output_dir,
        loaded.merge_env_max_chars,
        loaded.parallel_llm_request_count,
    )
    return loaded
