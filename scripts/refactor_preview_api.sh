#!/bin/sh
# (Re)create the single-path preview API container with its fixed settings.
# Claude login lives only in the candidate volume explorer-refactor-claude-auth (CLAUDE_CONFIG_DIR); the user logs
# in once with `docker exec -it explorer-refactor-single-path claude` then /login. Removing the volume logs out.
# CLAUDE_BIN stays /bin/false (Claude calls blocked) until a real web research test is approved.
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
docker inspect "$C" | python3 -c "import sys,json;print('\n'.join(json.load(sys.stdin)[0]['Config']['Env']))" | grep -v '^EXPLORER_' > "$ENV_FILE"  # the candidate runs private here; drop a public test's settings
# A public-mode run adds its settings (REFACTOR_API_EXTRA_ENV: an env file) and a read-only mount (REFACTOR_API_EXTRA_MOUNT).
if [ -n "${REFACTOR_API_EXTRA_ENV:-}" ]; then cat "$REFACTOR_API_EXTRA_ENV" >> "$ENV_FILE"; fi
IMAGE=${REFACTOR_API_IMAGE:-$(docker inspect "$C" --format '{{.Config.Image}}')}  # override to switch images
docker rm -f "$C" >/dev/null
docker run -d --name "$C" --user 10001:10001 --network explorer-refactor-preview-private --memory "$MEMORY" --read-only \
  --tmpfs /tmp:rw,size=512m,uid=10001,gid=10001,mode=700 --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 \
  --cpus 2 -p 127.0.0.1:18012:8000 --label explorer.purpose=refactor-single-path --env-file "$ENV_FILE" \
  -v explorer-public-codex-auth:/provider-auth -v explorer-data-rehearsal_models:/models:ro \
  -v explorer-refactor-single-projection:/projection \
  -v explorer-data-rehearsal_media:/app/media:ro \
  -v explorer-refactor-claude-auth:/home/explorer/.claude \
  -v "$ROOT/backend:/app/backend:ro" -v "$ROOT/scripts:/app/scripts:ro" \
  -v "$HOME/developer/agent-whiteboard/runtime/explorer/codex-credential-gate.py:/control/codex-credential-gate.py:ro" \
  -v "$DATA/review/refactor-single/codex-gate:/control/codex-gate:ro" \
  -v "$DATA/incoming/explorer-rehearsal/vault/principles:/app/vault/principles:ro" \
  -v "$DATA/review/refactor-single/vault-candidate/notes-injected:/app/vault/notes/injected" \
  ${REFACTOR_API_EXTRA_MOUNT:+-v "$REFACTOR_API_EXTRA_MOUNT"} \
  -w /app --entrypoint python "$IMAGE" /app/scripts/refactor_single_path_preview.py
docker network connect bridge "$C"
# A compute-worker pass stays up 90s after its last job with the code it started with; end it so the next job
# starts a pass with the code just deployed (the watcher itself only polls; an interrupted job stays queued).
docker exec "${REFACTOR_WORKER_CONTAINER:-explorer-refactor-single-compute-worker}" pkill -TERM -f 'pipeline\.postgres_compute_worker$' 2>/dev/null || true
