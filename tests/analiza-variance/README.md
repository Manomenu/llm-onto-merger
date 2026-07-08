# analiza-variance — repeated-runs variance analysis

Mirrors every chart/table in `tests/analiza/` but aggregates across **N repeated
runs ("turns")** and reports **mean ± sample-std** — error bars on charts,
`mean ± std` in tables. Purpose: answer the "single-seed anecdote" concern for
results produced by the non-deterministic LLM merger (temperature 0.7).

## How the variance is computed

The statistically meaningful unit is one *turn* = one full re-run of the merge
pipeline (one seed). For each turn we compute the **exact same aggregate** that
`tests/analiza/` produces (e.g. mean TPR over the 4 datasets), then take the
mean and sample standard deviation of those per-turn aggregates. Variance is
therefore the *seed variance* of each reported headline number.

## Generating the turns

Each turn is a labelled full run of the scenarios, written under
`tests/scenarios/outputs/<turn>/`:

```bash
# turn2, turn3, ... (turn1 can just be your existing single run — see below)
for T in turn2 turn3; do
  for DS in conference human-mouse acm-union swo-union confOf-ekaw; do
    tests/scenarios/scenario_2.sh --label "$T" "$DS"
  done
  for DS in conference human-mouse confOf-ekaw; do   # reference-input (OAEI) runs
    tests/scenarios/scenario_3.sh --label "$T" "$DS"
  done
done
```

`--label <turn>` only inserts a `<turn>/` folder above the usual `<dataset>-s2`
/ `-s3` output dir; the `-s2`/`-s3` suffixes and report filenames are unchanged,
so `analyze-all.sh` (and the plain `tests/analiza/` scripts) read them the same
way.

**turn1 = your existing single run.** The existing `tests/scenarios/outputs/<ds>-s2`
/ `-s3` dirs are one seed already. You can expose them as `turn1` with symlinks
(no recompute):

```bash
cd tests/scenarios/outputs && mkdir -p turn1
for d in *-s2 *-s3; do [ -e "turn1/$d" ] || ln -s "../$d" "turn1/$d"; done
```

(three seeds = turn1 existing + turn2 + turn3 generated → `n=3`, sample std.)

## Running the analysis

```bash
bash tests/analiza-variance/analyze-all.sh                 # turns = turn1 turn2 turn3
bash tests/analiza-variance/analyze-all.sh turn1 turn2     # explicit subset
bash tests/analiza-variance/analyze-all.sh --no-run        # never invoke scenarios;
                                                           # skip turns with missing data
```

Without `--no-run`, any turn missing its data triggers `scenario_2.sh` /
`scenario_3.sh --label <turn>` automatically (this invokes the LLM merger — slow
and costly). Use `--no-run` when you only want to (re)aggregate existing turns.

## Outputs (per dimension, under `tests/analiza-variance/<dim>/`)

- `*_var.csv`  — wide `method,<metric>,<metric>_std,…` (feeds the plotter)
- `*_pm.csv`   — thesis-ready `mean ± std` table
- `*_var.jpg`  — grouped bar chart with ±std error bars
- `work/<turn>/…` — per-turn scratch (raw + aggregate CSVs; safe to delete)

Dimensions mirrored: accuracy (TPR), conciseness (SUR, SR), structural_coherence
(cycle count — table only, matching the original's no-chart output),
knowledge_completeness (NCRC, NIRC, TCC), hierarchy_integration_quality (ARC,
depth, breadth %-change), understandability (CCR), domain_coherence (applied-
alignments %-change, multi-D/R, **and** the OAEI reference validation with
`combine_oaei.py`).

## Building blocks (reusable)

- `combine_turns.py`  — N per-turn aggregate CSVs → mean±std wide CSV + pm table.
- `plot_variance.py`  — grouped bars + error bars (same flags as `../analiza/plot_pct.py`, plus `--n-turns`).
- `combine_oaei.py`   — N per-turn `oaei_rejection.py` CSVs → mean±std OAEI table + chart.
- `../analiza/extract_metric.py --outputs-root <dir>` — the one change to the
  existing pipeline: lets extraction target a labelled run's output tree.

## Note on stale committed reference CSVs

The committed single-run CSVs in `tests/analiza/` are a snapshot; the live
`tests/scenarios/outputs/` tree can drift from them (observed: human-mouse NCRC
1240 committed vs 1266 live). The variance pipeline reads the **live** outputs
via the identical `extract_metric.py`, so its single-turn means equal the live
values, which may differ slightly from the committed `tests/analiza/` snapshot
(and from any thesis number taken from that snapshot). Regenerate the thesis
figures from the same run set you report.
