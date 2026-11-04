#!/usr/bin/env bash
# 개편 워크트리(feature/ia-redesign)를 실사용 앱과 겹치지 않게 띄운다: 백엔드 8001 · 프론트 5175.
# DB는 워크트리의 backend/db 복사본, 텔레그램은 .env에서 끔(TELEGRAM_POLLING=0, 토큰 비움).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend" && "$ROOT/.venv/bin/python" -m uvicorn main:app --port 8001 &
BE=$!
trap 'kill $BE 2>/dev/null' EXIT
cd "$ROOT/frontend" && VITE_PORT=5175 VITE_API_BASE=http://localhost:8001 npx vite
