#!/bin/bash
set -e

DB_URL="postgresql://postgres@localhost/noharm"
DATABASE_REPO="/tmp/noharm-database"
COMPOSE="docker compose -f docker-compose.test.yml"

echo "Starting PostgreSQL container..."
$COMPOSE up -d

echo "Waiting for PostgreSQL to be ready..."
until $COMPOSE exec db pg_isready -U postgres -d noharm 2>/dev/null; do
  sleep 1
done
echo "PostgreSQL is ready."

echo "Cloning noharm-ai/database..."
if [ -d "$DATABASE_REPO" ]; then
  git -C "$DATABASE_REPO" pull --quiet
else
  git clone --quiet https://github.com/noharm-ai/database "$DATABASE_REPO"
fi

echo "Loading database..."
psql "$DB_URL" -f "$DATABASE_REPO/noharm-public.sql"   -v ON_ERROR_STOP=1
psql "$DB_URL" -f "$DATABASE_REPO/noharm-create.sql"   -v ON_ERROR_STOP=1
psql "$DB_URL" -f "$DATABASE_REPO/noharm-newuser.sql"  -v ON_ERROR_STOP=1
psql "$DB_URL" -f "$DATABASE_REPO/noharm-triggers.sql" -v ON_ERROR_STOP=1
psql "$DB_URL" -f "$DATABASE_REPO/noharm-insert.sql"   -v ON_ERROR_STOP=1

echo "Done. Run: make test"
