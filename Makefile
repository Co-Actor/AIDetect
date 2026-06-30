.PHONY: help install dev backend frontend test lint format redis-up redis-down db-up migrate

help:
	@echo "AIDetect — make targets:"
	@echo "  install     install backend (uv) and frontend (pnpm) deps"
	@echo "  dev         run backend + frontend (needs tmux/2 terminals)"
	@echo "  backend     run backend dev server (port 8010)"
	@echo "  frontend    run frontend dev server (port 9000)"
	@echo "  redis-up    start redis via docker compose"
	@echo "  redis-down  stop redis"
	@echo "  db-up       start postgres via docker compose"
	@echo "  migrate     apply DB migrations against DATABASE_URL"
	@echo "  test        run pytest"
	@echo "  lint        ruff + mypy + eslint"
	@echo "  format      ruff format + prettier"

install:
	cd backend && uv sync
	cd frontend && pnpm install

dev:
	@echo "Run 'make backend' and 'make frontend' in two terminals."

backend:
	cd backend && uv run uvicorn aidetect.main:app --reload --port 8010

frontend:
	cd frontend && pnpm dev

redis-up:
	docker compose up -d redis

redis-down:
	docker compose stop redis

db-up:
	docker compose up -d postgres

migrate:
	cd backend && uv run python -m aidetect.db.migrate

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run mypy src
	cd frontend && pnpm lint

format:
	cd backend && uv run ruff format .
	cd frontend && pnpm format
