#!/bin/bash
# Runtime image inspection script
# Verifies that package manager caches are absent from the built image
set -euo pipefail

IMAGE_NAME="${1:-agent-orchestrator:runtime}"

echo "=== Checking runtime image: $IMAGE_NAME ==="

# Check for apt cache directories
for dir in /var/lib/apt/lists /var/cache/apt /var/cache/debconf /var/cache/ldconfig; do
    if docker run --rm "$IMAGE_NAME" test -d "$dir" 2>/dev/null; then
        echo "FAIL: Apt cache directory found: $dir"
        docker run --rm "$IMAGE_NAME" du -sh "$dir" 2>/dev/null || true
        exit 1
    fi
done

# Check for pip cache
if docker run --rm "$IMAGE_NAME" test -d /root/.cache/pip 2>/dev/null; then
    echo "FAIL: pip cache directory found"
    docker run --rm "$IMAGE_NAME" du -sh /root/.cache/pip
    exit 1
fi

# Check for temp files
for dir in /tmp /var/tmp; do
    contents=$(docker run --rm "$IMAGE_NAME" sh -c "ls -A $dir 2>/dev/null" | wc -l)
    if [ "$contents" -gt 0 ]; then
        echo "FAIL: Temp directory not empty: $dir"
        exit 1
    fi
done

# Get image size
IMAGE_SIZE=$(docker images --format "{{.Size}}" "$IMAGE_NAME" 2>/dev/null || echo "unknown")
echo "PASS: Runtime image is clean (size: $IMAGE_SIZE)"
echo ""
echo "=== Cache verification summary ==="
echo "  No package manager caches detected"
echo "  No stale temp files detected"
echo "  Image ready for production deployment"
