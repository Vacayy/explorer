#!/bin/bash
# The pilot cutover's Mac mini side (agent-whiteboard pilot-cutover-plan §2; rehearsed as R0-R7 on a clone).
# Each step is run by hand in order and reported; none starts the next. PAYLOAD is the verified, frozen MacBook
# snapshot (freeze.sh layout: backend/db, vault, media, logs, backend/local_sources), read-only from here on.
#   PAYLOAD=~/server-data/incoming/explorer-final-freeze-<T0> scripts/refactor_t0.sh <step>
# steps: verify | stop | dump | r2 | members | r3 | gates | files | rebuild | public
set -euo pipefail
export DOCKER_HOST=${DOCKER_HOST:-unix://$HOME/.colima/default/docker.sock}
cd "$(dirname "$0")/.."
eval "$(sed -n 10,40p scripts/refactor_collect_trial.sh)"; ROOT=$PWD
DATA=$HOME/server-data
BASE=$DATA/staging/refactor-preview-backup-20261116T050656Z   # the 11-14 base the live schema was built from
WORK=$DATA/review/refactor-single/t0; mkdir -p "$WORK"; chmod 700 "$WORK"
STATE=$WORK/schema; echo "$LIVE" > "$STATE"   # the live schema, on purpose: REFACTOR_T0=live below
SOURCE_DB=${PAYLOAD:-}/backend/db/stock_explorer.db
log() { tee -a "$WORK/t0.log"; }
live() {  # a one-shot container on the live schema with the frozen MacBook database at /rehearsal/source.db
  NO_INTERNET=1 JOB_MEMORY=${JOB_MEMORY:-3584m} container -e REFACTOR_T0=live -v "$SOURCE_DB:/rehearsal/source.db:ro" \
    -v "$BASE:/base:ro" "$@"
}
case "$1" in
  verify)
    python3 "$HOME/developer/agent-whiteboard/runtime/explorer/verify-transfer.py" "$PAYLOAD" --image explorer-rehearsal:local | log ;;
  stop)   # no writer but this script until the switch
    docker stop explorer-refactor-single-projection-builder explorer-refactor-single-compute-worker | log ;;
  dump)
    scripts/refactor_pg_backup.sh backup 2>&1 | tail -3 | log ;;
  r2)
    live "$IMAGE" python /app/scripts/refactor_rehearsal_r2.py 2>&1 | tail -1 | log ;;
  members)  # the public service's users (a SQLite backup taken now), then the operator's ledgers to its real principal
    docker exec explorer-public-image-candidate python3 -c "
import sqlite3; s=sqlite3.connect('file:/state/identity.sqlite?mode=ro',uri=True); d=sqlite3.connect('/tmp/identity-t0.sqlite'); s.backup(d); d.close()"
    docker exec explorer-public-image-candidate cat /tmp/identity-t0.sqlite > "$WORK/identity.sqlite"; chmod 600 "$WORK/identity.sqlite"
    docker exec explorer-public-image-candidate rm -f /tmp/identity-t0.sqlite
    # Member records in the public main DB (counts only): the import below assumes there are none.
    docker exec explorer-public-image-candidate python3 -c "
import sqlite3; c=sqlite3.connect('file:/app/backend/db/stock_explorer.db?mode=ro',uri=True)
n=[c.execute(q).fetchone()[0] for q in (\"SELECT count(*) FROM stock_groups WHERE kind='portfolio' AND owner_id IS NOT NULL\",
   'SELECT count(*) FROM member_portfolio_principles','SELECT count(*) FROM member_saved_documents')]
print('public member rows', n); raise SystemExit(1 if any(n) else 0)" | log
    live -v "$WORK/identity.sqlite:/copy/identity.sqlite:ro" "$IMAGE" python /app/scripts/refactor_t0_members.py 2>&1 | tail -3 | log ;;
  r3)
    live "$IMAGE" python /app/scripts/refactor_rehearsal_r3.py --apply 2>&1 | tail -1 | log ;;
  gates)
    live "$IMAGE" python /app/scripts/refactor_id_gate.py --gate 2>&1 | tail -1 | log
    ;;
  files)   # media to the candidate's own volume (the old one stays for the rollback), logs stores, history, vault, adapter
    docker volume create explorer-refactor-media >/dev/null
    docker run --rm --network none -v "$PAYLOAD:/p:ro" -v explorer-refactor-media:/media -v explorer-refactor-analysis-store:/logs \
      -v explorer-refactor-history:/history --entrypoint sh "$IMAGE" -c '
        set -e
        cp -a /p/media/. /media/
        for d in /p/logs/*/; do n=$(basename "$d"); case $n in weekly-harness|market-analysis-smoke) continue;; esac
          mkdir -p "/logs/$n"; cp -a "$d." "/logs/$n/"; done
        [ -f /history/market_history.sqlite ] && mv /history/market_history.sqlite /history/market_history.prev.sqlite
        cp /p/backend/db/market_history.sqlite /history/market_history.sqlite
        echo media $(find /media -type f | wc -l) logs $(find /logs -type f | wc -l) history $(stat -c %s /history/market_history.sqlite)' | log
    mkdir -p "$DATA/runtime" && chmod 700 "$DATA/runtime"
    rsync -a --delete "$PAYLOAD/vault/" "$DATA/runtime/vault/" && echo "vault $(find "$DATA/runtime/vault" -type f | wc -l)" | log
    mkdir -p "$DATA/review/refactor-single/local-sources"
    rsync -a --delete "$PAYLOAD/backend/local_sources/" "$DATA/review/refactor-single/local-sources/local_sources/" ;;
  rebuild)  # the post-freeze rebuild with 3.5GiB, then back to 2GiB (pilot plan R5)
    docker update --memory 3584m --memory-swap 3584m explorer-refactor-single-projection-builder >/dev/null
    docker start explorer-refactor-single-projection-builder >/dev/null
    echo "builder started with 3.5GiB; set it back to 2g after the first build" | log ;;
  *) echo "unknown step $1" >&2; exit 2 ;;
esac
