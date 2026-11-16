#!/bin/sh
# Start the single-path preview's compute worker beside the preview API: a separate container
# (3GB) for model-backed work too large for the API (reranker, chunk retrieval). A light watcher checks
# for queued jobs every second and runs each pass as a fresh process (pipeline.postgres_compute_worker);
# no model credentials are mounted. It also takes heavy publishing jobs (keyword back-linking on a private
# projection copy), so it is a one-shot-class container (EXPLORER_ONESHOT=1) like refactor_run_collector_once.sh.
#   scripts/refactor_compute_worker.sh            # (re)create the worker container
set -eu
API=${REFACTOR_API_CONTAINER:-explorer-refactor-single-path}
NAME=${REFACTOR_WORKER_CONTAINER:-explorer-refactor-single-compute-worker}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ENV_FILE=$(mktemp)
trap 'rm -f "$ENV_FILE"' EXIT
chmod 600 "$ENV_FILE"
docker inspect "$API" --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -E '^(REFACTOR_POSTGRES_DSN|REFACTOR_FIXTURE_SCHEMA|REFACTOR_TEST_DISPOSABLE|FASTEMBED_CACHE_PATH)=' > "$ENV_FILE"
IMAGE=$(docker inspect "$API" --format '{{.Config.Image}}')
NETWORK=$(docker inspect "$API" --format '{{.HostConfig.NetworkMode}}')
USER_ID=$(docker exec "$API" id -u):$(docker exec "$API" id -g)
MODELS=$(docker inspect "$API" --format '{{range .Mounts}}{{if eq .Destination "/models"}}{{.Name}}{{end}}{{end}}')
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart unless-stopped --memory=3g --network "$NETWORK" --env-file "$ENV_FILE" \
  --user "$USER_ID" -v explorer-refactor-single-projection:/projection -v "$MODELS:/models:ro" \
  -v "$ROOT/backend:/app/backend:ro" -w /app/backend -e PYTHONPATH=/app/backend -e PYTHONDONTWRITEBYTECODE=1 -e EXPLORER_ONESHOT=1 \
  "$IMAGE" python -m pipeline.postgres_compute_worker --watch
