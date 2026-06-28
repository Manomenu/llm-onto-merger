#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

DATASETS=(conference-s2 human-mouse-s2 acm-union-s2 swo-union-s2)
# For D/R metrics we only consider datasets with rdfs:domain/rdfs:range
# present on BOTH input sides (otherwise the metric is trivially 0 or measures
# unrelated LLM-hallucination, see acm-union with 0 D/R on acm.owl side).
DR_DATASETS=(conference-s2 swo-union-s2)

# 1. Raw per-metric CSVs
uv run python3 ../extract_metric.py \
    --metric applied_alignments \
    --datasets "${DATASETS[@]}" \
    --output applied_alignments.csv

uv run python3 ../extract_metric.py \
    --metric multi_domain_range_count \
    --datasets "${DR_DATASETS[@]}" \
    --output multi_domain_range_count.csv

uv run python3 ../extract_metric.py \
    --metric multi_domain_range_change_per_alignment \
    --datasets "${DR_DATASETS[@]}" \
    --output multi_domain_range_change_per_alignment.csv

# 2. Applied Alignments — % change vs Applied Alignments baseline
uv run python3 ../aggregate_pct.py \
    --metric "Applied Alignments" applied_alignments.csv \
    --baseline "Applied Alignments" \
    --exclude-method "Naive Union" \
    --exclude-method "Applied Alignments" \
    --output applied_alignments_pct_change.csv

# 3. Multi D/R Change per Alignment — średnia surowych wartości metryki
uv run python3 ../aggregate_mean.py \
    --metric "Multi D/R Change per Alignment" multi_domain_range_change_per_alignment.csv \
    --exclude-method "Naive Union" \
    --exclude-method "Applied Alignments" \
    --output multi_dr_change_per_alignment_mean.csv

# 4. Merge into one CSV → one chart, two subplots side by side
uv run python3 ../merge_csvs.py \
    --input applied_alignments_pct_change.csv \
    --input multi_dr_change_per_alignment_mean.csv \
    --output domain_coherence_combined.csv

uv run python3 ../plot_pct.py \
    --input domain_coherence_combined.csv \
    --output domain_coherence_combined.jpg \
    --ylabel-for "Applied Alignments" "% change vs Applied Alignments" \
    --ylabel-for "Multi D/R Change per Alignment" "Multi D/R Δ per alignment" \
    --bar-fmt-for "Applied Alignments" "%+.1f%%" \
    --bar-fmt-for "Multi D/R Change per Alignment" "%+.2f"

echo
echo "=== applied_alignments.csv (raw) ==="
cat applied_alignments.csv | column -t -s,
echo
echo "=== multi_domain_range_change_per_alignment.csv (raw) ==="
cat multi_domain_range_change_per_alignment.csv | column -t -s,
echo
echo "=== domain_coherence_combined.csv ==="
cat domain_coherence_combined.csv | column -t -s,

# 5. OAEI reference-alignment validation (Domain Coherence vs ground truth)
#    Measure 1 (rejected correct, lower=better) ← scenario_3 (reference as input).
#    Measure 2 (accepted AML false-positives, lower=better) ← scenario_2 (AML input).
#    Self-provisioning: if a dataset's scenario_2/scenario_3 outputs are missing,
#    this script runs them itself (scenario_2 with --skip-all = cheap cache reuse;
#    scenario_3 = the real reference-input run).  You only run analyze.sh.
S2_TAG="aml_15k_p24"
S3_TAG="ref_15k_p24"
SCENARIOS_DIR="../../scenarios"
OAEI_ARGS=()
for ds in conference human-mouse; do
  REF="../../inputs/$ds/reference.rdf"
  INPUT_DIR="../../inputs/$ds"
  S2_DIR="../../scenarios/outputs/${ds}-s2/${ds}-s2_${S2_TAG}"
  S3_DIR="../../scenarios/outputs/${ds}-s3/${ds}-s3_${S3_TAG}"

  if [ ! -f "$REF" ]; then
    echo "  (skip '$ds': no reference.rdf)"
    continue
  fi

  # Auto-provision what's missing — no need to call the scenarios by hand.
  # scenario_2 (measure 2): reuse caches, only refresh report + sidecars (cheap).
  if [ ! -f "$S2_DIR/applied_stats.json" ]; then
    echo "  → '$ds': scenario_2 outputs missing — running scenario_2.sh --skip-all"
    "$SCENARIOS_DIR/scenario_2.sh" --skip-all "$ds" \
      || echo "  WARNING: scenario_2 --skip-all $ds failed (caches may be absent)"
  fi
  # scenario_3 (measure 1): reference-input run — the real compute cost (LLM merger).
  if [ ! -f "$S3_DIR/alignment_stats.json" ]; then
    echo "  → '$ds': scenario_3 outputs missing — running scenario_3.sh (reference run; may take a while)"
    "$SCENARIOS_DIR/scenario_3.sh" "$ds" \
      || echo "  WARNING: scenario_3 $ds failed"
  fi

  if [ -f "$S2_DIR/applied_stats.json" ]; then
    OAEI_ARGS+=( --dataset "$ds" "$REF" "$S2_DIR" "$S3_DIR" "$INPUT_DIR" )
  else
    echo "  (skip OAEI validation for '$ds': scenario_2 applied_stats.json still missing)"
  fi
done

if [ ${#OAEI_ARGS[@]} -gt 0 ]; then
  uv run python3 oaei_rejection.py \
    "${OAEI_ARGS[@]}" \
    --out-csv oaei_rejection.csv \
    --out-jpg oaei_rejection.jpg
  echo
  echo "=== oaei_rejection.csv ==="
  cat oaei_rejection.csv | column -t -s,
else
  echo "  OAEI validation skipped — no dataset with reference.rdf + scenario_2 applied_stats.json."
fi
