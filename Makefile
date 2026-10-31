# Shortcuts for common tasks. Run `make help` to see them all.

BACKEND_PORT ?= 8001
FRONTEND_PORT ?= 5173

VENV := backend/.venv
PY := $(VENV)/bin/python

.PHONY: help install install-backend install-frontend migrate dev backend frontend test test-live lint build clean docker-build docker-up docker-down docker-logs

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36mmake %-18s\033[0m %s\n", $$1, $$2}'

install: install-backend install-frontend ## Install all dependencies (backend + frontend)

install-backend: ## Set up Python virtual environment and install requirements
	test -d $(VENV) || python3 -m virtualenv $(VENV) || python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r backend/requirements.txt
	test -f backend/.env || cp backend/.env.example backend/.env

install-frontend: ## Install frontend npm packages
	cd frontend && npm install

migrate: ## Apply Django database migrations
	cd backend && .venv/bin/python manage.py migrate

dev: ## Run both backend and frontend servers concurrently
	$(MAKE) -j2 backend frontend

backend: ## Start Django development server
	cd backend && .venv/bin/python manage.py runserver $(BACKEND_PORT)

frontend: ## Start React (Vite) development server
	cd frontend && BACKEND_URL=http://localhost:$(BACKEND_PORT) npx vite --port $(FRONTEND_PORT)

test: ## Run backend unit and integration tests (pytest)
	cd backend && .venv/bin/pytest

test-live: ## Run tests against live third-party APIs (requires internet)
	cd backend && RUN_LIVE_TESTS=1 .venv/bin/pytest -k live

lint: ## Lint frontend source code (oxlint)
	cd frontend && npm run lint

build: ## Build frontend production bundle
	cd frontend && npm run build

clean: ## Remove build artifacts and caches
	rm -rf frontend/dist backend/staticfiles backend/.pytest_cache
	find backend -name __pycache__ -type d -prune -exec rm -rf {} +

docker-build: ## Build Docker images
	docker compose build

docker-up: ## Start production containers (Gunicorn + Vite preview)
	docker compose up -d

docker-down: ## Stop and remove Docker containers
	docker compose down

docker-logs: ## Follow live logs from running containers
	docker compose logs -f
