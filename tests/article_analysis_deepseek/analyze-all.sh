#!/usr/bin/env bash
# Combined two-backend repeated-runs analysis — every chart/table from
# tests/article_analysis_gptoss/ EXTENDED with one extra method column:
#   ... AROM, CoMerger, Boomer, Proposed: gpt-oss, Proposed: deepseek-v4-flash
# reporting MEDIAN with MIN/MAX whiskers (bar height = median; min and max
# are marked on every bar; tables show "median [min; max]").
#
# DATA REUSE: everything that article_analysis_gptoss already resolves is
# taken from it, never recomputed here.  Step 0 delegates to
# ../article_analysis_gptoss/analyze-all.sh (same turns, --no-run passed
# through), which resolves the gpt-oss data (tests/analiza-variance tree
# first, own backfill second) and leaves:
#   - per-turn report views under article_analysis_gptoss/work/source/<turn>/
#     → source of the baseline columns + "Proposed: gpt-oss"
#   - per-turn OAEI CSVs under article_analysis_gptoss/domain_coherence/work/
# This folder only ADDS the deepseek side: per turn it ensures the s5
# (AML-input) / s6 (reference-input) OpenRouter deepseek-v4-flash runs exist
# under tests/article_scenarios/outputs/<turn>/ (granular backfill via
# s5.sh/s6.sh --label <turn> --only <dataset>), then aggregates the combined
# columns.
#
# Dataset lists (display labels):
#   s5 / core (all non-OAEI dims):   confOf-ekaw human-mouse swo-acm swo-union
#   s6 (reference-input):            cmt-edas confOf-ekaw human-mouse
#   OAEI validation:                 confOf-ekaw human-mouse — cmt-edas is
#     measured ONLY under the reference input, and oaei_rejection.py
#     hard-requires each dataset's AML-input run (applied_stats.json) for the
#     accepted-AML-FP measure, so cmt-edas cannot appear in the OAEI charts.
#
# Usage:
#   bash analyze-all.sh                       # turns = turn1 turn2 turn3 (default)
#   bash analyze-all.sh turn1 turn2           # explicit turn list
#   bash analyze-all.sh --no-run              # never invoke any scenario script —
#                                              # turns with missing data are
#                                              # skipped (with a warning)
set -euo pipefail
cd "$(dirname "$0")"

NO_RUN=0
POSITIONAL=()
for arg in "$@"; do
  case "$arg" in
    --no-run) NO_RUN=1 ;;
    -*) echo "Unknown option: $arg" >&2; exit 1 ;;
    *) POSITIONAL+=("$arg") ;;
  esac
done

if [ ${#POSITIONAL[@]} -gt 0 ]; then
  TURNS=("${POSITIONAL[@]}")
else
  TURNS=(turn1 turn2 turn3)
fi

echo "=== combined gpt-oss + deepseek repeated-runs analysis over turns: ${TURNS[*]} (no-run=$NO_RUN) ==="

OUTROOT="../article_scenarios/outputs"   # deepseek s5/s6 runs
GPTOSS="../article_analysis_gptoss"      # gpt-oss side (resolved data + OAEI CSVs)

# ── Step 0: gpt-oss side — delegate entirely to article_analysis_gptoss ─────
echo
echo "--- [0] gpt-oss side (delegated to $GPTOSS/analyze-all.sh) ---"
if [ "$NO_RUN" = "1" ]; then
  bash "$GPTOSS/analyze-all.sh" --no-run "${TURNS[@]}"
else
  bash "$GPTOSS/analyze-all.sh" "${TURNS[@]}"
fi

# Display labels as produced by s5.sh / s6.sh.
CORE_DATASETS=(confOf-ekaw human-mouse swo-acm swo-union)
S6_DATASETS=(cmt-edas confOf-ekaw human-mouse)  # reference-input runs

DATASETS=("${CORE_DATASETS[@]}")
SUR_DATASETS=(confOf-ekaw swo-union)
DR_DATASETS=(confOf-ekaw swo-union)

# Output-dir tags as computed by s5.sh/s6.sh with default flags
# (limit 15000, parallel 1000, model deepseek/deepseek-v4-flash).
MODEL_TAG="deepseek_deepseek-v4-flash"
S5_TAG="aml_15000c_p1000_${MODEL_TAG}"
S6_TAG="ref_15000c_p1000_${MODEL_TAG}"

_s5_report_exists() {  # turn, display label
  [ -f "$OUTROOT/$1/s5/$2/m_i_raport_$2.csv" ]
}

_s6_report_exists() {  # turn, display label
  [ -f "$OUTROOT/$1/s6/$2/m_i_raport_$2.csv" ]
}

_gptoss_view_exists() {  # turn, display label — step 0 built this view
  [ -f "$GPTOSS/work/source/$1/$2/m_i_raport_$2.csv" ]
}

_input_for() {  # display label -> tests/inputs folder name
  case "$1" in
    cmt-edas) echo conference ;;
    *)        echo "$1" ;;
  esac
}

# ── Granular backfill: look INSIDE the dataset dir and run only what's missing.
# The report CSV is written last, so its absence says nothing about how far the
# run got — never re-pay the LLM cost when merged_ontology.owl already exists.
_baselines_complete() {  # run dir — all four baseline outputs copied in
  [ -f "$1/applied_alignments.owl" ] && [ -f "$1/boomer_ontology.owl" ] \
    && [ -f "$1/arom_ontology.owl" ] && [ -f "$1/comerger_ontology.owl" ]
}

_backfill() {  # scenario (s5|s6), turn, display label
  local scen="$1" T="$2" ds="$3" tag out
  case "$scen" in
    s5) tag="$S5_TAG" ;;
    s6) tag="$S6_TAG" ;;
  esac
  out="$OUTROOT/$T/$scen/$ds/${ds}_${tag}"
  if [ -f "$out/merged_ontology.owl" ]; then
    if _baselines_complete "$out"; then
      echo "  [$T] $scen/$ds: LLM output + baselines present, report missing — regenerating report only"
      "../article_scenarios/$scen.sh" --label "$T" --only "$ds" --skip-all
    else
      echo "  [$T] $scen/$ds: LLM output present, baselines incomplete — rerunning baselines + report (LLM skipped)"
      "../article_scenarios/$scen.sh" --label "$T" --only "$ds" --skip-mine
    fi
  else
    echo "  [$T] $scen/$ds: no LLM output — full run"
    "../article_scenarios/$scen.sh" --label "$T" --only "$ds"
  fi
}

# ── Step 1: deepseek side — per-turn existence check + auto-run backfill ────
echo
echo "--- [1] deepseek side (s5/s6 runs under $OUTROOT/<turn>/) ---"
for T in "${TURNS[@]}"; do
  for ds in "${CORE_DATASETS[@]}"; do
    if ! _s5_report_exists "$T" "$ds"; then
      if [ "$NO_RUN" = "1" ]; then
        echo "  [$T] WARNING: missing deepseek s5 report for '$ds' and --no-run is set — skipping where needed."
      else
        _backfill s5 "$T" "$ds"
      fi
    fi
  done
  for ds in "${S6_DATASETS[@]}"; do
    if ! _s6_report_exists "$T" "$ds"; then
      if [ "$NO_RUN" = "1" ]; then
        echo "  [$T] WARNING: missing deepseek s6 report for '$ds' and --no-run is set — skipping where needed."
      else
        _backfill s6 "$T" "$ds"
      fi
    fi
  done
done

# ── Active turns for the "core" dimensions: each needs BOTH sides complete
# for all 4 core datasets (gpt-oss view from step 0 + deepseek s5 report). ──
CORE_TURNS=()
for T in "${TURNS[@]}"; do
  ok=1
  for ds in "${CORE_DATASETS[@]}"; do
    { _gptoss_view_exists "$T" "$ds" && _s5_report_exists "$T" "$ds"; } || ok=0
  done
  if [ "$ok" = "1" ]; then
    CORE_TURNS+=("$T")
  else
    echo "  WARNING: turn '$T' is missing core (4-dataset) gpt-oss and/or deepseek data — excluded from all core-dimension aggregates."
  fi
done

if [ ${#CORE_TURNS[@]} -eq 0 ]; then
  echo "ERROR: no turn has complete core data on both sides — nothing to aggregate. Re-run without --no-run, or check $GPTOSS/work/source and $OUTROOT." >&2
  exit 1
fi
echo "Core turns (both sides complete): ${CORE_TURNS[*]}"
N_CORE=${#CORE_TURNS[@]}

# Shorthand: combined two-backend extraction for one turn.
_extract() {  # turn, metric, output csv, datasets...
  local T="$1" metric="$2" out="$3"
  shift 3
  uv run python3 extract_metric_combined.py \
      --gptoss-root "$GPTOSS/work/source/$T" \
      --deepseek-root "$OUTROOT/$T/s5" \
      --metric "$metric" --datasets "$@" \
      --output "$out"
}

# ═══════════════════════════════════════════════════════════════════════════
# accuracy — triple_preservation_ratio (aggregate_mean, exclude Naive Union)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- accuracy ---"
DIM=accuracy
mkdir -p "$DIM"
AGG_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" triple_preservation_ratio \
      "$DIM/work/$T/raw_triple_preservation_ratio.csv" "${DATASETS[@]}"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Triple Preservation Ratio" "$DIM/work/$T/raw_triple_preservation_ratio.csv" \
      --exclude-method "Naive Union" \
      --output "$DIM/work/$T/agg.csv"
  AGG_INPUTS+=(--input "$DIM/work/$T/agg.csv")
done
uv run python3 combine_turns.py "${AGG_INPUTS[@]}" \
    --output "$DIM/tpr_med.csv" --pm-output "$DIM/tpr_pm.csv"
uv run python3 plot_turns.py \
    --input "$DIM/tpr_med.csv" --output "$DIM/tpr_med.jpg" --n-turns "$N_CORE" \
    --ylabel-for "Triple Preservation Ratio" "Triple preservation ratio (avg over 4 datasets)" \
    --bar-fmt "%.2f"

# ═══════════════════════════════════════════════════════════════════════════
# conciseness — syntactic_uniqueness_ratio (2 ds) + structural_redundancy (4 ds)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- conciseness ---"
DIM=conciseness
mkdir -p "$DIM"
AGG_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" syntactic_uniqueness_ratio \
      "$DIM/work/$T/raw_syntactic_uniqueness_ratio.csv" "${SUR_DATASETS[@]}"
  _extract "$T" structural_redundancy \
      "$DIM/work/$T/raw_structural_redundancy.csv" "${DATASETS[@]}"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Syntactic Uniqueness Ratio" "$DIM/work/$T/raw_syntactic_uniqueness_ratio.csv" \
      --metric "Structural Redundancy" "$DIM/work/$T/raw_structural_redundancy.csv" \
      --output "$DIM/work/$T/agg.csv"
  AGG_INPUTS+=(--input "$DIM/work/$T/agg.csv")
done
uv run python3 combine_turns.py "${AGG_INPUTS[@]}" \
    --output "$DIM/conciseness_med.csv" --pm-output "$DIM/conciseness_pm.csv"
uv run python3 plot_turns.py \
    --input "$DIM/conciseness_med.csv" --output "$DIM/conciseness_med.jpg" --n-turns "$N_CORE" \
    --ylabel-for "Syntactic Uniqueness Ratio" "Syntactic uniqueness ratio (avg)" \
    --ylabel-for "Structural Redundancy" "Structural redundancy (avg)" \
    --bar-fmt "%.2f"

# ═══════════════════════════════════════════════════════════════════════════
# structural_coherence — cycle_count (aggregate_mean, all 4 ds).  Table only —
# mirrors tests/analiza-variance (the original has no chart for this metric).
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- structural_coherence ---"
DIM=structural_coherence
mkdir -p "$DIM"
AGG_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" cycle_count "$DIM/work/$T/raw_cycle_count.csv" "${DATASETS[@]}"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Cycle Count" "$DIM/work/$T/raw_cycle_count.csv" \
      --output "$DIM/work/$T/agg.csv"
  AGG_INPUTS+=(--input "$DIM/work/$T/agg.csv")
done
uv run python3 combine_turns.py "${AGG_INPUTS[@]}" \
    --output "$DIM/cycle_count_med.csv" --pm-output "$DIM/cycle_count_pm.csv"
echo "(no chart for structural_coherence — mirrors the original's table-only output)"

# ═══════════════════════════════════════════════════════════════════════════
# knowledge_completeness — NCRC+NIRC (aggregate_mean, exclude Naive Union,
# log-scale plot) and TCC (aggregate_mean, exclude Naive Union)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- knowledge_completeness ---"
DIM=knowledge_completeness
mkdir -p "$DIM"
NCRC_INPUTS=(); TCC_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" new_cross_onto_relations_count "$DIM/work/$T/raw_ncrc.csv" "${DATASETS[@]}"
  _extract "$T" new_intra_onto_relations_count "$DIM/work/$T/raw_nirc.csv" "${DATASETS[@]}"
  _extract "$T" triple_count_delta "$DIM/work/$T/raw_tcc.csv" "${DATASETS[@]}"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "NCRC" "$DIM/work/$T/raw_ncrc.csv" \
      --metric "NIRC" "$DIM/work/$T/raw_nirc.csv" \
      --exclude-method "Naive Union" \
      --output "$DIM/work/$T/agg_ncrc_nirc.csv"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Triples Count Change" "$DIM/work/$T/raw_tcc.csv" \
      --exclude-method "Naive Union" \
      --output "$DIM/work/$T/agg_tcc.csv"
  NCRC_INPUTS+=(--input "$DIM/work/$T/agg_ncrc_nirc.csv")
  TCC_INPUTS+=(--input "$DIM/work/$T/agg_tcc.csv")
done
uv run python3 combine_turns.py "${NCRC_INPUTS[@]}" \
    --output "$DIM/ncrc_nirc_med.csv" --pm-output "$DIM/ncrc_nirc_pm.csv"
uv run python3 plot_turns.py \
    --input "$DIM/ncrc_nirc_med.csv" --output "$DIM/ncrc_nirc_med.jpg" --n-turns "$N_CORE" \
    --ylabel-for "NCRC" "New cross-onto relations (avg, log)" \
    --ylabel-for "NIRC" "New intra-onto relations (avg, log)" \
    --log-for "NCRC" \
    --log-for "NIRC" \
    --bar-fmt "%.1f"
uv run python3 combine_turns.py "${TCC_INPUTS[@]}" \
    --output "$DIM/tcc_med.csv" --pm-output "$DIM/tcc_pm.csv"
uv run python3 plot_turns.py \
    --input "$DIM/tcc_med.csv" --output "$DIM/tcc_med.jpg" --n-turns "$N_CORE" \
    --ylabel-for "Triples Count Change" "Triples count change (avg)" \
    --bar-fmt "%+.0f"

# ═══════════════════════════════════════════════════════════════════════════
# hierarchy_integration_quality — average_depth/ARC/average_breadth/max_breadth
# (aggregate_pct, exclude dataset swo-union; max_depth dropped as in original)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- hierarchy_integration_quality ---"
DIM=hierarchy_integration_quality
mkdir -p "$DIM"
HIQ_METRICS=(ARC average_depth max_depth average_breadth max_breadth)
AGG_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  for METRIC in "${HIQ_METRICS[@]}"; do
    _extract "$T" "$METRIC" "$DIM/work/$T/raw_${METRIC}.csv" "${DATASETS[@]}"
  done
  uv run python3 ../analiza/aggregate_pct.py \
      --metric average_depth "$DIM/work/$T/raw_average_depth.csv" \
      --metric ARC "$DIM/work/$T/raw_ARC.csv" \
      --metric average_breadth "$DIM/work/$T/raw_average_breadth.csv" \
      --metric max_breadth "$DIM/work/$T/raw_max_breadth.csv" \
      --exclude swo-union \
      --output "$DIM/work/$T/agg.csv"
  AGG_INPUTS+=(--input "$DIM/work/$T/agg.csv")
done
uv run python3 combine_turns.py "${AGG_INPUTS[@]}" \
    --output "$DIM/hiq_pct_change_med.csv" --pm-output "$DIM/hiq_pct_change_pm.csv"
uv run python3 plot_turns.py \
    --input "$DIM/hiq_pct_change_med.csv" --output "$DIM/hiq_pct_change_med.jpg" --n-turns "$N_CORE"

# ═══════════════════════════════════════════════════════════════════════════
# understandability — comment_coverage_ratio (aggregate_mean, no excludes)
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- understandability ---"
DIM=understandability
mkdir -p "$DIM"
AGG_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" comment_coverage_ratio \
      "$DIM/work/$T/raw_comment_coverage_ratio.csv" "${DATASETS[@]}"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Comment Coverage Ratio" "$DIM/work/$T/raw_comment_coverage_ratio.csv" \
      --output "$DIM/work/$T/agg.csv"
  AGG_INPUTS+=(--input "$DIM/work/$T/agg.csv")
done
uv run python3 combine_turns.py "${AGG_INPUTS[@]}" \
    --output "$DIM/ccr_med.csv" --pm-output "$DIM/ccr_pm.csv"
uv run python3 plot_turns.py \
    --input "$DIM/ccr_med.csv" --output "$DIM/ccr_med.jpg" --n-turns "$N_CORE" \
    --ylabel-for "Comment Coverage Ratio" "Comment coverage ratio (avg over 4 datasets)" \
    --bar-fmt "%.2f"

# ═══════════════════════════════════════════════════════════════════════════
# domain_coherence (a) — non-OAEI: Applied Alignments %-change + Multi D/R mean
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- domain_coherence (non-OAEI) ---"
DIM=domain_coherence
mkdir -p "$DIM"
AA_INPUTS=(); MDR_INPUTS=()
for T in "${CORE_TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  _extract "$T" applied_alignments \
      "$DIM/work/$T/raw_applied_alignments.csv" "${DATASETS[@]}"
  _extract "$T" multi_domain_range_change_per_alignment \
      "$DIM/work/$T/raw_multi_dr.csv" "${DR_DATASETS[@]}"
  uv run python3 ../analiza/aggregate_pct.py \
      --metric "Applied Alignments" "$DIM/work/$T/raw_applied_alignments.csv" \
      --baseline "Applied Alignments" \
      --exclude-method "Naive Union" \
      --exclude-method "Applied Alignments" \
      --output "$DIM/work/$T/agg_applied_alignments.csv"
  uv run python3 ../analiza/aggregate_mean.py \
      --metric "Multi D/R Change per Alignment" "$DIM/work/$T/raw_multi_dr.csv" \
      --exclude-method "Naive Union" \
      --exclude-method "Applied Alignments" \
      --output "$DIM/work/$T/agg_multi_dr.csv"
  AA_INPUTS+=(--input "$DIM/work/$T/agg_applied_alignments.csv")
  MDR_INPUTS+=(--input "$DIM/work/$T/agg_multi_dr.csv")
done
uv run python3 combine_turns.py "${AA_INPUTS[@]}" \
    --output "$DIM/applied_alignments_med.csv" --pm-output "$DIM/applied_alignments_pm.csv"
uv run python3 combine_turns.py "${MDR_INPUTS[@]}" \
    --output "$DIM/multi_dr_med.csv" --pm-output "$DIM/multi_dr_pm.csv"
# Combined chart (mirrors the original's merge_csvs.py → one plot call).
uv run python3 ../analiza/merge_csvs.py \
    --input "$DIM/applied_alignments_med.csv" \
    --input "$DIM/multi_dr_med.csv" \
    --output "$DIM/domain_coherence_combined_med.csv"
uv run python3 plot_turns.py \
    --input "$DIM/domain_coherence_combined_med.csv" \
    --output "$DIM/domain_coherence_combined_med.jpg" --n-turns "$N_CORE" \
    --ylabel-for "Applied Alignments" "% change vs Applied Alignments" \
    --ylabel-for "Multi D/R Change per Alignment" "Multi D/R Δ per alignment" \
    --bar-fmt-for "Applied Alignments" "%+.1f%%" \
    --bar-fmt-for "Multi D/R Change per Alignment" "%+.2f"

# ═══════════════════════════════════════════════════════════════════════════
# domain_coherence (b) — OAEI reference-alignment validation (adjusted).
# The gpt-oss per-turn CSV comes straight from article_analysis_gptoss's step-0
# run; only the deepseek run of oaei_rejection.py happens here, and
# merge_oaei_runs.py grafts its "Proposed" row in as the extra method column.
# cmt-edas is excluded (reference-input only — no AML-input run exists).
# ═══════════════════════════════════════════════════════════════════════════
echo; echo "--- domain_coherence (OAEI validation) ---"
OAEI_DATASETS=(confOf-ekaw human-mouse)
mkdir -p "$DIM/work"
OAEI_PM_INPUTS=()
N_OAEI_TURNS=0
for T in "${TURNS[@]}"; do
  mkdir -p "$DIM/work/$T"
  GPTOSS_OAEI="$GPTOSS/domain_coherence/work/$T/oaei.csv"
  if [ ! -f "$GPTOSS_OAEI" ]; then
    echo "  [$T] no gpt-oss OAEI CSV ($GPTOSS_OAEI) — turn skipped for OAEI aggregation."
    continue
  fi
  OAEI_ARGS=()
  for ds in "${OAEI_DATASETS[@]}"; do
    INPUT_NAME="$(_input_for "$ds")"
    REF="../inputs/$INPUT_NAME/reference.rdf"
    INPUT_DIR="../inputs/$INPUT_NAME"
    S5_DIR="$OUTROOT/$T/s5/$ds/${ds}_${S5_TAG}"
    S6_DIR="$OUTROOT/$T/s6/$ds/${ds}_${S6_TAG}"
    if [ -f "$S5_DIR/applied_stats.json" ]; then
      OAEI_ARGS+=(--dataset "$ds" "$REF" "$S5_DIR" "$S6_DIR" "$INPUT_DIR")
    else
      echo "  [$T] skip deepseek OAEI dataset '$ds': $S5_DIR/applied_stats.json missing"
    fi
  done
  if [ ${#OAEI_ARGS[@]} -gt 0 ]; then
    uv run python3 ../analiza/domain_coherence/oaei_rejection.py \
        "${OAEI_ARGS[@]}" \
        --no-flag \
        --out-csv "$DIM/work/$T/oaei_deepseek.csv" --out-jpg "$DIM/work/$T/oaei_deepseek.jpg"
    uv run python3 merge_oaei_runs.py \
        --gptoss "$GPTOSS_OAEI" --deepseek "$DIM/work/$T/oaei_deepseek.csv" \
        --output "$DIM/work/$T/oaei.csv"
    OAEI_PM_INPUTS+=(--input "$DIM/work/$T/oaei.csv")
    N_OAEI_TURNS=$((N_OAEI_TURNS + 1))
  else
    echo "  [$T] no deepseek OAEI datasets available for this turn — skipped for OAEI aggregation."
  fi
done
if [ "$N_OAEI_TURNS" -gt 0 ]; then
  uv run python3 combine_oaei.py "${OAEI_PM_INPUTS[@]}" \
      --pm-output "$DIM/adjusted_oaei_rejection_pm.csv" \
      --jpg-output "$DIM/adjusted_oaei_rejection_med.jpg" \
      --n-turns "$N_OAEI_TURNS"
else
  echo "  OAEI aggregation skipped entirely — no turn had both sides' OAEI data."
fi

echo
echo "=== Done. Combined median/min/max outputs under tests/article_analysis_deepseek/<dim>/ ==="
