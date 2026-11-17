#!/bin/bash
# Isolated collection trial runner (PM #3 6937405301): a disposable clone schema and trial volume, one job per
# one-shot container with outbound internet (the preview API keeps its network block). No Telegram/YouTube/bot
# credentials are given; Claude is blocked so tagging uses the Codex fallback.
#   scripts/refactor_collect_trial.sh setup                 # clone schema + trial volume + work copy
#   scripts/refactor_collect_trial.sh run <job> [feed_url]  # blog needs a feed URL
#   scripts/refactor_collect_trial.sh job <label>           # one scheduled job (refactor_collect_job.py)
#   scripts/refactor_collect_trial.sh teardown              # drop clone schema and trial volume
# NO_INTERNET=1 keeps the one-shot container off the outbound network (path checks without source requests).
set -euo pipefail
API=explorer-refactor-single-path
ROOT=$(cd "$(dirname "$0")/.." && pwd)
STATE=$HOME/server-data/review/refactor-single/collect-trial-schema
IMAGE=explorer-refactor-test:psycopg-3.2.13-auth
VOLUME=explorer-refactor-collect-trial
LIVE=$(docker exec "$API" printenv REFACTOR_FIXTURE_SCHEMA)
USER_ID=$(docker exec "$API" id -u):$(docker exec "$API" id -g)

container() {  # extra docker args..., then the command
  local env_file; env_file=$(mktemp); chmod 600 "$env_file"
  docker inspect "$API" --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -E '^(REFACTOR_POSTGRES_DSN|REFACTOR_TEST_DISPOSABLE|FASTEMBED_CACHE_PATH|CODEX_BIN|CODEX_HOME|CODEX_FALLBACK_MODEL|HOME|ENRICH_ENGINE)=' > "$env_file"
  printf 'REFACTOR_FIXTURE_SCHEMA=%s\nTRIAL_LIVE_SCHEMA=%s\nCLAUDE_BIN=/bin/false\nEXPLORER_ONESHOT=1\n' "$(cat "$STATE")" "$LIVE" >> "$env_file"
  for key in TRIAL_MAX_REQUESTS TRIAL_HOST_CAPS COLLECT_FEED_SOURCES COLLECT_MAX_NEW_DOCS COLLECT_MAX_MODEL_CALLS COLLECT_PROJECTION_WAIT HISTORY_DESTINATION; do   # caps and limits from the caller
    [ -n "${!key:-}" ] && printf '%s=%s\n' "$key" "${!key}" >> "$env_file"
  done
  local id; id=$(docker create ${CONTAINER_NAME:+--name "$CONTAINER_NAME"} --memory="${JOB_MEMORY:-2g}" --network explorer-refactor-preview-private --env-file "$env_file" --user "$USER_ID" \
    -v "$ROOT/backend:/app/backend:ro" -v "$ROOT/scripts:/app/scripts:ro" -v explorer-refactor-single-projection:/projection:"${PROJECTION_MODE:-ro}" \
    -v "$VOLUME:/trial" -v explorer-public-codex-auth:/provider-auth -v explorer-data-rehearsal_models:/models:ro \
    -v "$HOME/server-data/review/refactor-single/codex-gate:/control/codex-gate:ro" \
    -v "$HOME/developer/agent-whiteboard/runtime/explorer/codex-credential-gate.py:/control/codex-credential-gate.py:ro" \
    -w /app/backend -e PYTHONPATH=/app/backend -e PYTHONDONTWRITEBYTECODE=1 "$@")
  rm -f "$env_file"
  [ "${NO_INTERNET:-0}" = 1 ] || docker network connect bridge "$id"   # outbound internet for this one-shot run only
  local rc=0; docker start -a "$id" || rc=$?
  docker rm -f "$id" >/dev/null
  return $rc
}

case "$1" in
  setup)
    NEW=refactor_fixture_$(openssl rand -hex 16)
    docker exec explorer-refactor-preview-db sh -c "pg_dump -U fixture -d fixture -n $LIVE --no-owner --no-privileges | sed 's/$LIVE/$NEW/g' | psql -q -v ON_ERROR_STOP=1 -U fixture -d fixture"
    echo "$NEW" > "$STATE"
    docker volume create "$VOLUME" >/dev/null
    docker run --rm --user 0 -v "$VOLUME:/trial" --entrypoint chown "$IMAGE" "$USER_ID" /trial   # local image only
    container "$IMAGE" python /app/scripts/refactor_collect_trial.py prepare
    ;;
  run)
    if [ -n "${3:-}" ]; then
      container -e "TRIAL_FEED=$3" "$IMAGE" python /app/scripts/refactor_collect_trial.py run "$2"
    else
      container "$IMAGE" python /app/scripts/refactor_collect_trial.py run "$2"
    fi
    ;;
  job)   # one scheduled job (scripts/refactor_collect_scheduler.py --run), recorded in collect_runs
    container "$IMAGE" python /app/scripts/refactor_collect_job.py "$2"
    ;;
  catchup)   # which of the enabled jobs (comma-separated) to catch up now, from collect_runs
    container "$IMAGE" python /app/scripts/refactor_collect_job.py --catchup "$2"
    ;;
  stopped)   # record a run the scheduler stopped at its time limit
    NO_INTERNET=1 container "$IMAGE" python /app/scripts/refactor_collect_job.py --stopped "$2" "$3" "$4"
    ;;
  teardown)
    NEW=$(cat "$STATE")
    [ "$NEW" != "$LIVE" ] && docker exec explorer-refactor-preview-db psql -q -U fixture -d fixture -c "DROP SCHEMA $NEW CASCADE" 2>&1 | tail -1
    docker volume rm "$VOLUME" >/dev/null && rm -f "$STATE" && echo "torn down $NEW"
    ;;
esac
