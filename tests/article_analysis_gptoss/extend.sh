#!/usr/bin/env bash
# tests/article_analysis_gptoss/extend.sh — grow the gpt-oss repeated-runs
# analysis to N turns.
#
# For --number N: builds the turn list turn1..turnN, then delegates straight
# to analyze-all.sh with that explicit list.  analyze-all.sh ALREADY does
# everything the growth needs, per turn:
#   - resolves each dataset's s2 (swo-acm/confOf-ekaw/human-mouse/swo-union)
#     and s3 (cmt-edas/confOf-ekaw/human-mouse) data from the
#     tests/analiza-variance run tree
#     (tests/scenarios/outputs/<turn>/<name>-s2|-s3/ — already-computed
#     data is NEVER recomputed), then from
#     tests/article_scenarios/outputs/<turn>/
#   - only when NEITHER exists, runs tests/article_scenarios/s2.sh / s3.sh
#     --label turnK --only <dataset> to backfill it (slow — invokes the
#     default-backend LLM merger; each turn gets its own --run-nonce via
#     --label, so no two turns can share a prompt cache)
#   - then aggregates the N per-turn results into median [min; max] tables and
#     charts (bar = median, min and max marked on every bar) via the shared
#     ../article_analysis_deepseek/ helpers
#
# extend.sh's only job is turning a plain <number> into that turn list; no
# logic is duplicated from analyze-all.sh.
#
# Usage:
#   tests/article_analysis_gptoss/extend.sh 5   # ensure turn1..turn5 exist
#                                               # (reuse variance data, backfill
#                                               # the rest), then aggregate
#                                               # median/min/max
set -euo pipefail
cd "$(dirname "$0")"

N="${1:-}"
case "$N" in
  ''|*[!0-9]*)
    echo "Usage: extend.sh <number-of-turns>   (e.g. extend.sh 5 for turn1..turn5)" >&2
    exit 1
    ;;
esac
if [ "$N" -lt 1 ]; then
  echo "Error: <number> must be >= 1, got '$N'" >&2
  exit 1
fi

TURNS=()
for i in $(seq 1 "$N"); do
  TURNS+=("turn$i")
done

echo "=== extend.sh: growing gpt-oss repeated-runs analysis to n=$N turns (${TURNS[*]}) ==="
exec bash analyze-all.sh "${TURNS[@]}"
