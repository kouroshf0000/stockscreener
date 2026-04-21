.PHONY: up down dev api worker migrate test lint fmt typecheck clean web web-install

up:
	docker compose up -d

down:
	docker compose down

dev:
	uv run uvicorn backend.app.main:app --reload --port 8000 & cd frontend && npm run dev

api:
	uv run uvicorn backend.app.main:app --reload --port 8000

worker:
	uv run arq backend.workers.settings.WorkerSettings

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(m)"

test:
	uv run pytest

lint:
	uv run ruff check backend

fmt:
	uv run ruff format backend
	uv run ruff check --fix backend

typecheck:
	uv run mypy backend

clean:
	find backend -type d -name '__pycache__' -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache .uv-cache .coverage htmlcov dist build
	rm -rf exports/*.xlsx exports/*.pdf frontend/.next frontend/tsconfig.tsbuildinfo

web-install:
	cd frontend && npm install

web:
	cd frontend && npm run dev
