# article_analysis_deepseek — repeated-runs analysis (deepseek-v4-flash)

Mirrors every chart/table in `tests/analiza-variance/` but for the
**deepseek/deepseek-v4-flash (OpenRouter)** pipeline, reading the
`tests/article_scenarios/` s5 (AML-input) / s6 (reference-input) outputs and
reporting **median [min; max]** across N repeated runs ("turns") — bar height
= median, with the min and max of the N runs marked on every bar.

## Generating the turns + running the analysis

```bash
tests/article_analysis_deepseek/extend.sh 5    # ensure turn1..turn5 exist,
                                               # backfill any missing dataset,
                                               # then aggregate median/min/max
```

`extend.sh N` expands to `analyze-all.sh turn1 .. turnN`. For every turn,
`analyze-all.sh` checks that the required reports exist under
`tests/article_scenarios/outputs/<turn>/` and backfills anything missing with

```bash
tests/article_scenarios/s5.sh --label <turn> --only <dataset>   # AML input
tests/article_scenarios/s6.sh --label <turn> --only <dataset>   # reference input
```

(slow — each backfill invokes the OpenRouter LLM merger).

The backfill is granular twice over: it targets single datasets (`--only`),
and it inspects the dataset dir before running — if `merged_ontology.owl`
already exists the LLM step is never re-paid (`--skip-mine`: baselines +
report only), and if the baseline outputs are also complete only the report
is regenerated (`--skip-all`).

Dataset lists (display labels):

- **s5 / core dimensions:** confOf-ekaw, human-mouse, swo-acm, swo-union
- **s6 (reference-input):** cmt-edas, confOf-ekaw, human-mouse
- **OAEI validation:** confOf-ekaw, human-mouse — cmt-edas is measured only
  under the reference input (s6), and the OAEI validation hard-requires each
  dataset's AML-input run, so cmt-edas cannot appear in the OAEI charts.

```bash
bash tests/article_analysis_deepseek/analyze-all.sh                 # turn1..turn3
bash tests/article_analysis_deepseek/analyze-all.sh turn1 turn2     # explicit subset
bash tests/article_analysis_deepseek/analyze-all.sh --no-run        # never invoke
                                                                    # s5.sh/s6.sh; skip
                                                                    # turns with missing data
```

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
(applied-alignments %-change, multi-D/R, **and** the OAEI reference validation
via `combine_oaei.py`).

## Building blocks (reusable)

- `combine_turns.py` — N per-turn aggregate CSVs → median/min/max wide CSV + pm table.
- `plot_turns.py`    — grouped bars with asymmetric min/max whiskers (same flags as `../analiza/plot_pct.py`, plus `--n-turns`).
- `combine_oaei.py`  — N per-turn `oaei_rejection.py` CSVs → median/min/max OAEI table + chart.
- `../analiza/extract_metric.py --outputs-root <dir>` — extraction pointed at
  one turn's `s5/` output tree.
