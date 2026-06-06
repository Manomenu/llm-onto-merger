#!/usr/bin/env python3
"""Generate applied_alignments.owl — naive union + owl:equivalentClass baseline.

Uses raw (non-relabelled) ontology graphs so triple_preservation_ratio is
directly comparable to the raw union input.

Usage:
    uv run python tests/generate_applied_alignments.py \\
        --onto1 path/to/onto1.owl \\
        --onto2 path/to/onto2.owl \\
        --output path/to/cache_dir \\
        [--tool aml|logmap]
"""

import argparse
import asyncio
import sys
from pathlib import Path

from rdflib import Graph

from llm_onto_merger.alignment import alignment_modules_dict
from llm_onto_merger.ontology import apply_alignments, save_ontology


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onto1", required=True, type=Path)
    parser.add_argument("--onto2", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tool", default="aml", choices=list(alignment_modules_dict))
    args = parser.parse_args()

    if not args.onto1.exists():
        sys.exit(f"onto1 not found: {args.onto1}")
    if not args.onto2.exists():
        sys.exit(f"onto2 not found: {args.onto2}")
    args.output.mkdir(parents=True, exist_ok=True)

    print(f"[generate_applied_alignments] running {args.tool} alignment …")
    module = alignment_modules_dict[args.tool]()
    alignments = asyncio.run(module.create_alignment(args.onto1, args.onto2))
    print(f"  {args.tool} returned {len(alignments)} alignments")

    raw_1 = Graph()
    raw_1.parse(str(args.onto1))
    raw_2 = Graph()
    raw_2.parse(str(args.onto2))
    applied = apply_alignments(raw_1, raw_2, alignments)
    save_ontology(applied, args.output, name="applied_alignments")
    print(f"  saved {len(applied)} triples → {args.output}/applied_alignments.owl")


if __name__ == "__main__":
    main()
