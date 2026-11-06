#!/usr/bin/env bash
# gates/diff-size.sh — the factory v0 builds small features: stop changes over MAX_LINES lines.
# Counts lines added plus removed by the agents (from FACTORY_BASE, new files included).
MAX_LINES=150
total="$(git diff --numstat "$FACTORY_BASE" -- . | awk '{ if ($1 != "-") n += $1 + $2 } END { print n + 0 }')"
if [ "$total" -gt "$MAX_LINES" ]; then
  echo "The change is $total lines (added + removed); this factory takes at most $MAX_LINES."
  echo "Split the ticket into smaller ones."
  exit 1
fi
echo "The change is $total lines, within $MAX_LINES."
