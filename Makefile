VENV := .venv/bin

.PHONY: help dev infra up down migrate api web worker install lint

help:           ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

dev: infra api web  ## Start full dev environment

infra:          ## Start Docker infrastructure
	cd docker && docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

down:           ## Stop Docker infrastructure
	cd docker && docker compose -f docker-compose.yml -f docker-compose.dev.yml down

migrate:        ## Run database migrations
	cd apps/api && $(VENV)alembic upgrade head

api:            ## Start FastAPI dev server
	cd apps/api && $(VENV)uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

web:            ## Start React dev server
	cd apps/web && npm run dev

worker:         ## Start Celery worker
	cd workers && $(VENV)celery -A celery_app worker --loglevel=info

install:        ## Install all dependencies (uv + npm)
	uv venv --python 3.12
	uv pip install -e "apps/api[dev]" -e "workers[dev]"
	cd apps/web && npm install

lint:           ## Run linters (ruff + tsc)
	$(VENV)ruff check apps/api/app/ workers/
	cd apps/web && npx tsc --noEmit
