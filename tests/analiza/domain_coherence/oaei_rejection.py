#!/usr/bin/env python3
"""OAEI reference-alignment validation (Domain Coherence) — two complementary
measures, each from the run that makes it meaningful.  Both LOWER = better.

Measure 1 — rejected correct alignments  (needs scenario_3: REFERENCE as input)
    Feed the OAEI reference (gold) alignment to every method and count how many
    of those correct correspondences the method rejects:
        rejected_correct(method) = |R − accepted_under_reference(method)|
    Clean test over the FULL gold set (no AML-miss confound).

Measure 2 — accepted AML false-positives  (needs scenario_2: AML as input)
    From the AML-input run, count AML correspondences the method applied that are
    NOT in the reference (false-positives it failed to filter):
        accepted_aml_fp(method) = |accepted_under_aml(method) ∩ (A − R)|
    Inherently needs the AML run — the reference contains no AML false-positives.

A method's accepted-pair set is recovered identically in both runs:
    Applied Alignments / AROM → all input pairs            (apply-all)
    Proposed (merger)         → input − rejected_alignments (alignment_stats.json)
    Boomer                    → code_provenance            (boomer_stats.json)
    CoMerger                  → merged# entities in comerger_ontology.owl,
                                resolved against source name sets (handles '_').
where input = reference (scenario_3) or AML candidate set A (scenario_2).
A is the provenance of Applied Alignments in scenario_2 (it applies ALL AML pairs).

Usage (one --dataset group per OAEI dataset):
    uv run python oaei_rejection.py \\
        --dataset conference  <reference.rdf> <s2_dir> <s3_dir> <tests/inputs/conference> \\
        --dataset human-mouse <reference.rdf> <s2_dir> <s3_dir> <tests/inputs/human-mouse> \\
        --out-csv oaei_rejection.csv --out-jpg oaei_rejection.jpg

If a dataset's scenario_3 dir is missing, measure 1 is skipped for it (with a
warning) and only measure 2 is reported — run tests/scenarios/scenario_3.sh first.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from rdflib import Graph, URIRef

from llm_onto_merger.alignment.alignment import parse_oaei_alignment

PairKey = frozenset
_MERGED_NS = "http://merged#"


def _local(uri: str) -> str:
    idx = max(uri.rfind("#"), uri.rfind("/"))
    return uri[idx + 1:] if idx >= 0 else uri


def _key(uri1: str, uri2: str, inverse_relabel: dict[str, str]) -> PairKey:
    a = inverse_relabel.get(_local(uri1), _local(uri1))
    b = inverse_relabel.get(_local(uri2), _local(uri2))
    return frozenset((a, b))


def _provenance_pairs(stats_path: Path, inverse_relabel: dict[str, str] | None = None) -> set[PairKey]:
    inverse_relabel = inverse_relabel or {}
    data = json.loads(stats_path.read_text(encoding="utf-8"))
    out: set[PairKey] = set()
    for entry in data.get("code_provenance", {}).values():
        u1 = entry.get("1_uri") or entry.get("1")
        u2 = entry.get("2_uri") or entry.get("2")
        if u1 and u2:
            out.add(_key(u1, u2, inverse_relabel))
    return out


def _reference_pairs(reference_path: Path) -> set[PairKey]:
    return {_key(a.entity1, a.entity2, {}) for a in parse_oaei_alignment(reference_path)}


def _load_inverse_relabel(d: Path) -> dict[str, str]:
    path = d / "relabeling_map.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {new: old for old, new in raw.items()}


def _merger_rejected(d: Path, inverse_relabel: dict[str, str]) -> set[PairKey]:
    data = json.loads((d / "alignment_stats.json").read_text(encoding="utf-8"))
    return {
        _key(r["entity1"], r["entity2"], inverse_relabel)
        for r in data.get("rejected_alignments", [])
    }


def _local_names(onto_path: Path) -> set[str]:
    g = Graph()
    g.parse(str(onto_path))
    return {_local(str(s)) for s in g.subjects() if isinstance(s, URIRef)}


def _comerger_accepted(comerger_owl: Path, names1: set[str], names2: set[str]) -> tuple[set[PairKey], int]:
    """Recover CoMerger's accepted pairs from its merged# entities.

    CoMerger collapses an accepted pair into a `merged#` entity named by joining
    the two source local names with '_'.  For same-named pairs the name is that
    name (e.g. merged#Person).  Crucially, CoMerger STRIPS internal underscores
    from the source names before joining, so an OBO pair (MA_0000009, NCI_C12472)
    becomes merged#MA0000009_NCIC12472.  We therefore resolve each candidate split
    token both directly AND against an underscore-stripped index of the source
    names, mapping back to the original (with-underscore) name.  Returns
    (accepted_keys, unresolved_count)."""
    g = Graph()
    g.parse(str(comerger_owl))
    merged_locals = {
        _local(str(t)) for t in g.all_nodes()
        if isinstance(t, URIRef) and str(t).startswith(_MERGED_NS)
    }
    # Underscore-stripped index: stripped_name → original source name.
    strip1 = {n.replace("_", ""): n for n in names1}
    strip2 = {n.replace("_", ""): n for n in names2}

    def resolve(tok: str, names: set[str], strip: dict[str, str]) -> str | None:
        if tok in names:
            return tok
        return strip.get(tok)

    accepted: set[PairKey] = set()
    unresolved = 0
    for m in merged_locals:
        if not m:
            continue
        if m in names1 and m in names2:          # same local name (e.g. Person)
            accepted.add(frozenset((m,)))
            continue
        parts = m.split("_")
        found = None
        for i in range(1, len(parts)):
            a, b = "_".join(parts[:i]), "_".join(parts[i:])
            ra1, rb2 = resolve(a, names1, strip1), resolve(b, names2, strip2)
            if ra1 and rb2:
                found = frozenset((ra1, rb2))
                break
            ra2, rb1 = resolve(a, names2, strip2), resolve(b, names1, strip1)
            if ra2 and rb1:
                found = frozenset((rb1, ra2))
                break
        if found is not None:
            accepted.add(found)
        else:
            unresolved += 1
    return accepted, unresolved


def _accepted_per_method(
    run_dir: Path, input_pairs: set[PairKey],
    names1: set[str], names2: set[str], dataset: str,
) -> dict[str, set[PairKey]]:
    """Accepted-pair set per method for one run (input = reference or AML)."""
    inverse = _load_inverse_relabel(run_dir)
    res: dict[str, set[PairKey]] = {}
    # AROM — ACTUAL accepted pairs from its provenance sidecar (NOT assumed
    # apply-all).  AROM provenance uses original source local names → no inverse
    # relabeling (that only applies to the merger's own relabelled URIs).
    if (run_dir / "arom_stats.json").exists():
        res["AROM"] = _provenance_pairs(run_dir / "arom_stats.json")
    # Proposed (merger) — input minus the pairs it explicitly rejected.
    if (run_dir / "alignment_stats.json").exists():
        res["Proposed"] = input_pairs - _merger_rejected(run_dir, inverse)
    if (run_dir / "boomer_stats.json").exists():
        res["Boomer"] = _provenance_pairs(run_dir / "boomer_stats.json")
    cm = run_dir / "comerger_ontology.owl"
    if cm.exists():
        acc, unresolved = _comerger_accepted(cm, names1, names2)
        res["CoMerger"] = acc
        if unresolved:
            print(f"  [{dataset}] CoMerger ({run_dir.name}): {unresolved} merged# "
                  f"entit(ies) unresolved → excluded")
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dataset", action="append", nargs=5, required=True,
        metavar=("NAME", "REFERENCE", "S2_DIR", "S3_DIR", "INPUT_DIR"),
        help="name, reference.rdf, scenario_2 dir (AML run), scenario_3 dir "
             "(reference run), tests/inputs/<name> dir (source ontologies).",
    )
    parser.add_argument("--out-csv", type=Path, required=True)
    parser.add_argument("--out-jpg", type=Path, required=True)
    parser.add_argument("--title",
                        default="OAEI reference-alignment validation (Domain Coherence)",
                        help="Figure suptitle.")
    parser.add_argument("--no-flag", action="store_true",
                        help="Disable the Boomer ambiguity hatch/dual-label. Use for "
                             "the ADJUSTED run where Boomer's reference ptable uses a "
                             "realistic (mean-AML) p_equiv instead of the artificial cap.")
    args = parser.parse_args()

    rows: list[dict] = []
    for name, ref_path, s2_dir, s3_dir, input_dir in args.dataset:
        ref_path, s2_dir, s3_dir, input_dir = map(Path, (ref_path, s2_dir, s3_dir, input_dir))
        if not ref_path.exists():
            sys.exit(f"[{name}] reference not found: {ref_path}")
        applied_s2 = s2_dir / "applied_stats.json"
        if not applied_s2.exists():
            sys.exit(f"[{name}] {applied_s2} missing (needed as AML candidate set A)")
        owls = sorted(input_dir.glob("*.owl"))
        if len(owls) != 2:
            sys.exit(f"[{name}] expected 2 .owl in {input_dir}, found {len(owls)}")

        R = _reference_pairs(ref_path)
        A = _provenance_pairs(applied_s2)               # full AML candidate set
        names1, names2 = _local_names(owls[0]), _local_names(owls[1])

        # Measure 2 (accept AML-FP) — from scenario_2 (AML input).
        acc_s2 = _accepted_per_method(s2_dir, A, names1, names2, name)
        # Measure 1 (reject correct) — from scenario_3 (reference input), if present.
        acc_s3 = None
        if (s3_dir / "applied_stats.json").exists() or (s3_dir / "alignment_stats.json").exists():
            acc_s3 = _accepted_per_method(s3_dir, R, names1, names2, name)
        else:
            print(f"  [{name}] scenario_3 outputs not found in {s3_dir} — measure 1 "
                  f"(rejected correct) skipped; run scenario_3.sh {name}")

        methods = sorted(set(acc_s2) | set(acc_s3 or {}))
        for m in methods:
            accepted_aml_fp = len(acc_s2[m] & (A - R)) if m in acc_s2 else None
            rejected_correct = len(R - acc_s3[m]) if acc_s3 and m in acc_s3 else None
            rows.append({
                "method": m, "dataset": name,
                "reference_total": len(R), "aml_total": len(A),
                "rejected_correct": rejected_correct,
                "accepted_aml_fp": accepted_aml_fp,
            })
        print(f"  [{name}] |R|={len(R)} |A|={len(A)} methods={methods} "
              f"measure1={'yes' if acc_s3 else 'NO (no scenario_3)'}")

    # ── CSV ──────────────────────────────────────────────────────────────────
    fieldnames = ["method", "dataset", "reference_total", "aml_total",
                  "rejected_correct", "accepted_aml_fp"]
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {args.out_csv} ({len(rows)} rows)")

    # ── per-dataset chart (NO cross-dataset aggregation) ─────────────────────
    # Grid: one row per dataset (conference, human-mouse), two columns (the two
    # measures).  Each dataset keeps its own y-scale (conference ~10s vs
    # human-mouse ~1000s would otherwise be incomparable).
    methods: list[str] = []
    for r in rows:
        if r["method"] not in methods:
            methods.append(r["method"])
    datasets: list[str] = []
    for r in rows:
        if r["dataset"] not in datasets:
            datasets.append(r["dataset"])
    lookup = {(r["method"], r["dataset"]): r for r in rows}

    # Uniform muted blue + black edge — same palette as the other thesis charts
    # (tests/analiza/plot_pct.py).
    BAR_COLOR = "#4472C4"
    measures = [
        ("rejected_correct", "Rejected correct alignments\n(reference input; lower = better)"),
        ("accepted_aml_fp", "Accepted AML false-positives\n(AML input; lower = better)"),
    ]

    # AMBIGUOUS cell(s): Boomer's human-mouse rejected_correct exists ONLY thanks
    # to the artificial p_equiv cap (0.99) on the reference ptable — without it
    # Boomer's solver fails ('No possible resolution of perplexity') → 0/undefined.
    # ONLY this single bar is hatched and labelled "<capped>/0".  Boomer's other
    # bars (conference, and accepted_aml_fp from the AML run) have no such issue.
    FLAGGED_CELLS = set() if args.no_flag else {("Boomer", "human-mouse", "rejected_correct")}

    fig, axes = plt.subplots(len(datasets), 2, figsize=(12, 5 * len(datasets)),
                             squeeze=False)
    for di, ds in enumerate(datasets):
        for mi, (metric, title) in enumerate(measures):
            ax = axes[di][mi]
            vals = [lookup.get((m, ds), {}).get(metric) for m in methods]
            bars = ax.bar(methods, [v or 0 for v in vals], color=BAR_COLOR,
                          edgecolor="black", linewidth=0.5)
            labels = []
            for bar, m, v in zip(bars, methods, vals):
                flagged = (m, ds, metric) in FLAGGED_CELLS
                if flagged:
                    bar.set_hatch("///")
                if v is None:
                    labels.append("n/a")
                elif flagged:
                    labels.append(f"{v}/0")       # with-cap / without-cap (crash)
                else:
                    labels.append(str(v))
            ax.bar_label(bars, labels=labels, padding=3)
            ax.axhline(0, color="black", linewidth=0.6)
            ax.set_title(f"{ds} — {title}")
            ax.set_ylabel("count")
            ax.tick_params(axis="x", rotation=20)
            ax.margins(y=0.2)

    fig.suptitle(args.title)
    if FLAGGED_CELLS:
        fig.text(0.5, 0.005,
                 "Hatched bar (Boomer, human-mouse rejected): relies on an artificial "
                 "p_equiv cap (0.99); uncapped Boomer fails to resolve the reference → 0/undefined.",
                 ha="center", fontsize=8, style="italic")
    fig.tight_layout(rect=(0, 0.03, 1, 1) if FLAGGED_CELLS else None)
    fig.savefig(args.out_jpg, dpi=150)
    print(f"  wrote {args.out_jpg}")


if __name__ == "__main__":
    main()
