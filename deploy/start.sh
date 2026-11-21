#!/bin/sh
# Container entrypoint: migrate, seed if empty, start mock services, run the API.
set -eu

cd /app/backend 2>/dev/null || cd "$(dirname "$0")/../backend"

PORT="${PORT:-8000}"

echo "[start] running migrations"
uv run --no-sync alembic upgrade head

echo "[start] seeding if the database is empty"
uv run --no-sync python -m app.seed --if-empty

# The mock services land later in the build; start them only when present.
if [ -f app/mocks/main.py ]; then
  echo "[start] starting mock services on 127.0.0.1:9001"
  uv run --no-sync uvicorn app.mocks.main:app --host 127.0.0.1 --port 9001 &
fi

# Trust X-Forwarded-* from the reverse proxy in front of us (Caddy, the platform router, a tunnel).
# The API port must be reachable only through that proxy. Set FORWARDED_ALLOW_IPS to the proxy's
# address to tighten this. It is passed through the environment, not as a "*" argument, because
# uvicorn's CLI expands "*" into file names when it runs natively on Windows.
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"

# ONE worker only. The in-process rate limiter and the jobs worker assume a single
# process; more workers would multiply limits and run duplicate background loops.
echo "[start] starting API on port ${PORT}"
exec uv run --no-sync uvicorn app.main:app \
  --host 0.0.0.0 --port "${PORT}" --workers 1 --proxy-headers
