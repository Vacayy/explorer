---
name: api-contract
description: 백엔드 API를 새로 만들거나 응답 모양을 바꿀 때, 프론트에서 API를 새로 부르거나 타입을 바꿀 때, 화면에 "서버 응답 형식이 올바르지 않습니다"·"일부 데이터를 불러오지 못했습니다"가 뜰 때 쓴다. 서버 응답 모델 ↔ 프론트 계약 ↔ 실제 응답을 맞추는 절차와 원인 찾기.
---

# API 계약 절차

이 저장소의 프론트 응답 래퍼(`frontend/src/api/client.ts`)는 모든 JSON 응답을 생성된 계약(`frontend/src/api/generated/`)으로 검증하고, 어긋나면 화면에 오류를 띄운다. 계약은 서버 OpenAPI 응답 모델에서, 모델이 없으면 프론트 타입에서 만들어진다. 규칙 요약은 CLAUDE.md 'API 계약', 설계는 docs/specs/frontend-api-reliability.md.

## A. 새 API를 만들거나 응답 모양을 바꿀 때

1. **서버 모델 먼저**: `backend/models/{feature}.py` 또는 라우터의 Pydantic 모델에 응답을 정의하고 `@router.get(..., response_model=...)`로 연결한다.
   - 필드 이름은 파이프라인이 실제로 돌려주는 키와 같아야 한다. 파이프라인에서 키 이름을 바꾸면 모델도 같은 커밋에서 바꾼다(2026-07: `confidence`→`path_confidence`를 파이프라인만 바꿔 내러티브 경로 API가 석 달간 500).
   - 비거나 없을 수 있으면 `X | None`. LLM·외부 값이 정해진 집합 밖으로 나올 수 있으면 서버에서 정리하거나 `Literal[..., 'unknown']`처럼 실제 집합을 적는다.
   - 시장·종류별로 필드가 다르면 없는 쪽도 `None`으로 채워 모양을 같게 한다(2026-10: 주가 응답에 `market_cap`이 없어 모든 기업 상세 차트가 깨짐).
2. `cd backend && ../.venv/bin/python -c "from main import app"`.
3. **프론트**: `frontend/src/types/index.ts`(또는 기능 폴더)의 타입을 서버 모델과 같게 쓰고, 호출은 `apiQuery`/`getJson`/`postJson`(`@/api/query`) 또는 `api.get<T>`로 한다. 화면은 `shared/QueryState`로 상태를 그린다(갱신 실패 시 이전 데이터 유지).
4. `cd frontend && npm run contracts:generate` → `npm run contracts:check` → `npx tsc --noEmit -p tsconfig.app.json` → `npm run test:api`.
5. **사용자에게 백엔드 재시작을 요청**한다(`--reload` 없음). 재시작 전에는 옛 코드가 응답해 계약이 어긋난다.
6. 재시작 확인 후 `cd frontend && npm run contracts:live` — **실패 0**. 필수 쿼리·경로 파라미터가 있는 새 GET은 `frontend/scripts/live-contract-samples.json`에 예시 값을 넣는다(호출하면 수집·외부 요청이 도는 GET은 `skip`).
7. 백엔드 모델, 프론트 타입, 생성물(`frontend/src/api/generated/`), 예시 값을 **같은 커밋**에 담는다.

## B. 화면에 응답 형식 오류가 뜰 때

1. 배너의 **'자세히'**: `GET /api/... 200 · items.0.market_cap: must have required property` 형태로 API·필드가 보인다. 같은 내용이 `GET /api/spine/client-errors`와 운영 점검 '화면 API 오류(24시간)'에 남는다. 브라우저 콘솔에는 `[api]`로 찍힌다.
2. **백엔드 재시작 여부부터**: `GET /api/spine/admin/runtime`의 `stale: true`면 코드 수정 후 재시작 전이다. 배너에도 '재시작되지 않았습니다' 안내가 뜬다. 재시작 후 다시 본다.
3. 재시작 후에도 나면 실제 응답과 계약 중 어느 쪽이 맞는지 판단한다.
   - 서버가 실제로 그 값을 내는 게 맞다(예: `null`, 새 enum 값) → 서버 모델·프론트 타입을 실제에 맞추고 A-4 이후를 진행.
   - 서버가 잘못 낸다(필드 누락, 키 이름 불일치) → 서버를 고친다.
   - **계약·검증을 끄거나 `unknown`으로 느슨하게 만들어 덮지 않는다.**
4. `npm run contracts:live`로 같은 종류의 문제가 다른 API에도 있는지 한 번에 확인한다.
5. 5xx는 응답 모델 검증 실패(Pydantic `ValidationError`)인 경우가 많다 — `TestClient(app, raise_server_exceptions=True)`로 그 경로를 불러 traceback을 본다.

## 명령 모음

| 목적 | 명령 |
|---|---|
| 계약 생성 / 코드 일치 검사 | `cd frontend && npm run contracts:generate` / `npm run contracts:check` |
| 실제 응답 검사(백엔드 실행 중) | `cd frontend && npm run contracts:live` (`-- --no-report`면 기록 없이) |
| 정기 실행 기록 | `job_runs` 'live_contracts' (매일 08:40, `scripts/check_live_contracts.py`) |
| 오류 기록 | `GET /api/spine/client-errors?days=7` |
| 재시작 필요 여부 | `GET /api/spine/admin/runtime` |
| API 테스트 | `cd frontend && npm run test:api` |
