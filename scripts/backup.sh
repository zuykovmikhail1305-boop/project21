#!/bin/bash
set -e

BACKUP_DIR="./backups/$(date +%Y-%m-%d_%H-%M-%S)"
mkdir -p "$BACKUP_DIR"

echo "Backing up PostgreSQL..."
docker compose exec -T postgres pg_dump -U postgres project21 > "$BACKUP_DIR/postgres.sql"

echo "Backing up Qdrant..."
docker compose exec -T qdrant tar czf - /qdrant/storage > "$BACKUP_DIR/qdrant.tar.gz"

echo "Backup saved to $BACKUP_DIR"