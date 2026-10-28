.PHONY: help venv install install-ml migrate seed reset run test cov lint format check docker-up docker-down

PY ?= python
VENV = .venv
ifeq ($(OS),Windows_NT)
	BIN = $(VENV)/Scripts
else
	BIN = $(VENV)/bin
endif

help: ## Lista los comandos disponibles
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s
", $$1, $$2}'

venv: ## Crea el entorno virtual
	$(PY) -m venv $(VENV)

install: venv ## Instala dependencias de desarrollo
	$(BIN)/python -m pip install -r requirements-dev.txt

install-ml: ## Instala el clasificador opcional (scikit-learn)
	$(BIN)/python -m pip install -r requirements-ml.txt

migrate: ## Aplica las migraciones de Alembic
	$(BIN)/alembic upgrade head

seed: migrate ## Carga usuarios, políticas y ~200 tickets de demo
	$(BIN)/python -m app.seed --if-empty

reset: migrate ## Borra los datos y vuelve a cargar la demo
	$(BIN)/python -m app.seed --reset

run: ## Levanta la API en http://localhost:8000
	$(BIN)/uvicorn app.main:app --reload

test: ## Corre los tests
	$(BIN)/pytest

cov: ## Tests con reporte de cobertura
	$(BIN)/pytest --cov=app --cov-report=term-missing

lint: ## Ruff (lint + formato)
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format: ## Formatea el código
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

check: lint test ## Lint + tests (lo mismo que corre CI)

docker-up: ## Levanta API + PostgreSQL con datos de demo
	docker compose up --build

docker-down: ## Baja los contenedores y borra el volumen
	docker compose down -v
