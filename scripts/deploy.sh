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

# Check for stale PostgreSQL volume
echo ""
echo "=============================================="
echo "  IMPORTANT: If the database 'project21'"
echo "  does not exist (e.g., after adding POSTGRES_DB),"
echo "  you may need to clear the PostgreSQL volume."
echo ""
echo "  Option 1: Remove volume and recreate (WARNING: deletes all data!)"
echo "    docker compose down -v"
echo "    docker compose up -d --build"
echo ""
echo "  Option 2: Create database manually"
echo "    docker compose exec postgres createdb -U postgres project21"
echo ""
echo "  Option 3: Keep existing data (if DB already exists)"
echo "    docker compose down"
echo "    docker compose up -d --build"
echo "=============================================="
echo ""

# Build and restart (safe option — keeps volumes)
echo "Building and restarting containers..."
docker compose down
docker compose up -d --build

# Clean up old images
echo "Cleaning up old images..."
docker image prune -f

# Show status
echo "=== Deployment complete ==="
docker compose ps