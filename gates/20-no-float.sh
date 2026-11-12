#!/usr/bin/env bash
# AGENTS.md: money is Decimal, never float. Block any added line that builds a float in report/.
bad="$(git diff "$FACTORY_BASE" -- report/ | grep -E '^\+' | grep -vE '^\+\+\+' | grep -E '(^|[^A-Za-z_])float\(|[0-9]\.[0-9]+[eE]|: *float|-> *float' || true)"
if [ -n "$bad" ]; then
  echo "Money must be Decimal, never float. Found float in the change:"
  echo "$bad"
  exit 1
fi
echo "No float in the change."
