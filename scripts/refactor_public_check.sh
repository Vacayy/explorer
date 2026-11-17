#!/bin/bash
# Public-mode boundary check through the pilot gateway (PM #3 6941244763), on a disposable clone only.
# A public-mode candidate API runs on a cloned schema behind a temporary pilot gateway (scripts/refactor_pilot_gateway.conf)
# on an isolated network; a synthetic operator (mapped to the owner's ledgers) and a synthetic member get sessions in the
# clone. The live candidate, the public service and the MacBook are not touched. Google settings are fake values.
#   scripts/refactor_public_check.sh up      # clone, users and sessions, API, gateway on 127.0.0.1:18015
#   scripts/refactor_public_check.sh down    # remove everything created here
# CHECK_SCHEMA=<schema> CHECK_PROJECTION=<host dir> use an existing disposable schema (a sync rehearsal's) and its
# projection instead of a fresh clone of the live one; `down` then leaves that schema in place.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DATA=$HOME/server-data/review/refactor-single
STATE=$DATA/public-check            # sessions and secrets of this check (700)
NET=explorer-pilot-check
API=explorer-refactor-public-check
GW=explorer-pilot-gateway-check
IMAGE=explorer-refactor-test:psycopg-3.2.13-auth
case "$1" in
  up)
    if [ -n "${CHECK_SCHEMA:-}" ]; then
      CLONE=$CHECK_SCHEMA
    else
      NO_INTERNET=1 "$ROOT/scripts/refactor_collect_trial.sh" setup >/dev/null
      CLONE=$(cat "$DATA/collect-trial-schema")
    fi
    mkdir -p "$STATE" && chmod 700 "$STATE"
    head -c 32 /dev/urandom > "$STATE/trial-secret" && chmod 600 "$STATE/trial-secret"
    docker network create "$NET" >/dev/null
    subnet=$(docker network inspect "$NET" --format '{{(index .IPAM.Config 0).Subnet}}')
    env_file=$(mktemp); chmod 600 "$env_file"
    docker inspect explorer-refactor-single-path --format '{{range .Config.Env}}{{println .}}{{end}}' \
      | grep -vE '^(REFACTOR_FIXTURE_SCHEMA|EXPLORER_|REFACTOR_MARKET_)' > "$env_file"
    cat >> "$env_file" <<EOF
REFACTOR_FIXTURE_SCHEMA=$CLONE
REFACTOR_TEST_DISPOSABLE=1
EXPLORER_ACCESS_MODE=public
EXPLORER_PUBLIC_ORIGIN=https://candidate.test
EXPLORER_AUTH_ENABLED=1
EXPLORER_GOOGLE_CLIENT_ID=fake-client.apps.googleusercontent.com
EXPLORER_GOOGLE_CLIENT_SECRET=fake-secret-for-check
EXPLORER_IDENTITY_DB=/tmp/identity.sqlite
EXPLORER_LOGIN_DB=/tmp/login.sqlite
EXPLORER_TRIAL_SECRET_FILE=/check/trial-secret
EXPLORER_TRIAL_NETWORK_DAY_LIMIT=3
EXPLORER_TRIAL_GLOBAL_DAY_LIMIT=20
EXPLORER_TRIAL_MAX_IN_FLIGHT=2
EXPLORER_TRIAL_TRUSTED_PROXIES=$subnet
EOF
    # The operator and a member, with sessions, in the clone (the session files never leave $STATE).
    docker run --rm -i --network explorer-refactor-preview-private --env-file "$env_file" --user 10001:10001 \
      -v "$ROOT/backend:/app/backend:ro" -v "$STATE:/check" -w /app/backend -e PYTHONPATH=/app/backend "$IMAGE" python - <<'PY'
import os, psycopg
from pipeline import postgres_identity_store, postgres_principals
from pipeline.postgres_identity_store import PostgreSQLIdentityStore
from security.login_flow import session_csrf
dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
factory = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}')
store = PostgreSQLIdentityStore(factory)
for name, role in (('operator', 'operator'), ('member', 'member')):
    user = store.get_or_create_google_user('accounts.google.com', f'synthetic-check-{name}')
    store.set_role(user.id, role)
    if name == 'operator':
        with factory() as conn:
            try:
                postgres_principals.remap_operator(conn, user.id)
            except ValueError:  # a reused schema (CHECK_SCHEMA): mapped by an earlier run
                pass
    token = store.issue_session(user.id, ttl_seconds=6 * 3600)
    path = f'/check/{name}.session'
    with open(path, 'w') as f:
        f.write(f'{token} {session_csrf(token)}')
    os.chmod(path, 0o600)
print('sessions ready')
PY
    docker create --name "$API" --network "$NET" --network-alias explorer-refactor-single-path --user 10001:10001 \
      --memory 2684354560 --read-only --tmpfs /tmp:rw,size=512m,uid=10001,gid=10001,mode=700 --cap-drop ALL \
      --security-opt no-new-privileges --env-file "$env_file" \
      -v "${CHECK_PROJECTION:-explorer-refactor-single-projection}":/projection:ro -v explorer-data-rehearsal_media:/app/media:ro \
      -v explorer-refactor-analysis-store:/app/logs:ro -v explorer-data-rehearsal_models:/models:ro \
      -v "$ROOT/backend:/app/backend:ro" -v "$ROOT/scripts:/app/scripts:ro" -v "$STATE/trial-secret:/check/trial-secret:ro" \
      -w /app --entrypoint python "$IMAGE" -c "from pathlib import Path; from security.login_transactions import LoginTransactions; \
LoginTransactions(Path('/tmp/login.sqlite')).initialize(); import runpy; \
runpy.run_path('/app/scripts/refactor_single_path_preview.py', run_name='__main__')" >/dev/null  # login state on tmpfs
    docker network connect explorer-refactor-preview-private "$API"
    rm -f "$env_file"
    docker start "$API" >/dev/null
    docker create --name "$GW" --network "$NET" -p 127.0.0.1:18015:8080 \
      -v "$ROOT/scripts/refactor_pilot_gateway.conf:/etc/nginx/nginx.conf:ro" \
      -v "$DATA/frontend-2fcab10b:/srv/single:ro" nginx:stable-alpine >/dev/null
    docker network connect bridge "$GW"
    docker start "$GW" >/dev/null
    echo "up: clone $CLONE, trusted $subnet, sessions in $STATE"
    ;;
  down)
    docker rm -f "$GW" "$API" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
    [ -n "${CHECK_SCHEMA:-}" ] || "$ROOT/scripts/refactor_collect_trial.sh" teardown
    rm -rf "$STATE"
    ;;
esac
