#!/bin/bash
# Disposable local HTTPS preview. Ctrl-C removes only resources created here.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
site="/Users/juyeong/developer/explorer/frontend/dist"
network=explorer-member-preview-test
pgname=explorer-member-preview-test-pg
appname=explorer-member-preview-test-app
image=explorer-member-http-test:temporary
source_commit=748b68a7
state=''
created_network=0
created_image=0
cleanup() {
  if [ "$created_network" = 1 ]; then
    docker stop "$appname" "$pgname" >/dev/null 2>&1 || true
    docker container rm "$appname" "$pgname" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
  fi
  if [ "$created_image" = 1 ]; then docker image rm "$image" >/dev/null 2>&1 || true; fi
  if [ -n "$state" ]; then python3 -c 'import shutil,sys;shutil.rmtree(sys.argv[1],ignore_errors=True)' "$state"; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
cd "$root"
[ -f "$site/index.html" ] || { printf '%s\n' '기존 회원 화면 빌드를 찾지 못했습니다.' >&2; exit 1; }
git cat-file -e "$source_commit^{commit}"
if docker network inspect "$network" >/dev/null 2>&1 || docker container inspect "$pgname" >/dev/null 2>&1 || docker container inspect "$appname" >/dev/null 2>&1 || docker image inspect "$image" >/dev/null 2>&1; then
  printf '%s\n' '같은 이름의 시험 리소스가 이미 있어 시작하지 않습니다.' >&2; exit 1
fi
if lsof -nP -iTCP:19446 -sTCP:LISTEN >/dev/null 2>&1; then
  printf '%s\n' 'localhost 19446 포트가 이미 사용 중입니다.' >&2; exit 1
fi
state="$(mktemp -d "$root/.member-preview.XXXXXX")"
chmod 700 "$state"
git archive "$source_commit" backend/security backend/models backend/routers/__init__.py backend/routers/member_portfolio.py backend/routers/auth.py | tar -x -C "$state"
openssl req -x509 -newkey rsa:2048 -keyout "$state/key.pem" -out "$state/cert.pem" -days 1 -nodes -subj /CN=localhost >/dev/null 2>&1
printf '%s\n' 'FROM explorer-refactor-test:psycopg-3.2.13' 'RUN pip install --no-cache-dir google-auth[requests]==2.62.2 cryptography==50.0.2' | docker build -q -t "$image" - >/dev/null
created_image=1
docker network create "$network" >/dev/null
created_network=1
docker run -d --name "$pgname" --network "$network" --network-alias pg -e POSTGRES_USER=fixture -e POSTGRES_PASSWORD=fixture -e POSTGRES_DB=fixture postgres:17-alpine >/dev/null
for i in {1..30}; do if docker exec "$pgname" pg_isready -U fixture -d fixture >/dev/null 2>&1; then break; fi; sleep 1; done
docker exec "$pgname" pg_isready -U fixture -d fixture >/dev/null
schema="refactor_fixture_$(python3 -c 'import uuid;print(uuid.uuid4().hex)')"
docker exec "$pgname" psql -U fixture -d fixture -c "CREATE SCHEMA $schema" >/dev/null
docker run -d --name "$appname" --network "$network" -p 127.0.0.1:19446:19446 \
  -v "$root/backend:/app/backend:ro" -v "$root/scripts:/app/scripts:ro" -v "$state/backend:/overlay:ro" \
  -v "$state:/preview-state" -v "$site:/site:ro" -w /tmp -e PYTHONPATH=/overlay:/app/backend \
  -e REFACTOR_POSTGRES_DSN='host=pg dbname=fixture user=fixture password=fixture' \
  -e REFACTOR_FIXTURE_SCHEMA="$schema" -e REFACTOR_TEST_DISPOSABLE=1 \
  "$image" python /app/scripts/refactor_member_preview.py >/dev/null
ready=0
for i in {1..30}; do
  if curl -ksS --max-time 2 https://localhost:19446/api/auth/session >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = 1 ] || { printf '%s\n' '미리보기 시작에 실패했습니다.' >&2; exit 1; }
printf '%s\n' '시험용 미리보기: https://localhost:19446/portfolio (합성 데이터, 자체 서명 인증서)' \
  "시험 세션은 $state/session.json 에만 저장되며 브라우저에 자동 적용되지 않습니다." \
  '종료하려면 Ctrl-C를 누르세요.'
while :; do sleep 10; done
