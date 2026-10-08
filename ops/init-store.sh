#!/usr/bin/env bash
# ops/init-store.sh -- create OUR store inside the engine's PostgreSQL instance.
#
# CLAUDE.md §3: our store is a separate database with its own role, and the
# backend never reads the engine's tables. This script makes that true:
#   - role  acme_app  (LOGIN, not superuser)
#   - db    acme      (owner acme_app, timescaledb extension)
#   - db    acme_test (scratch, for the Postgres store tests) -- with --test-db
#   - REVOKE CONNECT on the engine's database from PUBLIC, so acme_app
#     cannot even open a connection to it.
#
# Idempotent: safe to run again; it only (re)sets the role's password.
#
# Usage (Git Bash, repo root):
#   ACME_DB_PASSWORD='...' bash ops/init-store.sh [--test-db]

set -euo pipefail
cd "$(dirname "$0")/.."

: "${ACME_DB_PASSWORD:?set ACME_DB_PASSWORD (the password for role acme_app)}"

env_value() { grep "^$1=" engine/.env | cut -d= -f2- | tr -d '\r'; }
ADMIN=$(env_value POSTGRES_USER)
ENGINE_DB=$(env_value POSTGRES_DB)

dbs=(acme)
[ "${1:-}" = "--test-db" ] && dbs+=(acme_test)

psql_admin() {
  docker compose -f engine/docker-compose.yml exec -T db \
    psql -v ON_ERROR_STOP=1 -q -U "$ADMIN" "$@"
}

# Role. The password goes in through a psql variable on stdin, never argv.
psql_admin -d "$ENGINE_DB" -v pw="$ACME_DB_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE acme_app LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'acme_app')\gexec
ALTER ROLE acme_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'pw';
SQL

for db in "${dbs[@]}"; do
  psql_admin -d "$ENGINE_DB" <<SQL
SELECT 'CREATE DATABASE $db OWNER acme_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db')\gexec
SQL
  # The extension needs a superuser; tables are created later by the app as owner.
  psql_admin -d "$db" -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
done

# Close the door to the engine's database for everyone but its owner.
psql_admin -d "$ENGINE_DB" -c "REVOKE CONNECT ON DATABASE \"$ENGINE_DB\" FROM PUBLIC;"

echo "init-store: role acme_app, database(s) ${dbs[*]} ready; CONNECT on $ENGINE_DB revoked from PUBLIC"
