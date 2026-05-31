#!/usr/bin/env bash
# Scenario #1: max-env-chars × alignment-tool grid (4 runs) for any dataset.
#
# Usage:
#   tests/scenarios/scenario_1.sh                # prompts for dataset name
#   tests/scenarios/scenario_1.sh conference     # uses tests/inputs/conference
#
# Runs (per dataset <name>):
#   <name>_10k_aml       max-env-chars=10000  alignment-tool=aml
#   <name>_20k_aml       max-env-chars=20000  alignment-tool=aml
#   <name>_10k_logmap    max-env-chars=10000  alignment-tool=logmap
#   <name>_20k_logmap    max-env-chars=20000  alignment-tool=logmap
#
# Inputs (same for all 4 runs):
#   tests/inputs/<name>/*.owl     (exactly 2 ontologies, sorted alphabetically)
#
# Outputs (all under tests/scenarios/outputs/ — gitignored):
#   tests/scenarios/outputs/<name>/<name>_<tag>/         merged_ontology.owl + insights + …
#   tests/scenarios/outputs/<name>/m_i_raport_<name>_1.html   combined report
#   tests/scenarios/outputs/<name>/m_i_raport_<name>_1.csv

set -euo pipefail
shopt -s nullglob

cd "$(dirname "$0")/../.."

DATASET="${1:-}"
if [ -z "$DATASET" ]; then
  echo "Available datasets:"
  for d in tests/inputs/*/; do
    echo "  - $(basename "$d")"
  done
  echo
  read -r -p "Dataset name: " DATASET
fi

INPUT_DIR="tests/inputs/$DATASET"
if [ ! -d "$INPUT_DIR" ]; then
  echo "Error: directory not found: $INPUT_DIR" >&2
  exit 1
fi

OWL_FILES=( "$INPUT_DIR"/*.owl )
if [ ${#OWL_FILES[@]} -ne 2 ]; then
  echo "Error: expected exactly 2 .owl files in $INPUT_DIR, found ${#OWL_FILES[@]}" >&2
  exit 1
fi
IFS=$'\n' OWL_SORTED=( $(printf '%s\n' "${OWL_FILES[@]}" | sort) )
unset IFS
BASE="${OWL_SORTED[0]}"
CANDIDATE="${OWL_SORTED[1]}"

SCENARIO_DIR="tests/scenarios/outputs/$DATASET"
OUT_BASE="$SCENARIO_DIR"
REPORT_HTML="$SCENARIO_DIR/m_i_raport_${DATASET}_1.html"
mkdir -p "$OUT_BASE"

# Tag, max-env-chars, alignment-tool
SCENARIOS=(
  "10k_aml     10000  aml"
  "20k_aml     20000  aml"
  "10k_logmap  10000  logmap"
  "20k_logmap  20000  logmap"
)

OUT_DIRS=()
for spec in "${SCENARIOS[@]}"; do
  read -r tag chars tool <<< "$spec"
  out="$OUT_BASE/${DATASET}_$tag"
  OUT_DIRS+=( "$out" )
  mkdir -p "$out"
  log_file="$out/run.log"
  echo
  echo "========================================"
  echo "  Scenario: ${DATASET}_$tag"
  echo "    base:           $BASE"
  echo "    candidate:      $CANDIDATE"
  echo "    alignment tool: $tool"
  echo "    max env chars:  $chars"
  echo "    output dir:     $out"
  echo "    log:            $log_file"
  echo "========================================"
  uv run llm-onto-merger \
    --base "$BASE" \
    --candidate "$CANDIDATE" \
    --alignment-tool "$tool" \
    --output "$out" \
    --max-env-chars "$chars" \
    >"$log_file" 2>&1
done

REPORT_LOG="$SCENARIO_DIR/m_i_raport_${DATASET}_1.log"
echo
echo "========================================"
echo "  Generating combined report"
echo "    inputs:  $INPUT_DIR"
echo "    output:  $REPORT_HTML"
echo "    log:     $REPORT_LOG"
echo "========================================"
uv run python tests/metrics_and_insights_raport.py \
  --inputs "$INPUT_DIR" \
  --output "$REPORT_HTML" \
  "${OUT_DIRS[@]}" \
  >"$REPORT_LOG" 2>&1

echo
echo "Done. Report: $REPORT_HTML"
