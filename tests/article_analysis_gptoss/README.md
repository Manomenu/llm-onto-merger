# article_analysis_gptoss — repeated-runs analysis (gpt-oss-20b)

The gpt-oss counterpart of `tests/article_analysis_deepseek/`: same dataset
lists, same dimensions, same **median [min; max]** statistic (bar height =
median, with the min and max of the N runs marked on every bar; tables show
`median [min; max]`), reusing that folder's `combine_turns.py` /
`plot_turns.py` / `combine_oaei.py` helpers.

## Data reuse — no recomputation of existing variance runs

Per turn × dataset, data is resolved in this order:

1. **`tests/scenarios/outputs/<turn>/<name>-s2|-s3/`** — the
   `tests/analiza-variance` run tree (produced by `scenario_2.sh` /
   `scenario_3.sh --label <turn>`). Display labels map onto the legacy
   dataset names: `cmt-edas → conference`, `swo-acm → acm-union` (both
   spellings are checked).
2. **`tests/article_scenarios/outputs/<turn>/s2|s3/<label>/`** — data this
   folder's own backfill produced earlier.
3. **Fallback**: `tests/article_scenarios/s2.sh` / `s3.sh --label <turn>
   --only <dataset>` is invoked (slow — default-backend LLM merger, same
   config as `scenario_2.sh`/`scenario_3.sh`: aml/reference input, 15000
   chars, 24 parallel). Suppress with `--no-run`. The fallback is granular
   twice over: it targets single datasets (`--only`), and it inspects the
   dataset dir in the article tree before running — if `merged_ontology.owl`
   already exists the LLM step is never re-paid (`--skip-mine`: baselines +
   report only), and if the baseline outputs are also complete only the
   report is regenerated (`--skip-all`).

Because the variance tree is checked first, `extend.sh 5` on a machine that
already ran `tests/analiza-variance/extend.sh 5` recomputes **nothing** — it
only re-aggregates into the median/min/max article format.

## Running

```bash
tests/article_analysis_gptoss/extend.sh 5      # turn1..turn5: reuse, backfill, aggregate
bash analyze-all.sh turn1 turn2                # explicit subset
bash analyze-all.sh --no-run                   # aggregate only; skip missing data
```

Dataset lists (display labels, same as article_analysis_deepseek):

- **s2, core dimensions:** cmt-edas, human-mouse, swo-acm, swo-union
- **s2, extra for OAEI:** confOf-ekaw
- **s3 (reference-input, OAEI):** cmt-edas, confOf-ekaw, human-mouse

## Outputs (per dimension, under `tests/article_analysis_gptoss/<dim>/`)

- `*_med.csv`  — wide `method,<metric>,<metric>_min,<metric>_max,…` (feeds the plotter)
- `*_pm.csv`   — thesis-ready `median [min; max]` table
- `*_med.jpg`  — grouped bar chart: bar = median, whiskers mark min and max
- `work/source/<turn>/<label>/` — unified per-turn view: each resolved
  `m_i_raport` CSV copied under its display-label name so extraction reads one
  consistent tree regardless of which source it came from
- `work/<turn>/…` (per dimension) — per-turn scratch; safe to delete

Dimensions mirrored from `tests/analiza-variance/`: accuracy (TPR),
conciseness (SUR, SR), structural_coherence (cycle count — table only),
knowledge_completeness (NCRC, NIRC, TCC), hierarchy_integration_quality (ARC,
depth, breadth %-change), understandability (CCR), domain_coherence
(applied-alignments %-change, multi-D/R, **and** the OAEI reference
validation).
