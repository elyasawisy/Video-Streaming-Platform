#!/bin/bash

# Default to development environment
ENV=${1:-dev}

# Function to display usage
usage() {
    echo "Usage: $0 [dev|prod]"
    echo "  dev  - Deploy development environment (default)"
    echo "  prod - Deploy production environment"
    exit 1
}

# Validate input
if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
    usage
fi

echo "Deploying $ENV environment..."

# Determine script and project root so relative paths work regardless of CWD
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Project root: $PROJECT_ROOT"
cd "$PROJECT_ROOT" || { echo "Failed to cd to project root: $PROJECT_ROOT"; exit 1; }

# Track overall status
overall_status=0

echo "Bringing down any existing stacks (clean volumes)..."
docker-compose down -v || true

echo "Starting services for $ENV..."
if [[ "$ENV" == "prod" ]]; then
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d || overall_status=1
else
    docker-compose -f docker-compose.yml -f docker-compose.override.yml up -d || overall_status=1
fi

# Run database migrations if alembic is available (try to install if missing)
echo "Running database migrations..."
if python -c "import importlib,sys; importlib.import_module('alembic')" 2>/dev/null; then
    python -m alembic upgrade head || overall_status=1
else
    echo "alembic not found in current Python environment. Attempting to install from requirements.txt..."
    # Try to install only alembic (lighter and avoids heavy builds on host)
    echo "Attempting to install alembic locally (only) to run migrations..."
    python -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
    python -m pip install alembic==1.12.1 SQLAlchemy==2.0.23 >/dev/null 2>&1 || {
        echo "Failed to install alembic (or SQLAlchemy) in host environment."
        echo "Common on Windows when building binary deps. To run migrations, execute them inside a container instead:" >&2
        echo "  docker-compose run --rm upload_service_http2 python -m alembic upgrade head" >&2
        echo "or" >&2
        echo "  docker-compose run --rm streaming_service python -m alembic upgrade head" >&2
        overall_status=1
    }
    # If alembic is now available, run migrations
    if python -c "import importlib; importlib.import_module('alembic')" 2>/dev/null; then
        python -m alembic upgrade head || overall_status=1
    fi
fi

# Run health checks
echo "Verifying deployment with health checks..."
if python src/shared/healthcheck.py; then
    echo "Health checks passed"
else
    echo "Health checks failed" >&2
    overall_status=1
fi

if [ "$overall_status" -eq 0 ]; then
    echo "Deployment successful!"
    exit 0
else
    echo "Deployment failed! Check service logs for details." >&2
    exit 1
fi