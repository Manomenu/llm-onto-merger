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
