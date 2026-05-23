# syntax=docker/dockerfile:1
FROM python:3.11-slim AS runtime

# System setup: install only what's needed for the agent
ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1     DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies and clean apt cache in the same layer
RUN apt-get update &&     apt-get install -y --no-install-recommends         ca-certificates         &&     apt-get clean &&     rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/* /var/tmp/*

# Copy only the minimal runtime files
COPY pyproject.toml ./
COPY src/ ./src/

# Install Python dependencies and clean pip cache in the same layer
RUN pip install --no-cache-dir . &&     rm -rf /root/.cache/pip /tmp/pip-*

# Run as non-root user
RUN useradd --create-home --shell /bin/bash agent &&     chown -R agent:agent /app
USER agent

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3     CMD python -c "import src; exit(0)"

CMD ["uvicorn", "src.api.server:create_app", "--host", "0.0.0.0", "--port", "8000"]
