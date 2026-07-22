#!/bin/bash
set -e

echo "=== Project21 Deployment ==="

# Check if .env exists
if [ ! -f .env ]; then
    echo "ERROR: .env file not found!"
    echo "Copy .env.example to .env and fill in your values"
    exit 1
fi

# Pull latest changes
echo "Pulling latest changes..."
git pull origin main

# Build and restart
echo "Building and restarting containers..."
docker compose down
docker compose up -d --build

# Clean up old images
echo "Cleaning up old images..."
docker image prune -f

# Show status
echo "=== Deployment complete ==="
docker compose ps