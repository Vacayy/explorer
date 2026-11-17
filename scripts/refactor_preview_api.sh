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
# Media and the vault are the cutover copies (MacBook freeze 2026-11-17, scripts/refactor_t0.sh files).
# Market analysis runs through the candidate's own broker (scripts/refactor_analysis_broker.sh): its RPC volume read-only
# and the private preview image's adapter package (copied, no download).
# A public-mode run adds its settings (REFACTOR_API_EXTRA_ENV: an env file) and a read-only mount (REFACTOR_API_EXTRA_MOUNT).
if [ -n "${REFACTOR_API_EXTRA_ENV:-}" ]; then cat "$REFACTOR_API_EXTRA_ENV" >> "$ENV_FILE"; fi
# Public mode keeps its login transactions on the tmpfs (as scripts/refactor_public_check.sh): created at each start.
set -- /app/scripts/refactor_single_path_preview.py
if [ -n "${REFACTOR_API_EXTRA_ENV:-}" ] && grep -q '^EXPLORER_LOGIN_DB=' "$REFACTOR_API_EXTRA_ENV"; then
  set -- -c "import os, runpy; from pathlib import Path; from security.login_transactions import LoginTransactions; \
LoginTransactions(Path(os.environ['EXPLORER_LOGIN_DB'])).initialize(); \
runpy.run_path('/app/scripts/refactor_single_path_preview.py', run_name='__main__')"
fi
IMAGE=${REFACTOR_API_IMAGE:-$(docker inspect "$C" --format '{{.Config.Image}}')}  # override to switch images
docker rm -f "$C" >/dev/null
docker run -d --name "$C" --restart unless-stopped --user 10001:10001 --network explorer-refactor-preview-private --memory "$MEMORY" --read-only \
  --tmpfs /tmp:rw,size=512m,uid=10001,gid=10001,mode=700 --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 \
  --cpus 2 -p 127.0.0.1:18012:8000 --label explorer.purpose=refactor-single-path --env-file "$ENV_FILE" \
  -v explorer-public-codex-auth:/provider-auth -v explorer-data-rehearsal_models:/models:ro \
  -v explorer-refactor-single-projection:/projection \
  -v explorer-refactor-history:/history:ro -e ANALYSIS_MARKET_HISTORY=/history/market_history.sqlite \
  -v explorer-refactor-media:/app/media:ro \
  -v explorer-refactor-analysis-store:/app/logs \
  -v explorer-analysis-rpc-candidate:/run/explorer-analysis:ro \
  -v "$DATA/review/refactor-single/explorer-analysis-package:/opt/analysis-adapter:ro" \
  -e ANALYSIS_RUNTIME=linux-broker -e ANALYSIS_BROKER_SOCKET=/run/explorer-analysis/socket \
  -e ANALYSIS_BROKER_TOKEN_FILE=/run/explorer-analysis/token -e PYTHONPATH=/app/backend:/app/scripts:/opt/analysis-adapter \
  -v explorer-refactor-claude-auth:/home/explorer/.claude \
  -v "$ROOT/backend:/app/backend:ro" -v "$ROOT/scripts:/app/scripts:ro" \
  -v "$HOME/developer/agent-whiteboard/runtime/explorer/codex-credential-gate.py:/control/codex-credential-gate.py:ro" \
  -v "$DATA/review/refactor-single/codex-gate:/control/codex-gate:ro" \
  -v "$DATA/runtime/vault/principles:/app/vault/principles:ro" \
  -v "$DATA/runtime/vault/notes/injected:/app/vault/notes/injected" \
  ${REFACTOR_API_EXTRA_MOUNT:+-v "$REFACTOR_API_EXTRA_MOUNT"} \
  -w /app --entrypoint python "$IMAGE" "$@"
docker network connect bridge "$C"
# A compute-worker pass stays up 90s after its last job with the code it started with; end it so the next job
# starts a pass with the code just deployed (the watcher itself only polls; an interrupted job stays queued).
docker exec "${REFACTOR_WORKER_CONTAINER:-explorer-refactor-single-compute-worker}" pkill -TERM -f 'pipeline\.postgres_compute_worker$' 2>/dev/null || true
