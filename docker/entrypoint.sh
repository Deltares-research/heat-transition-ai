#!/bin/bash
# Runs api (uvicorn, loopback-only) and webapp (nginx, public) as two
# processes in the same container/Azure Container App. If either dies, this
# script exits so the platform restarts the container; SIGTERM is forwarded
# to both so they shut down cleanly.
set -e

uvicorn apps.api:app --host 127.0.0.1 --port 8000 &
API_PID=$!

nginx -g 'daemon off;' &
NGINX_PID=$!

trap 'kill -TERM $API_PID $NGINX_PID 2>/dev/null' TERM INT

wait -n "$API_PID" "$NGINX_PID"
EXIT_CODE=$?

kill -TERM $API_PID $NGINX_PID 2>/dev/null
exit $EXIT_CODE
