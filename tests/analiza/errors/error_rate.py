#!/usr/bin/env python3
"""LLM error-rate per dataset, read from logs/app.log.

For each requested dataset we locate its LAST run in the log (runs are delimited
by 'Arguments loaded ... base: tests/inputs/<dataset>/...') and compute:

    error_rate = failed_environments / total_environments

where
    total_environments  = N from 'Merging N environments'      (that run)
    failed_environments = count of 'LLM response could not be parsed'  (that run)

A "failed" environment is one where the LLM response could not be parsed and the
pipeline fell back to the deterministic collapse_alignments merge.

Usage:
    uv run python error_rate.py --log ../../../logs/app.log \\
        --dataset conference --dataset human-mouse \\
        --out-csv error_rate.csv --out-jpg error_rate.jpg
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ARGS_RE = re.compile(r"Arguments loaded .* base:\s*(\S+)")
INPUT_RE = re.compile(r"tests/inputs/([^/]+)/")
MERGING_RE = re.compile(r"Merging\s+(\d+)\s+environments")
ENV_ID_RE = re.compile(r"env\s+(\d+):")
PARSE_FAIL = "could not be parsed"          # WARNING: malformed JSON → fallback
EMPTY_GRAPH = "LLM returned EMPTY merged graph"  # ERROR: parsed but empty result


def parse_log(log_path: Path) -> dict[str, dict]:
    """Return {dataset: run_info} for the LAST run of each dataset.

    An environment counts as failed if its 'env N:' id appears in either failure
    mode (parse failure or empty merged graph) or in any ERROR-level line.
    failed_environments is the count of DISTINCT failed env ids (no double count)."""
    last: dict[str, dict] = {}
    cur_ds: str | None = None
    cur: dict | None = None

    def flush() -> None:
        if cur_ds is not None and cur is not None:
            last[cur_ds] = cur          # overwrite → keeps the last run per dataset

    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = ARGS_RE.search(line)
            if m:
                flush()
                im = INPUT_RE.search(m.group(1))
                cur_ds = im.group(1) if im else None
                cur = {"total": None, "failed_ids": set(),
                       "parse_fail": 0, "empty_graph": 0, "other_error": 0}
                continue
            if cur is None:
                continue
            mm = MERGING_RE.search(line)
            if mm:
                cur["total"] = int(mm.group(1))
                continue
            is_parse = PARSE_FAIL in line
            is_empty = EMPTY_GRAPH in line
            is_error = "| ERROR " in line
            if is_parse or is_empty or is_error:
                idm = ENV_ID_RE.search(line)
                if idm:
                    cur["failed_ids"].add(int(idm.group(1)))
                if is_parse:
                    cur["parse_fail"] += 1
                elif is_empty:
                    cur["empty_graph"] += 1
                elif is_error:
                    cur["other_error"] += 1
    flush()
    return last


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--dataset", action="append", required=True,
                        help="Dataset name (matches tests/inputs/<name>/). Repeatable.")
    parser.add_argument("--out-csv", type=Path, required=True)
    parser.add_argument("--out-jpg", type=Path, required=True)
    args = parser.parse_args()

    if not args.log.exists():
        sys.exit(f"log not found: {args.log}")

    runs = parse_log(args.log)

    rows: list[dict] = []
    for ds in args.dataset:
        info = runs.get(ds)
        if info is None:
            print(f"  WARNING: no run found for '{ds}' in {args.log}")
            rows.append({"dataset": ds, "total_environments": 0,
                         "failed_environments": 0, "parse_fail": 0,
                         "empty_graph": 0, "other_error": 0, "error_rate_pct": None})
            continue
        total = info["total"]
        failed = len(info["failed_ids"])
        rate = round(100.0 * failed / total, 2) if total else None
        rows.append({"dataset": ds, "total_environments": total or 0,
                     "failed_environments": failed,
                     "parse_fail": info["parse_fail"],
                     "empty_graph": info["empty_graph"],
                     "other_error": info["other_error"],
                     "error_rate_pct": rate})
        print(f"  [{ds}] last run: {failed}/{total} envs failed "
              f"(parse={info['parse_fail']} empty={info['empty_graph']} "
              f"other_error={info['other_error']}) "
              f"→ error rate {rate if rate is not None else 'n/a'}%")

    # ── CSV ──────────────────────────────────────────────────────────────────
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["dataset", "total_environments",
                                          "failed_environments", "parse_fail",
                                          "empty_graph", "other_error", "error_rate_pct"])
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {args.out_csv}")

    # ── chart ─────────────────────────────────────────────────────────────────
    labels = [r["dataset"] for r in rows]
    rates = [r["error_rate_pct"] or 0 for r in rows]
    fig, ax = plt.subplots(figsize=(7, 5))
    bars = ax.bar(labels, rates, color="#c0392b")
    ax.set_title("LLM merge error rate per dataset (last run)\n"
                 "failed envs / total envs — lower = better")
    ax.set_ylabel("error rate [%]")
    ax.bar_label(bars,
                 labels=[("n/a" if r["error_rate_pct"] is None
                          else f"{r['error_rate_pct']}%\n({r['failed_environments']}/{r['total_environments']})")
                         for r in rows],
                 padding=3)
    ax.margins(y=0.2)
    fig.tight_layout()
    fig.savefig(args.out_jpg, dpi=150)
    print(f"  wrote {args.out_jpg}")


if __name__ == "__main__":
    main()
