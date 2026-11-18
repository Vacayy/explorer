#!/bin/bash
# Candidate PG backup and restore check (pilot plan: daily backup during the pilot, a restore check before the cutover).
# The live candidate schema and every schema its views read (the base, the sector store) are dumped together (custom format, compressed) to a
# host directory with a SHA-256. Manual dumps are retained. Scheduled rotation publishes only a restored dump.
# `check` restores in an isolated container with an ephemeral Docker volume.
#   scripts/refactor_pg_backup.sh backup        # prints the dump path
#   scripts/refactor_pg_backup.sh check <dump>
#   scripts/refactor_pg_backup.sh rotate | check-current
set -euo pipefail
case "${1:-}" in
  rotate|check-current) exec python3 "$(dirname "$0")/refactor_pg_backup_rotation.py" "$1" ;;
esac
DB=explorer-refactor-preview-db
DIR=${REFACTOR_BACKUP_DIR:-$HOME/server-data/backups/refactor-pg}
SCHEMA_FILE=${REFACTOR_SCHEMA_CONFIG:-$HOME/server-data/review/refactor-single-schema.json}
MIN_VM_FREE_KB=2097152  # stop rather than fill the VM (2GB)
LIVE=$(docker exec explorer-refactor-single-path printenv REFACTOR_FIXTURE_SCHEMA)
BASE=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['base_schema'])" \
       "$SCHEMA_FILE")
# Every schema the live schema's views read (the base, the current sector store): a dump without one does not restore.
REFERENCED=$(docker exec "$DB" psql -U fixture -d fixture -Atc "SELECT DISTINCT m[1] FROM information_schema.views v,
  regexp_matches(v.view_definition, '(refactor_fixture_[0-9a-f]{32})\\.', 'g') m WHERE v.table_schema='$LIVE' AND m[1] <> '$LIVE'")
SCHEMAS=$(printf '%s\n' "$LIVE" "$BASE" $REFERENCED | sort -u)
for schema in $SCHEMAS; do
  [[ "$schema" =~ ^refactor_fixture_[0-9a-f]{32}$ ]] || { echo 'invalid backup schema'; exit 1; }
done
vm_free() { docker exec "$DB" df -k /var/lib/postgresql/data | awk 'NR==2{print $4}'; }
restore_space_kb() {
  schema_literals=$(printf "'%s'," $SCHEMAS | sed 's/,$//')
  live_bytes=$(docker exec "$DB" psql -U fixture -d fixture -Atc "SELECT COALESCE(sum(pg_total_relation_size(c.oid)),0)
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE c.relkind IN ('r','m') AND n.nspname IN ($schema_literals)")
  [[ "$live_bytes" =~ ^[0-9]+$ ]] || { echo 'could not determine VM space requirement' >&2; return 1; }
  required_kb=$((live_bytes / 1024 + 1048576))
  [ "$required_kb" -ge "$MIN_VM_FREE_KB" ] || required_kb=$MIN_VM_FREE_KB
  printf '%s\n' "$required_kb"
}
case "${1:-}" in
  backup)
    mkdir -p "$DIR" && chmod 700 "$DIR"
    # Dump only the selected schemas; table+index bytes plus 3 GiB are a conservative host budget.
    schema_literals=$(printf "'%s'," $SCHEMAS | sed 's/,$//')
    selected_bytes=$(docker exec "$DB" psql -U fixture -d fixture -Atc "SELECT COALESCE(sum(pg_total_relation_size(c.oid)),0)
      FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE c.relkind IN ('r','m') AND n.nspname IN ($schema_literals)")
    [[ "$selected_bytes" =~ ^[0-9]+$ ]] || { echo 'could not determine backup space requirement'; exit 1; }
    host_free_kb=$(df -Pk "$DIR" | awk 'NR==2 {print $4}')
    [[ "$host_free_kb" =~ ^[0-9]+$ ]] || { echo 'could not determine host free space'; exit 1; }
    [ "$host_free_kb" -gt "$((selected_bytes / 1024 + 3145728))" ] || { echo 'not enough host space for a backup'; exit 1; }
    [ "$(vm_free)" -gt "$((MIN_VM_FREE_KB + 262144))" ] || { echo 'not enough VM space for a backup'; exit 1; }
    # The supervisor holds the heavy-job lock and monitors host/VM space throughout streaming.
    exec python3 "$(dirname "$0")/refactor_pg_backup_stream.py"
    ;;
  check)
    dump=$2
    sha_file="$dump.sha256"
    expected=$(awk -v name="$(basename "$dump")" '$2==name && NF==2 {print $1}' "$sha_file")
    [[ "$expected" =~ ^[0-9a-f]{64}$ ]] &&
      [ "$expected" = "$(shasum -a 256 < "$dump" | awk '{print $1}')" ] ||
      { echo 'checksum mismatch'; exit 1; }
    # A compressed dump may expand to the whole database size; keep an additional GiB free.
    required_kb=$(restore_space_kb)
    [ "$(vm_free)" -gt "$required_kb" ] || { echo 'not enough VM space for a restore check'; exit 1; }
    image=$(docker inspect --format '{{.Image}}' "$DB")
    [[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]]
    scratch_dir=$(mktemp -d "${TMPDIR:-/tmp}/explorer-restore-check.XXXXXXXX")
    scratch="explorer-pg-restore-${scratch_dir##*.}"
    volume="$scratch-data"
    volume_created=0
    created=0
    cleanup() {
      if [ "$created" -eq 1 ]; then
        docker stop --time 30 "$scratch" >/dev/null 2>&1 || true
        docker rm "$scratch" >/dev/null || return 1
        created=0
      fi
      if [ "$volume_created" -eq 1 ]; then
        docker volume rm "$volume" >/dev/null || return 1
        volume_created=0
      fi
      rm -rf -- "$scratch_dir"
    }
    trap 'cleanup' EXIT
    trap 'exit 1' INT TERM
    docker volume create "$volume" >/dev/null
    volume_created=1
    POSTGRES_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    export POSTGRES_PASSWORD
    docker create --pull never --name "$scratch" --network none --log-driver none \
      --memory 2g --cpus 1 --env POSTGRES_PASSWORD --env POSTGRES_USER=fixture \
      --env POSTGRES_DB=fixture --mount "type=volume,src=$volume,dst=/var/lib/postgresql/data" \
      "$image" -c 'listen_addresses=' >/dev/null
    created=1
    unset POSTGRES_PASSWORD
    docker start "$scratch" >/dev/null
    ready=0
    for ((attempt=0; attempt<60; attempt++)); do
      if docker exec "$scratch" sh -c 'test "$(cat /proc/1/comm)" = postgres && pg_isready -U fixture -d fixture' >/dev/null 2>&1; then
        ready=1
        break
      fi
      sleep 1
    done
    [ "$ready" -eq 1 ] || { echo 'isolated restore database did not start'; exit 1; }
    docker exec -i "$scratch" pg_restore --list < "$dump" |
      awk '$4=="TABLE" && $5 ~ /^refactor_fixture_[0-9a-f]+$/ {print $5 "." $6}' |
      LC_ALL=C sort > "$scratch_dir/expected"
    [ -s "$scratch_dir/expected" ] || { echo 'restore check FAILED: no expected tables'; exit 1; }
    docker exec -i "$scratch" pg_restore -U fixture -d fixture --no-owner --exit-on-error < "$dump"
    docker exec "$scratch" psql -XAt -U fixture -d fixture -c \
      "SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname ~ '^refactor_fixture_[0-9a-f]{32}$'" |
      LC_ALL=C sort > "$scratch_dir/restored"
    cmp -s "$scratch_dir/expected" "$scratch_dir/restored" ||
      { echo 'restore check FAILED: the restored table inventory differs from the dump'; exit 1; }
    tables=$(wc -l < "$scratch_dir/restored" | tr -d ' ')
    cleanup
    trap - EXIT
    echo "restore check ok: $tables tables restored in isolation"
    ;;
  *) echo 'usage: refactor_pg_backup.sh backup | rotate | check <dump> | check-current' >&2; exit 2 ;;
esac
