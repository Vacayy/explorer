#!/bin/bash
# Candidate PG backup and restore check (pilot plan: daily backup during the pilot, a restore check before the cutover).
# The live candidate schema and every schema its views read (the base, the sector store) are dumped together (custom format, compressed) to a
# host directory with a SHA-256; all dumps are retained. `check` restores into a newly created uniquely named scratch
# database, compares table inventories, and drops only the scratch database created by that invocation.
#   scripts/refactor_pg_backup.sh backup        # prints the dump path
#   scripts/refactor_pg_backup.sh check <dump>
set -eu
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
case "$1" in
  backup)
    mkdir -p "$DIR" && chmod 700 "$DIR"
    # The host receives the dump; budget the entire database plus 3 GiB spare.
    # This intentionally overestimates the selected, compressed schemas.
    database_bytes=$(docker exec "$DB" psql -U fixture -d fixture -Atc 'SELECT pg_database_size(current_database())')
    [[ "$database_bytes" =~ ^[0-9]+$ ]] || { echo 'could not determine backup space requirement'; exit 1; }
    host_free_kb=$(df -Pk "$DIR" | awk 'NR==2 {print $4}')
    [[ "$host_free_kb" =~ ^[0-9]+$ ]] || { echo 'could not determine host free space'; exit 1; }
    [ "$host_free_kb" -gt "$((database_bytes / 1024 + 3145728))" ] || { echo 'not enough host space for a backup'; exit 1; }
    # A real dump temporarily consumed several GiB in the VM: refuse under
    # the same conservative budget used for a full restore.
    required_kb=$(restore_space_kb)
    [ "$(vm_free)" -gt "$required_kb" ] || { echo 'not enough VM space for a backup'; exit 1; }
    # Compress in a bounded disposable container using the already-local PG image.
    image=$(docker inspect "$DB" --format '{{.Image}}')
    [[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo 'invalid local PG image'; exit 1; }
    REFACTOR_POSTGRES_DSN=$(docker exec explorer-refactor-single-path printenv REFACTOR_POSTGRES_DSN)
    export REFACTOR_POSTGRES_DSN
    out="$DIR/$(date -u +%Y%m%dT%H%M%SZ)-candidate.dump"
    docker run --rm --pull=never --log-driver none --network explorer-refactor-preview-private --cpus 1 --memory 1g --pids-limit 100 \
      --read-only --cap-drop ALL --security-opt no-new-privileges -e REFACTOR_POSTGRES_DSN --entrypoint sh "$image" \
      -c 'exec pg_dump -d "$REFACTOR_POSTGRES_DSN" -Fc -Z 6 "$@"' sh $(printf -- '-n %s ' $SCHEMAS) > "$out.tmp"
    shasum -a 256 "$out.tmp" | sed "s|$out.tmp|$(basename "$out")|" > "$out.sha256"
    mv "$out.tmp" "$out" && chmod 600 "$out" "$out.sha256"
    echo "$out"
    ;;
  check)
    dump=$2
    (cd "$(dirname "$dump")" && shasum -a 256 -c "$(basename "$dump").sha256" >/dev/null) || { echo 'checksum mismatch'; exit 1; }
    # A compressed dump may expand to the whole database size; keep an additional GiB free.
    required_kb=$(restore_space_kb)
    [ "$(vm_free)" -gt "$required_kb" ] || { echo 'not enough VM space for a restore check'; exit 1; }
    scratch="explorer_restore_$(date -u +%Y%m%d%H%M%S)_$$"
    exists=$(docker exec "$DB" psql -U fixture -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname='$scratch'")
    [ -z "$exists" ] || { echo 'scratch database name already exists'; exit 1; }
    scratch_dir=$(mktemp -d "${TMPDIR:-/tmp}/explorer-restore-check.XXXXXXXX")
    created=0
    trap '[ "$created" -eq 0 ] || docker exec "$DB" dropdb -U fixture --if-exists "$scratch" >/dev/null 2>&1 || true; rm -rf "$scratch_dir"' EXIT
    docker exec "$DB" createdb -U fixture "$scratch"
    created=1
    docker exec -i "$DB" pg_restore -U fixture -d "$scratch" --no-owner --exit-on-error < "$dump"
    counts="SELECT n.nspname||'.'||c.relname, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='r' AND n.nspname IN ($(printf "'%s'," $SCHEMAS | sed 's/,$//')) ORDER BY 1"
    docker exec "$DB" psql -U fixture -d fixture -AtF'|' -c "$counts" > "$scratch_dir/live-counts"
    docker exec "$DB" psql -U fixture -d "$scratch" -AtF'|' -c "$counts" > "$scratch_dir/restored-counts"
    tables=$(wc -l < "$scratch_dir/live-counts" | tr -d ' ')
    # The restore itself is the test (it stops at the first error); the live service keeps writing after the dump, so
    # row counts are reported, not judged. Every live table must be there.
    if ! diff -q <(cut -d'|' -f1 "$scratch_dir/live-counts") <(cut -d'|' -f1 "$scratch_dir/restored-counts") >/dev/null; then
      echo "restore check FAILED: the restored table inventory differs from live"
      exit 1
    else
      moved=$(diff "$scratch_dir/live-counts" "$scratch_dir/restored-counts" | grep -c '^<' || true)
      echo "restore check ok: $tables tables restored; $moved with rows written since the dump"
    fi
    ;;
esac
