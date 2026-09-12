# Nexus task runner. `just` lists recipes. Recipes double as the documented
# way to do things: if a step is not here, it is not part of the process.

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set shell := ["bash", "-cu"]

cov_floor := "15"

default:
    @just --list

# One-time developer setup: Python 3.12 venv + lock, frontend deps, git hooks.
setup:
    uv sync --python 3.12
    npm --prefix frontend ci
    uv run pre-commit install

# Same, plus the local AI extras (torch CUDA wheels, ~2.5 GB).
setup-ai:
    uv sync --python 3.12 --extra ai

# Backend with reload on 127.0.0.1:8001.
dev-backend:
    uv run uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload

# Frontend dev server on :3000.
dev-frontend:
    npm --prefix frontend run dev

# The CI gate. Green here means green in CI.
check: lint typecheck test lint-frontend build-frontend

lint:
    uv run ruff check backend
    uv run ruff format --check backend

# Apply auto-fixes and formatting.
fix:
    uv run ruff check --fix backend
    uv run ruff format backend

typecheck:
    uv run mypy

test:
    uv run pytest --cov --cov-fail-under={{cov_floor}}

# Unit tests only: no network, no live services.
test-fast:
    uv run pytest -m "not slow and not network and not integration"

lint-frontend:
    npm --prefix frontend run lint
    npm --prefix frontend run typecheck

# Production build. The desktop app serves THIS output; source edits are
# invisible in the app until you run it.
build-frontend:
    npm --prefix frontend run build

# Environment doctor: ports, Ollama + model, DB, token, data sources.
doctor:
    uv run python -m backend.ops.doctor

# Remove build output and caches. Never touches data/ or .env.
clean:
    uv run python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('frontend/.next', 'frontend/out', '.pytest_cache', '.ruff_cache', '.mypy_cache', 'htmlcov')]; print('clean')"
