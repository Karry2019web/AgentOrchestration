# ===== Builder Stage =====
FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source
COPY src/ src/

# ===== Runtime Stage =====
FROM python:3.11-slim

# Install runtime dependencies only — caches cleaned in same layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    /tmp/* \
    /var/tmp/*

# Copy only runtime artifacts from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /app/src/ /app/src/
COPY --from=builder /app/pyproject.toml /app/

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

EXPOSE 8000
CMD ["uvicorn", "src.api.server:create_app", "--host", "0.0.0.0", "--port", "8000"]
