#!/bin/bash
# Candidate PG backup and restore check (pilot plan: daily backup during the pilot, a restore check before the cutover).
# The live candidate schema and every schema its views read (the base, the sector store) are dumped together (custom format, compressed) to a
# host directory with a SHA-256; the newest KEEP dumps stay. `check` restores a dump into a separate scratch database,
# compares row counts of every table with the live database and drops the scratch database: the live one is untouched.
#   scripts/refactor_pg_backup.sh backup        # prints the dump path
#   scripts/refactor_pg_backup.sh check <dump>
set -eu
DB=explorer-refactor-preview-db
DIR=${REFACTOR_BACKUP_DIR:-$HOME/server-data/backups/refactor-pg}
KEEP=${REFACTOR_BACKUP_KEEP:-3}
MIN_VM_FREE_KB=2097152  # stop rather than fill the VM (2GB)
LIVE=$(docker exec explorer-refactor-single-path printenv REFACTOR_FIXTURE_SCHEMA)
BASE=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['base_schema'])" \
       "$HOME/server-data/review/refactor-single-schema.json")
# Every schema the live schema's views read (the base, the current sector store): a dump without one does not restore.
REFERENCED=$(docker exec "$DB" psql -U fixture -d fixture -Atc "SELECT DISTINCT m[1] FROM information_schema.views v,
  regexp_matches(v.view_definition, '(refactor_fixture_[0-9a-f]{32})\\.', 'g') m WHERE v.table_schema='$LIVE' AND m[1] <> '$LIVE'")
SCHEMAS=$(printf '%s\n' "$LIVE" "$BASE" $REFERENCED | sort -u)
vm_free() { docker exec "$DB" df -k /var/lib/postgresql/data | awk 'NR==2{print $4}'; }
case "$1" in
  backup)
    mkdir -p "$DIR" && chmod 700 "$DIR"
    out="$DIR/$(date -u +%Y%m%dT%H%M%SZ)-candidate.dump"
    docker exec "$DB" pg_dump -U fixture -d fixture -Fc -Z 6 $(printf -- '-n %s ' $SCHEMAS) > "$out.tmp"
    shasum -a 256 "$out.tmp" | sed "s|$out.tmp|$(basename "$out")|" > "$out.sha256"
    mv "$out.tmp" "$out" && chmod 600 "$out" "$out.sha256"
    ls -1t "$DIR"/*-candidate.dump | tail -n +$((KEEP + 1)) | while read -r old; do rm -f "$old" "$old.sha256"; done
    echo "$out"
    ;;
  check)
    dump=$2
    (cd "$(dirname "$dump")" && shasum -a 256 -c "$(basename "$dump").sha256" >/dev/null) || { echo 'checksum mismatch'; exit 1; }
    [ "$(vm_free)" -gt "$MIN_VM_FREE_KB" ] || { echo 'not enough VM space for a restore check'; exit 1; }
    docker exec "$DB" dropdb -U fixture --if-exists restore_check
    docker exec "$DB" createdb -U fixture restore_check
    trap 'docker exec "$DB" dropdb -U fixture --if-exists restore_check' EXIT
    docker exec -i "$DB" pg_restore -U fixture -d restore_check --no-owner --exit-on-error < "$dump"
    counts="SELECT n.nspname||'.'||c.relname, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='r' AND n.nspname IN ($(printf "'%s'," $SCHEMAS | sed 's/,$//')) ORDER BY 1"
    docker exec "$DB" psql -U fixture -d fixture -AtF'|' -c "$counts" > "$DIR/.live-counts"
    docker exec "$DB" psql -U fixture -d restore_check -AtF'|' -c "$counts" > "$DIR/.restored-counts"
    tables=$(wc -l < "$DIR/.live-counts" | tr -d ' ')
    # The restore itself is the test (it stops at the first error); the live service keeps writing after the dump, so
    # row counts are reported, not judged. Every live table must be there.
    if ! diff -q <(cut -d'|' -f1 "$DIR/.live-counts") <(cut -d'|' -f1 "$DIR/.restored-counts") >/dev/null; then
      echo "restore check FAILED: the restored tables differ from the live ones:"
      diff <(cut -d'|' -f1 "$DIR/.live-counts") <(cut -d'|' -f1 "$DIR/.restored-counts") | head -20
    else
      moved=$(diff "$DIR/.live-counts" "$DIR/.restored-counts" | grep -c '^<' || true)
      echo "restore check ok: $tables tables restored; $moved with rows written since the dump"
    fi
    rm -f "$DIR/.live-counts" "$DIR/.restored-counts"
    ;;
esac
