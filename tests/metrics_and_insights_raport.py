#!/usr/bin/env python3
"""
Combined Metrics & Insights report comparing multiple scenario outputs.

Usage:
    uv run python tests/metrics_and_insights_raport.py \\
        --inputs tests/inputs/<dataset> \\
        --output <path-to-output.html> \\
        <scenario_dir_1> <scenario_dir_2> [scenario_dir_N...]

Each scenario directory must contain merged_ontology.owl.  Optional files
read when present: applied_alignments.owl, insights.csv, alignment_stats.json.

Produces:
    <output>.html  — full report with three sections:
                     (1) metrics per scenario (like metrics_def.html),
                     (2) full insights per scenario (all envs from insights.csv),
                     (3) comparison of merged_ontology metric values across all
                         scenarios with deltas vs the first (baseline) scenario.
    <output>.csv   — same data as flat multi-section CSV.

Reuses functions from tests/metrics_def.py — no logic duplication.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from rdflib import Graph, URIRef

sys.path.insert(0, str(Path(__file__).parent))
from metrics_def import (  # noqa: E402
    _CATEGORIES,
    _REGISTRY,
    _SOURCE_BORDER,
    _cat_badges,
    _compute_self_metrics,
    _compute_suspected_counts,
    _fmt,
    _fmt_applied,
    _load_graph,
    _reasoner_check,
)

# ── Per-scenario computation ───────────────────────────────────────────────────


def _compute_scenario(
    out_dir: Path,
    onto1: Graph,
    onto2: Graph,
    union: Graph,
    onto1_entities: set[URIRef],
    onto2_entities: set[URIRef],
) -> dict | None:
    merged_path = out_dir / "merged_ontology.owl"
    if not merged_path.exists():
        print(
            f"  WARNING: {merged_path} not found — skipping scenario {out_dir.name}",
            file=sys.stderr,
        )
        return None

    applied_path = out_dir / "applied_alignments.owl"
    boomer_path = out_dir / "boomer_ontology.owl"
    arom_path = out_dir / "arom_ontology.owl"
    comerger_path = out_dir / "comerger_ontology.owl"
    insights_path = out_dir / "insights.csv"
    alignment_stats_path = out_dir / "alignment_stats.json"
    boomer_stats_path = out_dir / "boomer_stats.json"
    arom_stats_path = out_dir / "arom_stats.json"

    merged = _load_graph(str(merged_path))
    applied = _load_graph(str(applied_path)) if applied_path.exists() else None
    boomer = _load_graph(str(boomer_path)) if boomer_path.exists() else None
    arom = _load_graph(str(arom_path)) if arom_path.exists() else None
    comerger = _load_graph(str(comerger_path)) if comerger_path.exists() else None
    arom_provenance: dict[str, dict[str, str]] | None = None
    if arom is not None and arom_stats_path.exists():
        arom_provenance = json.loads(
            arom_stats_path.read_text(encoding="utf-8")
        ).get("code_provenance")

    graphs: dict[str, Graph] = {"union_input": union, "merged_ontology": merged}
    if applied is not None:
        graphs["applied_alignments"] = applied
    if arom is not None:
        graphs["arom_ontology"] = arom
    if comerger is not None:
        graphs["comerger_ontology"] = comerger
    if boomer is not None:
        graphs["boomer_ontology"] = boomer

    metrics: dict[str, dict[str, float | None]] = {}
    for name, g in graphs.items():
        union_arg = None if name == "union_input" else union
        prov = arom_provenance if name == "arom_ontology" else None
        metrics[name] = _compute_self_metrics(
            g, onto1_entities, onto2_entities, union_arg, arom_provenance=prov
        )

    print(f"  running HermiT for {out_dir.name} …")
    for name, g in graphs.items():
        metrics[name].update(_reasoner_check(g, f"{out_dir.name}/{name}"))

    suspected_counts: dict[str, int] = {}
    alignment_stats: dict | None = None
    if alignment_stats_path.exists():
        alignment_stats = json.loads(alignment_stats_path.read_text(encoding="utf-8"))
        total = float(alignment_stats.get("total_alignments", 0))
        applied_count = float(alignment_stats.get("applied_count", 0))
        rejected = alignment_stats.get("rejected_alignments", [])
        rejected_count = int(total - applied_count)

        if "union_input" in metrics:
            metrics["union_input"]["applied_alignments"] = 0.0
        if "applied_alignments" in metrics:
            metrics["applied_alignments"]["applied_alignments"] = total
        if "merged_ontology" in metrics:
            metrics["merged_ontology"]["applied_alignments"] = applied_count
        # AROM has no rejection — applies all alignments ≥ threshold (default 0.0)
        if "arom_ontology" in metrics:
            metrics["arom_ontology"]["applied_alignments"] = total
        # CoMerger: count owl:equivalentClass triples (it may filter via consistency)
        if "comerger_ontology" in metrics and comerger is not None:
            from rdflib.namespace import OWL as _OWL
            equiv_count = sum(1 for _ in comerger.triples((None, _OWL.equivalentClass, None)))
            metrics["comerger_ontology"]["applied_alignments"] = float(equiv_count)

        if applied is not None and rejected:
            tainted_uris = {URIRef(a["entity1"]) for a in rejected}
            suspected_counts = _compute_suspected_counts(
                applied, onto1_entities, onto2_entities, tainted_uris
            )
            suspected_counts["applied_alignments"] = rejected_count

    # Boomer accepted-equiv count (from sidecar written by apply_boomer.py)
    if boomer_stats_path.exists() and "boomer_ontology" in metrics:
        bstats = json.loads(boomer_stats_path.read_text(encoding="utf-8"))
        metrics["boomer_ontology"]["applied_alignments"] = float(
            bstats.get("accepted_equiv_count", 0)
        )

    insights_rows: list[dict] = []
    if insights_path.exists():
        with insights_path.open(encoding="utf-8") as f:
            insights_rows = list(csv.DictReader(f))

    return {
        "label": out_dir.name,
        "out_dir": out_dir,
        "metrics": metrics,
        "suspected_counts": suspected_counts,
        "insights_rows": insights_rows,
        "alignment_stats": alignment_stats,
        "has_applied": applied is not None,
        "has_boomer": boomer is not None,
        "has_arom": arom is not None,
        "has_comerger": comerger is not None,
    }


# ── Comparison helpers ─────────────────────────────────────────────────────────


def _delta_direction(metric_name: str, baseline: float, value: float) -> str:
    """Return 'better' / 'worse' / 'neutral' based on the metric's target."""
    if baseline == value:
        return "neutral"
    meta = _REGISTRY.get(metric_name, {})
    target = meta.get("target", "").lower()
    if "= 1.0" in target:
        return "better" if abs(value - 1.0) < abs(baseline - 1.0) else "worse"
    if "= 0" in target or "low" in target:
        return "better" if value < baseline else "worse"
    if "high" in target:
        return "better" if value > baseline else "worse"
    return "neutral"


def _fmt_compare_cell(
    metric_name: str, baseline: float | None, value: float | None, is_baseline: bool
) -> str:
    if value is None:
        return '<td class="na">N/A</td>'
    base_text = (
        f"{int(value)}" if value == int(value) and abs(value) < 1e9 else f"{value:.4f}"
    )
    if is_baseline or baseline is None:
        return f'<td class="num">{base_text}</td>'
    direction = _delta_direction(metric_name, baseline, value)
    raw_diff = value - baseline
    meta = _REGISTRY.get(metric_name, {})
    target = meta.get("target", "")
    is_ratio = "= 1.0" in target or (0 < abs(baseline) <= 1.0 and abs(value) <= 1.0)
    if is_ratio and baseline != 0:
        diff_text = f"{100 * raw_diff / baseline:+.1f}%"
    elif value == int(value) and baseline == int(baseline) and abs(value) < 1e9:
        diff_text = f"{int(raw_diff):+d}"
    else:
        diff_text = f"{raw_diff:+.4f}"
    return (
        f'<td class="num">'
        f'<span class="val">{base_text}</span> '
        f'<span class="delta delta-{direction}">{diff_text}</span>'
        f"</td>"
    )


# ── HTML rendering ─────────────────────────────────────────────────────────────


_HTML_CSS = """
body { font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a;
       background: #fafafa; }
h1   { font-size: 1.5rem; margin: 0 0 0.3rem; }
h2   { font-size: 1.15rem; margin: 2rem 0 0.8rem;
       border-bottom: 2px solid #d0d0d0; padding-bottom: 0.3rem; }
h3   { font-size: 1.0rem; margin: 1.2rem 0 0.5rem; color: #2c3e50; }
p.sub { color: #666; font-size: 0.9rem; margin: 0 0 1rem; }
.scenario-section { background: #fff; border: 1px solid #ddd; border-radius: 8px;
                    padding: 1rem 1.4rem; margin-bottom: 1.2rem; }
.scenario-meta { font-size: 0.82rem; color: #666; margin-bottom: 0.6rem; }
table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
th, td { padding: 0.45rem 0.6rem; text-align: left; vertical-align: top;
         border: 1px solid #d8d8d8; }
th { background: #2c3e50; color: #fff; font-weight: 600; white-space: nowrap; }
tr:nth-child(even) td { background: #f9f9f9; }
tr:hover td { background: #eef5fb; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.na  { text-align: center; color: #aaa; }
td.src { font-size: 0.78rem; white-space: nowrap; }
td.tgt { font-size: 0.78rem; color: #666; white-space: nowrap; }
td.cats { max-width: 220px; }
td.interp { font-size: 0.8rem; color: #444; max-width: 280px; }
.badge { display: inline-block; padding: 2px 7px; border-radius: 3px;
         font-size: 0.7rem; margin: 1px; color: #fff; white-space: nowrap; }
.susp { color: #c0392b; font-size: 0.76rem; font-weight: 600;
        margin-left: 0.2rem; cursor: help; }
.delta { font-size: 0.78rem; font-weight: 600; margin-left: 0.3rem;
         font-variant-numeric: tabular-nums; }
.delta-better  { color: #2e7d32; }
.delta-worse   { color: #c62828; }
.delta-neutral { color: #888; }
tr.total td { background: #e8eef5 !important; font-weight: 700; }
"""


def _render_metrics_table(scenario: dict) -> str:
    rows_html: list[str] = []
    metrics = scenario["metrics"]
    suspected = scenario["suspected_counts"]
    has_applied = scenario["has_applied"]
    has_boomer = scenario["has_boomer"]
    has_arom = scenario["has_arom"]
    has_comerger = scenario["has_comerger"]
    for metric_name, meta in _REGISTRY.items():
        u_val = metrics.get("union_input", {}).get(metric_name)
        m_val = metrics.get("merged_ontology", {}).get(metric_name)
        a_val = (
            metrics.get("applied_alignments", {}).get(metric_name)
            if has_applied else None
        )
        b_val = (
            metrics.get("boomer_ontology", {}).get(metric_name)
            if has_boomer else None
        )
        ar_val = (
            metrics.get("arom_ontology", {}).get(metric_name)
            if has_arom else None
        )
        c_val = (
            metrics.get("comerger_ontology", {}).get(metric_name)
            if has_comerger else None
        )
        if all(v is None for v in (u_val, m_val, a_val, b_val, ar_val, c_val)):
            continue
        border = _SOURCE_BORDER.get(meta["source"], "#ccc")
        badges = _cat_badges(meta["categories"])
        susp = suspected.get(metric_name, 0)
        applied_cell = _fmt_applied(a_val, susp) if has_applied else ""
        arom_cell = _fmt(ar_val) if has_arom else ""
        comerger_cell = _fmt(c_val) if has_comerger else ""
        boomer_cell = _fmt(b_val) if has_boomer else ""
        rows_html.append(
            f'    <tr style="border-left: 3px solid {border}">'
            f"<td><strong>{metric_name}</strong></td>"
            f"{_fmt(u_val)}"
            f"{applied_cell}"
            f"{arom_cell}"
            f"{comerger_cell}"
            f"{boomer_cell}"
            f"{_fmt(m_val)}"
            f'<td class="tgt">{meta["target"]}</td>'
            f'<td class="src">{meta["source"]}</td>'
            f'<td class="cats">{badges}</td>'
            f'<td class="interp">{meta["interpretation"]}</td>'
            f"</tr>"
        )
    applied_header = "<th>applied_alignments</th>" if has_applied else ""
    arom_header = "<th>arom_ontology</th>" if has_arom else ""
    comerger_header = "<th>comerger_ontology</th>" if has_comerger else ""
    boomer_header = "<th>boomer_ontology</th>" if has_boomer else ""
    return f"""<table>
  <thead><tr>
    <th>Metric</th><th>union_input</th>{applied_header}{arom_header}{comerger_header}{boomer_header}<th>merged_ontology</th>
    <th>Target</th><th>Source</th><th>Categories</th><th>Interpretation</th>
  </tr></thead>
  <tbody>
{chr(10).join(rows_html)}
  </tbody>
</table>"""


def _render_insights_table(scenario: dict) -> str:
    rows = scenario["insights_rows"]
    if not rows:
        return '<p style="color:#888;font-size:0.85rem;">insights.csv brak w tej ścieżce</p>'
    header = list(rows[0].keys())
    body_rows: list[str] = []
    for r in rows:
        is_total = str(r.get("env", "")).upper() == "TOTAL"
        tr_cls = ' class="total"' if is_total else ""
        cells = "".join(f'<td class="num">{r[c]}</td>' for c in header)
        body_rows.append(f"    <tr{tr_cls}>{cells}</tr>")
    return f"""<table>
  <thead><tr>{"".join(f"<th>{h}</th>" for h in header)}</tr></thead>
  <tbody>
{chr(10).join(body_rows)}
  </tbody>
</table>"""


def _render_comparison_table(scenarios: list[dict], graph_name: str) -> str:
    """Render comparison table for a specific graph column ('merged_ontology' or 'boomer_ontology')."""
    baseline = scenarios[0]
    labels = [s["label"] for s in scenarios]

    headers = [
        f"<th>{labels[0]} <span style='font-weight:400;color:#aaa;'>(baseline)</span></th>"
    ]
    for label in labels[1:]:
        headers.append(f"<th>{label}</th>")

    body_rows: list[str] = []
    for metric_name, meta in _REGISTRY.items():
        baseline_val = baseline["metrics"].get(graph_name, {}).get(metric_name)
        scenario_vals = [
            s["metrics"].get(graph_name, {}).get(metric_name) for s in scenarios
        ]
        if all(v is None for v in scenario_vals):
            continue
        border = _SOURCE_BORDER.get(meta["source"], "#ccc")
        cells = [
            _fmt_compare_cell(metric_name, None, scenario_vals[0], is_baseline=True)
        ]
        for v in scenario_vals[1:]:
            cells.append(
                _fmt_compare_cell(metric_name, baseline_val, v, is_baseline=False)
            )
        body_rows.append(
            f'    <tr style="border-left: 3px solid {border}">'
            f"<td><strong>{metric_name}</strong></td>"
            f"{''.join(cells)}"
            f'<td class="tgt">{meta["target"]}</td>'
            f"</tr>"
        )

    return f"""<table>
  <thead><tr>
    <th>Metric</th>{"".join(headers)}<th>Target</th>
  </tr></thead>
  <tbody>
{chr(10).join(body_rows)}
  </tbody>
</table>
<p style="font-size:0.82rem;color:#666;margin-top:0.5rem;">
  <span class="delta delta-better">+/-</span> zielony = bliżej target wg <code>_REGISTRY</code>;
  <span class="delta delta-worse">+/-</span> czerwony = gorzej;
  <span class="delta delta-neutral">+/-</span> szary = context-dependent.
  Procenty dla metryk ratio (target = 1.0 lub baseline ∈ (0,1]), liczby absolutne dla pozostałych.
</p>"""


def _render_legend() -> str:
    cat_html = "\n".join(
        f'    <span class="badge" style="background:{color}">{cat}</span>'
        for cat, (_, color) in _CATEGORIES.items()
    )
    return f"""<div style="margin-top:1.5rem;font-size:0.82rem;color:#555;">
  <div><strong>Categories:</strong></div>
  <div style="margin-top:0.3rem;">
{cat_html}
  </div>
  <div style="margin-top:0.6rem;">
    <strong>Source border:</strong>
    <span style="display:inline-block;width:4px;height:14px;background:{_SOURCE_BORDER["self-implemented"]};vertical-align:middle;margin-right:4px;"></span>
    self-implemented &nbsp;
    <span style="display:inline-block;width:4px;height:14px;background:{_SOURCE_BORDER["hermit_reasoner"]};vertical-align:middle;margin-right:4px;"></span>
    hermit_reasoner
  </div>
</div>"""


def _align_stats_label(stats: dict | None) -> str:
    if not stats:
        return "brak"
    applied = int(stats.get("applied_count", 0))
    total = int(stats.get("total_alignments", 0))
    return f"applied {applied}/{total}"


def _scenario_metrics_block(s: dict) -> str:
    applied_mark = "✓" if s["has_applied"] else "✗"
    arom_mark = "✓" if s["has_arom"] else "✗"
    comerger_mark = "✓" if s["has_comerger"] else "✗"
    boomer_mark = "✓" if s["has_boomer"] else "✗"
    align_label = _align_stats_label(s["alignment_stats"])
    return (
        f'<div class="scenario-section"><h3>Scenariusz: <code>{s["label"]}</code></h3>'
        f'<div class="scenario-meta">'
        f"merged_ontology.owl: ✓ &nbsp; "
        f"applied_alignments.owl: {applied_mark} &nbsp; "
        f"arom_ontology.owl: {arom_mark} &nbsp; "
        f"comerger_ontology.owl: {comerger_mark} &nbsp; "
        f"boomer_ontology.owl: {boomer_mark} &nbsp; "
        f"alignment_stats: {align_label}"
        f"</div>"
        f"{_render_metrics_table(s)}</div>"
    )


def _build_html(scenarios: list[dict], inputs_dir: Path) -> str:
    summary = (
        f"<strong>{len(scenarios)}</strong> scenariuszy &nbsp;|&nbsp; "
        f"inputs: <code>{inputs_dir}</code> &nbsp;|&nbsp; "
        f"baseline: <code>{scenarios[0]['label']}</code>"
    )
    sec1 = "\n".join(_scenario_metrics_block(s) for s in scenarios)
    sec2 = "\n".join(
        f'<div class="scenario-section"><h3>Scenariusz: <code>{s["label"]}</code></h3>'
        f"{_render_insights_table(s)}</div>"
        for s in scenarios
    )
    sec3 = (
        '<div class="scenario-section">'
        + _render_comparison_table(scenarios, "merged_ontology")
        + "</div>"
    )
    sec4_html = ""
    if any(s["has_boomer"] for s in scenarios):
        sec4_html = (
            "<h2>4. Porównanie <code>boomer_ontology</code> — wszystkie scenariusze</h2>\n"
            '<div class="scenario-section">'
            + _render_comparison_table(scenarios, "boomer_ontology")
            + "</div>"
        )
    sec5_html = ""
    if any(s["has_arom"] for s in scenarios):
        sec5_html = (
            "<h2>5. Porównanie <code>arom_ontology</code> — wszystkie scenariusze</h2>\n"
            '<div class="scenario-section">'
            + _render_comparison_table(scenarios, "arom_ontology")
            + "</div>"
        )
    sec6_html = ""
    if any(s["has_comerger"] for s in scenarios):
        sec6_html = (
            "<h2>6. Porównanie <code>comerger_ontology</code> — wszystkie scenariusze</h2>\n"
            '<div class="scenario-section">'
            + _render_comparison_table(scenarios, "comerger_ontology")
            + "</div>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Metrics &amp; Insights Report</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<h1>Metrics &amp; Insights Report</h1>
<p class="sub">{summary}</p>

<h2>1. Metryki per scenariusz</h2>
{sec1}

<h2>2. Insights per scenariusz</h2>
{sec2}

<h2>3. Porównanie <code>merged_ontology</code> — wszystkie scenariusze</h2>
{sec3}

{sec4_html}

{sec5_html}

{sec6_html}

{_render_legend()}
</body>
</html>"""


# ── CSV rendering ──────────────────────────────────────────────────────────────


def _build_csv_rows(scenarios: list[dict]) -> list[list[str]]:
    rows: list[list[str]] = []
    rows.append(["# section: metrics (per scenario, per metric, per graph)"])
    rows.append(["section", "scenario", "metric", "graph", "value", "suspected"])
    for s in scenarios:
        for graph_name, graph_metrics in s["metrics"].items():
            for metric_name, value in graph_metrics.items():
                susp = (
                    s["suspected_counts"].get(metric_name, "")
                    if graph_name == "applied_alignments"
                    else ""
                )
                rows.append(
                    [
                        "metrics",
                        s["label"],
                        metric_name,
                        graph_name,
                        "" if value is None else str(value),
                        str(susp),
                    ]
                )

    rows.append([])
    rows.append(["# section: insights (per scenario, per env)"])
    for s in scenarios:
        if not s["insights_rows"]:
            continue
        header = list(s["insights_rows"][0].keys())
        rows.append(["section", "scenario"] + header)
        for r in s["insights_rows"]:
            rows.append(["insights", s["label"]] + [r[h] for h in header])

    def _emit_comparison_section(graph_name: str) -> None:
        rows.append([])
        rows.append(
            [f"# section: comparison ({graph_name} metric values across scenarios)"]
        )
        baseline = scenarios[0]
        labels = [s["label"] for s in scenarios]
        header = ["metric", labels[0] + "_baseline"]
        for label in labels[1:]:
            header += [label, label + "_delta_vs_baseline", label + "_direction"]
        rows.append(header)
        for metric_name in _REGISTRY:
            baseline_val = baseline["metrics"].get(graph_name, {}).get(metric_name)
            scenario_vals = [
                s["metrics"].get(graph_name, {}).get(metric_name) for s in scenarios
            ]
            if all(v is None for v in scenario_vals):
                continue
            row = [
                metric_name,
                "" if scenario_vals[0] is None else str(scenario_vals[0]),
            ]
            for v in scenario_vals[1:]:
                if v is None or baseline_val is None:
                    row += ["", "", ""]
                else:
                    row += [
                        str(v),
                        f"{v - baseline_val:+g}",
                        _delta_direction(metric_name, baseline_val, v),
                    ]
            rows.append(row)

    _emit_comparison_section("merged_ontology")
    if any(s["has_boomer"] for s in scenarios):
        _emit_comparison_section("boomer_ontology")
    if any(s["has_arom"] for s in scenarios):
        _emit_comparison_section("arom_ontology")
    if any(s["has_comerger"] for s in scenarios):
        _emit_comparison_section("comerger_ontology")
    return rows


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combined Metrics & Insights report comparing scenario outputs."
    )
    parser.add_argument(
        "--inputs",
        required=True,
        help="Path to inputs directory containing exactly 2 .owl files (same for all scenarios).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to output .html file. CSV will be written alongside with .csv extension.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Paths to scenario output directories (≥1).  Label = basename.",
    )
    args = parser.parse_args()

    inputs_dir = Path(args.inputs)
    if not inputs_dir.is_dir():
        sys.exit(f"--inputs is not a directory: {inputs_dir}")
    owl_files = sorted(inputs_dir.glob("*.owl"))
    if len(owl_files) != 2:
        sys.exit(
            f"Expected exactly 2 .owl files in {inputs_dir}, found {len(owl_files)}"
        )

    print(f"Loading inputs from {inputs_dir}")
    onto1 = _load_graph(str(owl_files[0]))
    onto2 = _load_graph(str(owl_files[1]))
    union = Graph()
    for t in onto1:
        union.add(t)
    for t in onto2:
        union.add(t)
    onto1_entities: set[URIRef] = {s for s, _, _ in onto1 if isinstance(s, URIRef)}
    onto2_entities: set[URIRef] = {s for s, _, _ in onto2 if isinstance(s, URIRef)}
    print(f"  union_input: {len(union)} triples")

    scenarios: list[dict] = []
    for path_str in args.paths:
        path = Path(path_str)
        print(f"\nProcessing scenario: {path}")
        scenario = _compute_scenario(
            path, onto1, onto2, union, onto1_entities, onto2_entities
        )
        if scenario is not None:
            scenarios.append(scenario)

    if not scenarios:
        sys.exit("No valid scenarios — every path was missing merged_ontology.owl")

    out_html = Path(args.output)
    out_csv = out_html.with_suffix(".csv")
    out_html.parent.mkdir(parents=True, exist_ok=True)

    out_html.write_text(_build_html(scenarios, inputs_dir), encoding="utf-8")
    print(f"\nReport HTML: {out_html}")

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(_build_csv_rows(scenarios))
    print(f"Report CSV:  {out_csv}")


if __name__ == "__main__":
    main()
