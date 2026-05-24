#!/bin/bash
# Docker Build Context Audit
# Checks the size of the Docker build context and flags prohibited paths.
# Usage: ./scripts/check-build-context.sh [--budget SIZE_MB]

set -euo pipefail

MAX_BUDGET="${1:-100}"
CONTEXT_DIR="${2:-.}"

PROHIBITED_PATTERNS=("__pycache__" ".git" "node_modules" "*.egg-info" "build/" "dist/" ".venv" "venv/" ".env" "*.pyc")

echo "=== Docker Build Context Audit ==="
echo "Context directory: $(cd "$CONTEXT_DIR" && pwd)"
echo "Max budget: ${MAX_BUDGET} MB"
echo ""

echo "--- Checking prohibited patterns ---"
FOUND_PROHIBITED=false
for pattern in "${PROHIBITED_PATTERNS[@]}"; do
  while IFS= read -r -d '' entry; do
    size=$(du -sm "$entry" 2>/dev/null | cut -f1)
    echo "  [PROHIBITED] $entry (${size}MB)"
    FOUND_PROHIBITED=true
  done < <(find "$CONTEXT_DIR" -name "$pattern" -not -path './.git/*' -print0 2>/dev/null || true)
done

echo ""
echo "--- Calculating context size ---"
CONTEXT_SIZE_MB=$(du -sm --exclude='.git' "$CONTEXT_DIR" 2>/dev/null | tail -1 | cut -f1)
echo "Estimated context size: ${CONTEXT_SIZE_MB}MB"

if [ "$FOUND_PROHIBITED" = true ]; then
  echo ""
  echo "[FAIL] Prohibited files/directories found in build context!"
fi

if [ "$CONTEXT_SIZE_MB" -gt "$MAX_BUDGET" ]; then
  echo ""
  echo "[FAIL] Context size ${CONTEXT_SIZE_MB}MB exceeds budget of ${MAX_BUDGET}MB!"
  exit 1
fi

if [ "$FOUND_PROHIBITED" = true ]; then
  exit 1
fi

echo ""
echo "[PASS] Build context audit passed (${CONTEXT_SIZE_MB}MB / ${MAX_BUDGET}MB budget)"
