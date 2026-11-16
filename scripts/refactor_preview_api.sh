#!/bin/sh
# (Re)create the single-path preview API container with its fixed settings.
# The previous limit was 1468006400 bytes (1.37GB); REFACTOR_API_MEMORY reverts or changes it.
#   REFACTOR_API_MEMORY=2684354560 scripts/refactor_preview_api.sh
set -eu
C=${REFACTOR_API_CONTAINER:-explorer-refactor-single-path}
MEMORY=${REFACTOR_API_MEMORY:-2684354560}   # 2.5GB (PM decision): the hybrid index alone holds about 1.1GB
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DATA=${REFACTOR_SERVER_DATA:-$HOME/server-data}
ENV_FILE=$(mktemp)
trap 'rm -f "$ENV_FILE"' EXIT
chmod 600 "$ENV_FILE"
docker inspect "$C" | python3 -c "import sys,json;print('\n'.join(json.load(sys.stdin)[0]['Config']['Env']))" > "$ENV_FILE"
IMAGE=$(docker inspect "$C" --format '{{.Config.Image}}')
docker rm -f "$C" >/dev/null
docker run -d --name "$C" --user 10001:10001 --network explorer-refactor-preview-private --memory "$MEMORY" --read-only \
  --tmpfs /tmp:rw,size=512m,uid=10001,gid=10001,mode=700 --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 \
  --cpus 2 -p 127.0.0.1:18012:8000 --label explorer.purpose=refactor-single-path --env-file "$ENV_FILE" \
  -v explorer-public-codex-auth:/provider-auth -v explorer-data-rehearsal_models:/models:ro \
  -v explorer-refactor-single-projection:/projection \
  -v "$ROOT/backend:/app/backend:ro" -v "$ROOT/scripts:/app/scripts:ro" \
  -v "$HOME/developer/agent-whiteboard/runtime/explorer/codex-credential-gate.py:/control/codex-credential-gate.py:ro" \
  -v "$DATA/review/refactor-single/codex-gate:/control/codex-gate:ro" \
  -v "$DATA/incoming/explorer-rehearsal/vault/principles:/app/vault/principles:ro" \
  -v "$DATA/review/refactor-single/vault-candidate/notes-injected:/app/vault/notes/injected" \
  -w /app --entrypoint python "$IMAGE" /app/scripts/refactor_single_path_preview.py
docker network connect bridge "$C"
