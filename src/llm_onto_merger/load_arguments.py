import argparse
import os
from pydantic import BaseModel


class LoadedArguments(BaseModel):
    base_content: str
    candidate_content: str
    mappings_content: str
    output_path: str


def load_arguments() -> LoadedArguments:
    parser = argparse.ArgumentParser(description="Ontology Merging System")
    parser.add_argument('--base', required=True, help='Path to base ontology')
    parser.add_argument('--candidate', required=True, help='Path to candidate ontology')
    parser.add_argument('--mappings', required=True, help='Path to OAEI-standard mappings')
    parser.add_argument('--output', default='merged_ontology.owl', help='Output file path')
    args = parser.parse_args()

    # Validation
    for path_attr in ['base', 'candidate', 'mappings']:
        path = getattr(args, path_attr)
        if not os.path.exists(path):
            parser.error(f"File not found for --{path_attr}: {path}")
        if not os.path.isfile(path):
            parser.error(f"Path for --{path_attr} is not a file: {path}")

    # Loading
    try:
        with open(args.base, 'r', encoding='utf-8') as f:
            base_content = f.read()
        with open(args.candidate, 'r', encoding='utf-8') as f:
            candidate_content = f.read()
        with open(args.mappings, 'r', encoding='utf-8') as f:
            mappings_content = f.read()
    except Exception as e:
        parser.error(f"Error reading files: {e}")

    return LoadedArguments(
        base_content=base_content,
        candidate_content=candidate_content,
        mappings_content=mappings_content,
        output_path=args.output
    )
