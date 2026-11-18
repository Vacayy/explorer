#!/bin/sh
# One-shot container for heavy single-path preview work (collector runs, change
# comparison, publishing): never inside the preview API, whose memory is small.
#   scripts/refactor_run_collector_once.sh <python file under scripts/ or backend/> [args...]
set -eu
FILE=$1
shift
API=${REFACTOR_API_CONTAINER:-explorer-refactor-single-path}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BACKUP=${REFACTOR_BASE_BACKUP:-}
if [ -n "$BACKUP" ] && [ ! -d "$BACKUP" ]; then
  echo "REFACTOR_BASE_BACKUP must point to an existing directory" >&2
  exit 2
fi
ENV_FILE=$(mktemp)
trap 'rm -f "$ENV_FILE"' EXIT
chmod 600 "$ENV_FILE"
# The same database and schema as the preview API, without printing them.
docker inspect "$API" --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -E '^(REFACTOR_POSTGRES_DSN|REFACTOR_FIXTURE_SCHEMA|REFACTOR_TEST_DISPOSABLE|FASTEMBED_CACHE_PATH)=' > "$ENV_FILE"
IMAGE=$(docker inspect "$API" --format '{{.Config.Image}}')
NETWORK=$(docker inspect "$API" --format '{{.HostConfig.NetworkMode}}')
USER_ID=$(docker exec "$API" id -u):$(docker exec "$API" id -g)
set -- --user "$USER_ID" -v explorer-refactor-single-projection:/projection \
  -v "$ROOT/backend:/app/backend:ro" -v "$ROOT/scripts:/app/scripts:ro" -w /app/backend \
  -e PYTHONPATH=/app/backend -e PYTHONDONTWRITEBYTECODE=1 "$IMAGE" python "/app/$FILE" "$@"
if [ -n "$BACKUP" ]; then
  set -- -v "$BACKUP:/backup:ro" "$@"
fi
docker run --rm --memory=2g --network "$NETWORK" --env-file "$ENV_FILE" -e EXPLORER_ONESHOT=1 "$@"
