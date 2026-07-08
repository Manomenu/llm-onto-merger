#!/usr/bin/env bash
# tests/article_analysis_deepseek/extend.sh — grow the combined
# gpt-oss + deepseek repeated-runs analysis to N turns.
#
# For --number N: builds the turn list turn1..turnN, then delegates straight
# to analyze-all.sh with that explicit list.  analyze-all.sh ALREADY does
# everything the growth needs, per turn:
#   - delegates the whole gpt-oss side to ../article_analysis_gptoss/
#     analyze-all.sh (which reuses the tests/analiza-variance data and
#     backfills the rest) — nothing gpt-oss is ever computed here
#   - checks turnK has complete deepseek s5 (AML-input) data for the datasets
#     swo-acm, confOf-ekaw, human-mouse, swo-union, and s6 (reference-input)
#     data for cmt-edas/confOf-ekaw/human-mouse
#   - for anything missing, runs tests/article_scenarios/s5.sh / s6.sh
#     --label turnK --only <dataset> to backfill it (slow — invokes the
#     OpenRouter deepseek-v4-flash merger; each turn gets its own --run-nonce
#     via --label, so no two turns can share a provider prompt cache)
#   - then aggregates the N per-turn results into median [min; max] tables and
#     charts (bar = median, min and max marked on every bar) where every
#     figure carries BOTH method columns: "Proposed: gpt-oss" and
#     "Proposed: deepseek-v4-flash"
#
# extend.sh's only job is turning a plain <number> into that turn list; no
# logic is duplicated from analyze-all.sh.
#
# Usage:
#   tests/article_analysis_deepseek/extend.sh 5   # ensure turn1..turn5 exist
#                                                 # (backfill any missing ones),
#                                                 # then aggregate median/min/max
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

echo "=== extend.sh: growing deepseek repeated-runs analysis to n=$N turns (${TURNS[*]}) ==="
exec bash analyze-all.sh "${TURNS[@]}"
