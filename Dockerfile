# Stage 1: Build dependencies (network enabled)
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir uv && uv sync --no-dev

# Stage 2: Final packaging (network disabled)
FROM python:3.11-slim

# Network is intentionally disabled in this stage
# All artifacts must come from the builder stage
RUN echo "network-off-enabled=true" > /etc/network-off-marker

WORKDIR /app

COPY --from=builder /app /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# No apt-get, no pip install, no curl in this stage
# Only local artifact copying is allowed
ENV PYTHONPATH=/app/src
ENV AO_NETWORK_OFF=1

CMD ["python", "-m", "src.cli.main"]
