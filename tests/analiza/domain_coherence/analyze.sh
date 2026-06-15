#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

DATASETS=(conference-s2 human-mouse-s2 acm-union-s2 swo-union-s2)

# 1. Raw per-metric CSVs
uv run python3 ../extract_metric.py \
    --metric applied_alignments \
    --datasets "${DATASETS[@]}" \
    --output applied_alignments.csv

uv run python3 ../extract_metric.py \
    --metric multi_domain_range_count \
    --datasets "${DATASETS[@]}" \
    --output multi_domain_range_count.csv

# 2. Normalized: Multi D/R per applied alignment (fair across methods)
uv run python3 ../normalize_metric.py \
    --numerator multi_domain_range_count.csv \
    --denominator applied_alignments.csv \
    --output mdr_per_alignment.csv

# 3. Aggregated %-change vs Applied Alignments baseline (Naive Union excluded)
uv run python3 ../aggregate_pct.py \
    --metric "Applied Alignments" applied_alignments.csv \
    --metric "Multiple D/R per Alignment" mdr_per_alignment.csv \
    --baseline "Applied Alignments" \
    --exclude-method "Naive Union" \
    --exclude-method "Applied Alignments" \
    --output domain_coherence_pct_change.csv

uv run python3 ../plot_pct.py \
    --input domain_coherence_pct_change.csv \
    --output domain_coherence_pct_change.jpg \
    --baseline-label "Applied Alignments"

echo
echo "=== applied_alignments.csv (raw) ==="
cat applied_alignments.csv | column -t -s,
echo
echo "=== multi_domain_range_count.csv (raw) ==="
cat multi_domain_range_count.csv | column -t -s,
echo
echo "=== mdr_per_alignment.csv (normalized) ==="
cat mdr_per_alignment.csv | column -t -s,
echo
echo "=== domain_coherence_pct_change.csv ==="
cat domain_coherence_pct_change.csv | column -t -s,
