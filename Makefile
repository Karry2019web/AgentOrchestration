.PHONY: install test lint clean build run check-build-context docker-build docker-up docker-down

install:
	uv sync

test:
	pytest --cov=src tests/ -v

lint:
	flake8 src/ tests/
	mypy src/ --ignore-missing-imports

clean:
	rm -rf build/ dist/ *.egg-info/ __pycache__/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

build:
	uv build

run:
	uvicorn src.api.server:create_app --reload --host 0.0.0.0 --port 8000

check-build-context:
	chmod +x scripts/check-build-context.sh
	./scripts/check-build-context.sh --budget 100

docker-build: check-build-context
	docker compose -f infra/docker-compose.yml build

docker-up:
	docker compose -f infra/docker-compose.yml up -d

docker-down:
	docker compose -f infra/docker-compose.yml down
