#!/bin/bash
# Build Context Audit
# Enforces a size budget on the Docker build context and reports large entries.
#
# Usage: bash check-build-context.sh [context_dir] [budget_mb]
#   context_dir  - Directory to audit (default: project root)
#   budget_mb    - Max allowed context size in MB (default: 10)

set -euo pipefail

CONTEXT_DIR="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
BUDGET_MB="${2:-10}"
BUDGET_BYTES=$((BUDGET_MB * 1024 * 1024))

echo "--- Docker Build Context Audit ---"
echo "Context directory: $CONTEXT_DIR"
echo "Size budget: ${BUDGET_MB}MB"
echo ""

if [ ! -d "$CONTEXT_DIR" ]; then
    echo "ERROR: Context directory does not exist."
    exit 1
fi

report_size() {
    local path="$1"
    local label="$2"
    if command -v numfmt &>/dev/null; then
        du -sh "$path" 2>/dev/null | cut -f1
    else
        du -sh "$path" 2>/dev/null | cut -f1
    fi
}

echo "=== Top-level directory sizes ==="
du -sh "$CONTEXT_DIR"/*/ 2>/dev/null | sort -rh | head -20
echo ""

echo "=== Files larger than 1MB ==="
find "$CONTEXT_DIR" -maxdepth 4 -type f -size +1M \
    ! -path '*/.git/*' \
    ! -path '*/__pycache__/*' \
    ! -path '*/.venv/*' \
    ! -path '*/venv/*' \
    ! -path '*/node_modules/*' 2>/dev/null | while read -r f; do
    ls -lh "$f" 2>/dev/null | awk '{print $5, $NF}'
done | sort -rh | head -20
echo ""

PROHIBITED=(".venv" "venv" "env" "__pycache__" ".mypy_cache" ".pytest_cache" "node_modules" "dist" "build" ".uv")
echo "=== Prohibited generated directories ==="
found_prohibited=false
for dir in "${PROHIBITED[@]}"; do
    if [ -d "$CONTEXT_DIR/$dir" ]; then
        dir_size=$(du -sh "$CONTEXT_DIR/$dir" 2>/dev/null | cut -f1)
        echo "  WARNING: '$dir/' (${dir_size})"
        found_prohibited=true
    fi
done
if [ "$found_prohibited" = false ]; then
    echo "  None found."
fi
echo ""

total_size=$(du -sb "$CONTEXT_DIR" --exclude=.git 2>/dev/null | cut -f1)
echo "Context size (excl. .git): $(if command -v numfmt &>/dev/null; then numfmt --to=iec "$total_size"; else echo "$total_size bytes"; fi)"

if [ "$total_size" -gt "$BUDGET_BYTES" ]; then
    echo ""
    echo "FAIL: Context size exceeds ${BUDGET_MB}MB budget."
    echo "Large entries:"
    du -sh "$CONTEXT_DIR"/*/ 2>/dev/null | sort -rh | head -5
    exit 1
fi

echo ""
echo "PASS: Context within ${BUDGET_MB}MB budget."
