#!/bin/bash
# The Mac mini collection scheduler as one container (restart: unless-stopped; architect #3 6938360203).
# Only this container gets the Docker socket, to start the one-shot job containers (scripts/refactor_collect_engine.py).
# The repository and the review state directory are mounted at their host paths, since bind sources are host paths.
# Not started before the cutover (the MacBook stays the collection source); the job target is the clone schema
# until the cutover changes it explicitly.
#   scripts/refactor_collect_scheduler.sh create <labels>   # create and start (restart unless-stopped)
#   scripts/refactor_collect_scheduler.sh once <label>      # one job from inside a throwaway scheduler container
#   scripts/refactor_collect_scheduler.sh remove
set -euo pipefail
NAME=explorer-refactor-collect-scheduler
IMAGE=explorer-refactor-test:psycopg-3.2.13-auth
ROOT=$(cd "$(dirname "$0")/.." && pwd)
STATE_DIR=$HOME/server-data/review/refactor-single
args=(--user 0 -v /var/run/docker.sock:/var/run/docker.sock -v "$ROOT:$ROOT:ro" -v "$STATE_DIR:$STATE_DIR"
      -e HOME="$HOME" -e HOST_HOME="$HOME" -e PYTHONDONTWRITEBYTECODE=1 -w "$ROOT" --memory=256m)
for key in NO_INTERNET COLLECT_JOB_SECONDS TRIAL_MAX_REQUESTS COLLECT_FEED_SOURCES COLLECT_MAX_NEW_DOCS COLLECT_MAX_MODEL_CALLS COLLECT_PROJECTION_WAIT; do
  [ -n "${!key:-}" ] && args+=(-e "$key=${!key}")
done
case "$1" in
  create)
    [ -n "${2:-}" ] || { echo 'name the jobs to enable'; exit 1; }
    docker run -d --name "$NAME" --restart unless-stopped "${args[@]}" --entrypoint python "$IMAGE" \
      "$ROOT/scripts/refactor_collect_scheduler.py" --run --enable "$2"
    ;;
  once)
    docker run --rm "${args[@]}" --entrypoint python "$IMAGE" "$ROOT/scripts/refactor_collect_scheduler.py" --run --enable "$2" --once "$2"
    ;;
  remove)
    docker rm -f "$NAME"
    ;;
esac
