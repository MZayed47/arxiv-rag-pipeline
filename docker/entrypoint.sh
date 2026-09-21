#!/bin/sh
set -e

# Wait for Postgres and apply any pending migrations before the process starts.
python -m app.db.migrate up

exec "$@"
