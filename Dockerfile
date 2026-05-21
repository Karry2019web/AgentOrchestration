# syntax=docker/dockerfile:1.7
# Multi-stage build: network access only in dependency stage.

# --- Dependency stage (may resolve external packages) ---
FROM python:3.11-slim AS dependency-resolver

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip uv \
    && python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && uv pip install --python /opt/venv/bin/python .

# --- Final stage (network disabled) ---
FROM python:3.11-slim AS final

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=dependency-resolver /opt/venv /opt/venv
COPY src ./src

# Verify package loads without network
RUN --network=none python -c "import importlib; importlib.import_module('src')"

EXPOSE 8000

CMD ["uvicorn", "src.api.server:create_app", "--host", "0.0.0.0", "--port", "8000"]
