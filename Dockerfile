# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends     gcc     && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy only dependency manifest and source
COPY pyproject.toml .
COPY src/ src/

# Install project
RUN uv sync --no-dev

# ---------- Runtime stage ----------
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends     ca-certificates     && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /app /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

EXPOSE 8000

ENTRYPOINT ["uvicorn", "src.api.server:create_app", "--host", "0.0.0.0", "--port", "8000"]
