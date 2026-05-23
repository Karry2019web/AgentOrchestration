#!/usr/bin/env bash
# Check Docker build context for prohibited entries.
set -euo pipefail

CONTEXT_DIR="${1:-.}"

echo "[check-docker-context] Building context from: $CONTEXT_DIR"
echo "[check-docker-context] Testing .dockerignore rules..."

cd "$CONTEXT_DIR"

# List files that would be in context (respecting .dockerignore via tar)
tar_list=$(tar -cf - \
    --exclude-vcs \
    --exclude-vcs-ignores \
    -C "$CONTEXT_DIR" \
    . 2>/dev/null | tar -tf - | sort || echo "")

total_files=$(echo "$tar_list" | wc -l)
echo "[check-docker-context] Estimated context entries: $total_files"

PROHIBITED=(
    ".env"
    ".env.local"
    "__pycache__"
    ".venv"
    "venv"
    ".git/"
    "node_modules"
    ".DS_Store"
    "Thumbs.db"
    "scratch/"
    "debug/"
    "notebooks/"
)

violations=0
for pattern in "${PROHIBITED[@]}"; do
    pattern_escaped=$(echo "$pattern" | sed 's/\./\\\./g; s/\*/.*/g')
    matches=$(echo "$tar_list" | grep -iE "$pattern_escaped" || true)
    if [ -n "$matches" ]; then
        echo "[FAIL] Prohibited entry matches '$pattern':"
        echo "$matches" | sed 's/^/       /'
        violations=$((violations + 1))
    fi
done

if [ "$violations" -gt 0 ]; then
    echo ""
    echo "Failed - $violations prohibited pattern violation(s) found."
    exit 1
fi

echo ""
echo "Passed - no prohibited files in build context."
exit 0
