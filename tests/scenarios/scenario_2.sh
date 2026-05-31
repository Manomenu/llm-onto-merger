#!/usr/bin/env bash
# Scenario #2: single-config run for the human-mouse dataset.
#
# human-mouse is a big ontology pair (anatomy ontologies, thousands of classes)
# — a 2×2 grid like scenario_1 would burn through the LLM budget for marginal
# insight.  This scenario runs ONE configuration and produces a metrics +
# insights report comparing it against the naive applied_alignments baseline
# and the Boomer probabilistic resolver.
#
# Hardcoded config:
#   dataset:                    human-mouse
#   alignment tool:             aml
#   max env chars:              15000
#   parallel llm request count: 24
#
# Usage:
#   tests/scenarios/scenario_2.sh                # full run (LLM + Boomer + report)
#   tests/scenarios/scenario_2.sh --skip-mine    # reuse existing LLM output, rerun Boomer + report
#
# Outputs (all under tests/scenarios/outputs/human-mouse/ — gitignored):
#   human-mouse_aml_15k_p24/    LLM merger output + boomer_ontology.owl + insights
#   .boomer_aml/                Boomer's own output (cache)
#   m_i_raport_human-mouse_2.html / .csv / .log

set -euo pipefail
shopt -s nullglob

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck source=../../.env
  source "$REPO_ROOT/.env"
  set +a
fi

# ── Hardcoded config ────────────────────────────────────────────────────────
DATASET="human-mouse"
TOOL="aml"
MAX_CHARS=15000
PARALLEL=24
TAG="aml_15k_p24"

# ── Arg parsing ─────────────────────────────────────────────────────────────
SKIP_MINE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-mine) SKIP_MINE=1; shift ;;
    --help|-h)
      sed -n '2,/^$/p' "$0" | sed 's/^# *//' >&2
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

# ── Resolve inputs ──────────────────────────────────────────────────────────
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

# ── Output paths ────────────────────────────────────────────────────────────
SCENARIO_DIR="tests/scenarios/outputs/$DATASET"
OUT_DIR="$SCENARIO_DIR/${DATASET}_$TAG"
REPORT_HTML="$SCENARIO_DIR/m_i_raport_${DATASET}_2.html"
REPORT_LOG="$SCENARIO_DIR/m_i_raport_${DATASET}_2.log"
BOOMER_CACHE="$SCENARIO_DIR/.boomer_$TOOL"
AROM_CACHE="$SCENARIO_DIR/.arom"

mkdir -p "$OUT_DIR"

echo "========================================"
echo "  Scenario 2 / ${DATASET}_$TAG"
echo "    base:                       $BASE"
echo "    candidate:                  $CANDIDATE"
echo "    alignment tool:             $TOOL"
echo "    max env chars:              $MAX_CHARS"
echo "    parallel llm request count: $PARALLEL"
echo "    output dir:                 $OUT_DIR"
echo "    log:                        $OUT_DIR/run.log"
echo "    skip-mine:                  $([ "$SKIP_MINE" = "1" ] && echo yes || echo no)"
echo "========================================"

# ── LLM merger ──────────────────────────────────────────────────────────────
if [ "$SKIP_MINE" = "1" ]; then
  if [ -f "$OUT_DIR/merged_ontology.owl" ]; then
    echo "  --skip-mine: $OUT_DIR/merged_ontology.owl exists — skipping LLM merger"
  else
    echo "  WARNING: --skip-mine set but $OUT_DIR/merged_ontology.owl missing —" \
         "report will be incomplete"
  fi
else
  uv run llm-onto-merger \
    --base "$BASE" \
    --candidate "$CANDIDATE" \
    --alignment-tool "$TOOL" \
    --output "$OUT_DIR" \
    --max-env-chars "$MAX_CHARS" \
    --parallel-llm-request-count "$PARALLEL" \
    >"$OUT_DIR/run.log" 2>&1
fi

# ── Boomer (cached per tool) ────────────────────────────────────────────────
if [ ! -f "$BOOMER_CACHE/merged_ontology.owl" ]; then
  echo "  → running Boomer ($TOOL) → $BOOMER_CACHE"
  mkdir -p "$BOOMER_CACHE"
  ./thirdparty/boomer/boomer.sh "$BASE" "$CANDIDATE" "$BOOMER_CACHE" "$TOOL" \
    >"$BOOMER_CACHE/run.log" 2>&1
else
  echo "  → reusing cached Boomer ($TOOL) from $BOOMER_CACHE"
fi
if [ -f "$BOOMER_CACHE/merged_ontology.owl" ]; then
  cp "$BOOMER_CACHE/merged_ontology.owl" "$OUT_DIR/boomer_ontology.owl"
  if [ -f "$BOOMER_CACHE/boomer_stats.json" ]; then
    cp "$BOOMER_CACHE/boomer_stats.json" "$OUT_DIR/boomer_stats.json"
  fi
  echo "  → boomer_ontology.owl ← $BOOMER_CACHE/merged_ontology.owl"
fi

# ── AROM (cached) ──────────────────────────────────────────────────────────
if [ ! -f "$AROM_CACHE/arom_ontology.owl" ]; then
  echo "  → running AROM → $AROM_CACHE"
  mkdir -p "$AROM_CACHE"
  ./thirdparty/arom/arom.sh "$BASE" "$CANDIDATE" "$AROM_CACHE" \
    >"$AROM_CACHE/run.log" 2>&1
else
  echo "  → reusing cached AROM from $AROM_CACHE"
fi
if [ -f "$AROM_CACHE/arom_ontology.owl" ]; then
  cp "$AROM_CACHE/arom_ontology.owl" "$OUT_DIR/arom_ontology.owl"
  if [ -f "$AROM_CACHE/arom_stats.json" ]; then
    cp "$AROM_CACHE/arom_stats.json" "$OUT_DIR/arom_stats.json"
  fi
  echo "  → arom_ontology.owl ← $AROM_CACHE/arom_ontology.owl"
fi

# ── Report (single-scenario: metrics + insights + Boomer column) ────────────
echo
echo "========================================"
echo "  Generating report"
echo "    inputs: $INPUT_DIR"
echo "    output: $REPORT_HTML"
echo "    log:    $REPORT_LOG"
echo "========================================"
uv run python tests/metrics_and_insights_raport.py \
  --inputs "$INPUT_DIR" \
  --output "$REPORT_HTML" \
  "$OUT_DIR" \
  >"$REPORT_LOG" 2>&1

echo
echo "Done. Report: $REPORT_HTML"
