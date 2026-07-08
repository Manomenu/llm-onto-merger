# article_analysis_deepseek — combined gpt-oss + deepseek repeated-runs analysis

Extends every chart/table of `tests/article_analysis_gptoss/` with one extra
method column, so each figure compares:

> Naive Union, Applied Alignments, AROM, CoMerger, Boomer,
> **Proposed: gpt-oss**, **Proposed: deepseek-v4-flash**

with the **median [min; max]** statistic across N repeated runs ("turns") —
bar height = median, min and max marked on every bar; tables show
`median [min; max]`.

## Data flow — the gpt-oss side is never computed here

1. **Step 0** delegates to `../article_analysis_gptoss/analyze-all.sh` (same
   turns, `--no-run` passed through). That script reuses the
   `tests/analiza-variance` run tree wherever it exists, backfills the rest
   via `s2.sh`/`s3.sh`, and leaves per-turn report views under
   `article_analysis_gptoss/work/source/<turn>/` plus per-turn OAEI CSVs —
   this folder reads those directly (baseline columns + "Proposed: gpt-oss").
2. **Step 1** ensures the deepseek runs exist per turn under
   `tests/article_scenarios/outputs/<turn>/s5|s6/` and backfills any missing
   dataset with `s5.sh` / `s6.sh --label <turn> --only <dataset>`
   (OpenRouter deepseek-v4-flash).
3. Aggregation merges both sides per turn (`extract_metric_combined.py`,
   `merge_oaei_runs.py` for OAEI) and feeds the shared median/min/max
   helpers.

The deepseek backfill is granular twice over: it targets single datasets
(`--only`), and it inspects the dataset dir before running — if
`merged_ontology.owl` already exists the LLM step is never re-paid
(`--skip-mine`), and if the baseline outputs are also complete only the
report is regenerated (`--skip-all`). Baselines themselves are deterministic
and live in the label-independent shared cache
`tests/article_scenarios/outputs/.baseline_cache/aml|ref/<dataset>/` — only
the LLM merger runs per turn.

## Running

```bash
tests/article_analysis_deepseek/extend.sh 5    # turn1..turn5: reuse, backfill, aggregate
bash analyze-all.sh turn1 turn2                # explicit subset
bash analyze-all.sh --no-run                   # aggregate only; skip missing data
```

Dataset lists (display labels):

- **s5 / core dimensions:** confOf-ekaw, human-mouse, swo-acm, swo-union
- **s6 (reference-input):** cmt-edas, confOf-ekaw, human-mouse
- **OAEI validation:** confOf-ekaw, human-mouse — cmt-edas is measured only
  under the reference input, and the OAEI validation hard-requires each
  dataset's AML-input run, so cmt-edas cannot appear in the OAEI charts.

## Independence of the turns (prompt-cache busting)

`s5.sh`/`s6.sh` pass `--run-nonce "<label>:<scenario>:<dataset>"` to
`llm-onto-merger`, which prepends the nonce to the LLM system instructions.
Two turns of the same dataset therefore share **no common prompt prefix**, so
provider-side prompt/prefix caches (OpenRouter, DeepSeek) can never reuse
state from an earlier turn — every turn is sampled independently.

## Outputs (per dimension, under `tests/article_analysis_deepseek/<dim>/`)

- `*_med.csv`  — wide `method,<metric>,<metric>_min,<metric>_max,…` (feeds the plotter)
- `*_pm.csv`   — thesis-ready `median [min; max]` table
- `*_med.jpg`  — grouped bar chart: bar = median, whiskers mark min and max
- `work/<turn>/…` — per-turn scratch (raw + aggregate CSVs; safe to delete)

Dimensions mirrored from `tests/analiza-variance/`: accuracy (TPR),
conciseness (SUR, SR), structural_coherence (cycle count — table only),
knowledge_completeness (NCRC, NIRC, TCC), hierarchy_integration_quality (ARC,
depth, breadth %-change), understandability (CCR), domain_coherence
(applied-alignments %-change, multi-D/R, **and** the OAEI reference
validation).

## Building blocks (reusable)

- `extract_metric_combined.py` — one turn's gpt-oss view + deepseek tree → raw
  metric CSV with both Proposed columns.
- `merge_oaei_runs.py` — one turn's gpt-oss + deepseek `oaei_rejection.py`
  CSVs → single CSV with both Proposed rows.
- `combine_turns.py` — N per-turn aggregate CSVs → median/min/max wide CSV + pm table.
- `plot_turns.py`    — grouped bars with asymmetric min/max whiskers (same flags as `../analiza/plot_pct.py`, plus `--n-turns`).
- `combine_oaei.py`  — N per-turn OAEI CSVs → median/min/max OAEI table + chart.
