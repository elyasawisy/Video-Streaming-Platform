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

# Bring down any running containers first
docker-compose down -v

# Start services based on environment
if [[ "$ENV" == "prod" ]]; then
    # Production deployment
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
    
    # Run database migrations
    echo "Running database migrations..."
    python -m alembic upgrade head
    
    # Verify deployment with health checks
    echo "Verifying deployment..."
    python src/shared/healthcheck.py
else
    # Development deployment
    docker-compose -f docker-compose.yml -f docker-compose.override.yml up -d
    
    # Run database migrations
    echo "Running database migrations..."
    python -m alembic upgrade head
    
    # Verify deployment with health checks
    echo "Verifying deployment..."
    python src/shared/healthcheck.py
fi

# Final status check
if [ $? -eq 0 ]; then
    echo "Deployment successful!"
else
    echo "Deployment failed! Check logs for details."
    exit 1
fi