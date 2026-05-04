.PHONY: help dev infra up down migrate api web worker install

help:           ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

dev: infra api web  ## Start full dev environment

infra:          ## Start Docker infrastructure
	cd docker && docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

down:           ## Stop Docker infrastructure
	cd docker && docker compose -f docker-compose.yml -f docker-compose.dev.yml down

migrate:        ## Run database migrations
	cd apps/api && alembic upgrade head

api:            ## Start FastAPI dev server
	cd apps/api && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

web:            ## Start React dev server
	cd apps/web && npm run dev

worker:         ## Start Celery worker
	cd workers && celery -A celery_app worker --loglevel=info

install:        ## Install all dependencies
	cd apps/api && pip install -e ".[dev]"
	cd apps/web && npm install
	cd packages/core && pip install -e .
