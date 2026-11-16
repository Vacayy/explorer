#!/bin/sh
# Start the single-path preview's projection builder beside the preview API: a separate
# container (2GB) that rebuilds the legacy projection and re-embeds changed documents as a
# fresh process each cycle, so the API never holds a build in memory.
#   scripts/refactor_projection_builder.sh        # (re)create the builder container
set -eu
API=${REFACTOR_API_CONTAINER:-explorer-refactor-single-path}
NAME=${REFACTOR_BUILDER_CONTAINER:-explorer-refactor-single-projection-builder}
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
docker run -d --name "$NAME" --restart unless-stopped --memory=2g --network "$NETWORK" --env-file "$ENV_FILE" \
  --user "$USER_ID" -v explorer-refactor-single-projection:/projection -v "$MODELS:/models:ro" \
  -v "$ROOT/backend:/app/backend:ro" -w /app/backend -e PYTHONPATH=/app/backend -e PYTHONDONTWRITEBYTECODE=1 \
  "$IMAGE" sh -c 'while true; do python -m pipeline.postgres_legacy_projection_builder /projection || echo "build failed"; sleep 10; done'
