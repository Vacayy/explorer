# 프런트엔드 API 안정성

## 점검 결과와 적용 범위

2026-10-30 점검에서 기본 Axios timeout 부재, 타입 단언만 있는 응답 처리, 별도 fetch 요청 계층, 화면별 실패/빈 결과 혼동, 렌더 오류 격리 부재를 확인했다.

- `frontend/src/api/client.ts`: 공통 Axios 요청의 기본 timeout 30초. 기존 요청별 긴 timeout은 유지한다. 정상 HTTP 2xx(201/204 포함)는 성공이며 4xx/5xx, 연결 실패, timeout은 구분한다. HTML/잘못된 JSON 응답을 데이터로 전달하지 않는다. blob/text 등 명시적 responseType은 별도 처리한다.
- `api/errors.ts`: `ApiError.kind`는 http/network/timeout/schema/unknown. status와 cause, 검증 issues는 진단용이며 화면에는 문자열 메시지만 전달한다. 취소는 오류로 정규화하거나 재시도하지 않는다.
- `api/query.ts`: Query signal을 요청에 전달한다. 네트워크/timeout/408/429/5xx는 최대 1회 재시도, 스키마/영구적 4xx는 재시도하지 않는다. 쓰기 mutation과 계산형 query는 자동 재시도하지 않는다. 캐시 단위 실패 알림으로 여러 observer의 중복 알림을 줄인다. 별도 onError가 있는 mutation은 기존 처리에 맡긴다.
- 분석/발견/전략 카탈로그의 별도 fetch 호출도 공통 요청 계층으로 통합했다. EventSource 스트림은 기존 재연결/이벤트 검증 흐름을 유지한다.

## 응답 계약

`api/contracts.ts`의 Zod 계약과 `api/openapi.ts`의 생성된 계약을 Axios 응답 interceptor에서 적용하여 직접 Axios 호출과 Query 유틸 호출 모두 캐시 저장 전에 검증한다. 숫자 문자열의 자동 변환이나 잘못된 배열을 빈 배열로 대체하는 처리는 하지 않는다. 추가 필드는 허용하여 서버의 필드 추가에 호환되게 한다.

현재 명시적 계약:

| 요청 | 검증 |
| --- | --- |
| GET /api/companies/search | 기업 배열 및 필드 |
| GET /api/companies/:code | 기업 필드 및 nullable 값 |
| GET /api/spine/feed | 페이지 크기/번호/총수, 문서/엔티티/이미지 배열 및 필드 |
| GET /api/spine/indices | 지수, 수치, spark 배열 및 갱신 정보 |
| GET /api/spine/transcript/recent | 실적발표 목록 및 필드 |
| GET /api/spine/transcript/follow | 추적 기업 및 최근 발표 ID |

### 자동 생성 계약

`npm run contracts:generate`는 현재 체크아웃의 FastAPI 앱에서 OpenAPI 응답 모델을 읽는다. 서버를 실행하거나 DB를 초기화하지 않는다. 응답 모델이 없는 경로는 TypeScript checker로 실제 호출의 응답 타입을 찾아 보완한다. 직접 Axios/Query factory, useQuery 타입, as 타입 단언, 문맥상 mutation 반환 타입, discovery action의 실제 호출 경로를 지원한다. 공개되지 않은 응답 타입이나 지원하지 않는 타입은 `generated/unresolved-types.json`에 기록하고 테스트에서 실패시킨다.

2026-10-30 기준 생성 계약은 **277개**다. 같은 경로를 여러 화면이 서로 다른 부분 타입으로 읽으면 그 필드를 모두 검증한다. null/undefined 구분을 보존하고 중첩 배열, 객체, enum, tuple과 `$ref`를 검증한다. [Ajv standalone](https://ajv.js.org/standalone.html)으로 빌드 시 생성하므로 브라우저에서 스키마를 컴파일하지 않는다. 기능별 검증기를 동적으로 로드해 초기 화면 번들에 전체 검증 코드를 포함하지 않는다.

- `api/generated/routes.json`: method/path/status/검증기 매핑. 특정 경로를 매개변수 경로보다 먼저 찾는다.
- `api/generated/unmodeled.json`: 자동 생성 대상에서 제외된 60개 응답. 8개 GET은 프런트에서 사용하지 않는 JSON 조회 5개와 스트림/파일 3개이며, 나머지는 응답 타입이 선언되지 않은 mutation이다. 이 중 컨콜 수집 POST는 아래의 명시적 계약으로 별도 검증한다. **명시적 계약도 없는 응답에는 전송/JSON 보호만 적용되며 필드별 검증은 적용되지 않는다.** 응답 본문을 화면이나 캐시에 쓰는 새 호출에는 응답 타입 또는 명시적 schema를 반드시 선언한다.
- `api/generated/unresolved-types.json`: 추출에 실패한 프런트 타입. 현재 0개.
- `npm run contracts:check`: 서버 모델·프런트 응답 타입·호출 경로와 생성물이 일치하는지 검사. 백엔드 의존성이 설치된 `.venv/bin/python`이 필요하며, 다른 환경은 `EXPLORER_PYTHON`으로 지정한다.

추가 점검으로 스터디 생성 ID, 프로젝트에 추가된 문서 ID 배열, 노트 저장 revision, 질문 후보 개수처럼 mutation 응답을 화면/캐시에 쓰는 곳에도 타입과 검증을 연결했다. 응답을 읽지 않고 조회를 무효화하는 쓰기 완료 응답은 별도 필드 계약 없이 HTTP/JSON 오류 보호를 유지한다.

컨콜 수집 `/api/spine/transcript/collect`는 `dry_run`에 따라 계획과 실행 접수의 응답이 다르므로 명시적 Zod 계약으로 분기한다. Axios URL과 `params`를 합친 실제 요청 URL을 기준으로 선택하며 잘못된 계획이 상태에 저장되거나 접수 응답이 계획으로 처리되지 않게 한다.

새 endpoint는 응답 모델/타입을 선언하고 `contracts:generate`를 실행한다. 생성된 파일을 직접 수정하지 않는다. 필요하면 `apiQuery`, `apiComputeQuery`, `getJson`, `postJson`의 `schema` 옵션으로 더 강한 값 제약을 추가한다. 정적 타입 인자만 추가하고 생성물을 갱신하지 않으면 런타임 보호가 추가되지 않으므로 `contracts:check`를 함께 실행해야 한다. 직접 선언하는 스키마는 [Zod 공식 parse 규약](https://zod.dev/basics)을 따른다.

```tsx
const schema = z.object({ items: z.array(z.object({ id: z.number(), label: z.string() })) })
const query = useQuery(apiQuery({ key: ['example'], url: '/api/example', schema }))
return <QueryState query={query} isEmpty={data => data.items.length === 0}>
  {data => <List items={data.items} />}
</QueryState>
```

## 오류 기록 (2026-10-31)

계약 위반·5xx·timeout·네트워크 오류는 화면에 일반 문구만 보이고 원인(어느 API의 어느 필드)이 어디에도 남지 않았다. 실제로 주가 응답(`GET /api/spine/feed/company-prices`)의 `market_cap` 누락이 국내·미국 기업 상세 차트를 모두 막았지만, 원인을 찾으려면 브라우저 요청을 가로채 검증기를 직접 돌려야 했다. 그래서 응답 래퍼에서 원인을 붙여 남긴다.

- `api/client.ts` 응답 interceptor가 `ApiError.endpoint`(`GET /api/...`, 쿼리 제외)를 붙인다. 계약 위반 issues는 그대로 유지한다.
- `api/telemetry.ts` `reportApiError`: 계약 위반·5xx·timeout·네트워크를 콘솔(`[api]`)과 `POST /api/spine/client-errors`로 보낸다. 4xx(입력·없는 자원)는 보내지 않는다. 같은 API·종류·상태·필드는 10분에 한 번만 보낸다. 보고 실패는 무시한다.
- 서버 `client_errors` 테이블은 같은 서명(API·종류·상태·필드)을 한 행으로 묶어 횟수·처음/마지막 시각·마지막 화면을 쌓는다. `GET /api/spine/client-errors?days=7`로 조회한다.
- 운영 점검(`/api/spine/admin/health`, 상단 '운영' 배지)에 '화면 API 오류(24시간)' 항목: 최근 24시간 기록이 있으면 비정상, detail에 상위 3개 API·필드·횟수. 텔레그램 경고 대상(critical)은 아니다.
- 화면 배너(`ActiveQueryStatus`)에 '자세히'를 두어 실패한 API·상태·첫 검증 실패 필드를 보인다.
- 검증: `tests/api-telemetry.test.ts`(원인 포함 보고·같은 오류 1회·5xx만 보고).

## 실제 응답 검사 (2026-10-31)

`contracts:check`는 코드끼리(서버 모델·프론트 타입·생성물)만 비교해 실제 데이터에서만 나오는 `null`·새 enum 값·빠진 필드와 서버 응답 모델 오류(500)를 못 잡는다. 첫 실행에서 프론트 타입 추측 5건(주가 `market_cap`, 스터디 목록, 가이던스 `unknown`, 발견 레인 `web`, 스터디 검색 `published_at` null)과 서버 모델 이름 불일치로 석 달간 500이던 내러티브 경로·MER 2건이 나왔다.

- `frontend/scripts/check-live-contracts.mjs`(`npm run contracts:live`): 실행 중인 백엔드의 GET 계약 전부를 `scripts/live-contract-samples.json` 예시 값으로 호출해 생성된 검증기로 검사한다. 실패는 콘솔과 `client_errors`(page='live-check')에 남기고 종료 코드 1. 예시 값이 없거나 non-200이면 '호출 못 함' 목록으로 알린다. 호출하면 수집이 도는 GET은 `skip`.
- 정기 실행: `scripts/check_live_contracts.py` → `job_runs('live_contracts')`, launchd `contracts` 매일 08:40(따라잡기 대상). 백엔드가 떠 있지 않으면 skipped.
- node에서는 ajv CJS 헬퍼를 쓰는 검증기(문자열 길이 제한, 대시보드)가 실행되지 않아 'node 검증 불가'로 따로 분류한다. 브라우저(vite)에서는 정상.

## 서버 반영 (2026-10-31)

백엔드는 `--reload` 없이 돈다(수 분짜리 백그라운드 작업이 코드 저장마다 끊기지 않게). 코드를 고친 뒤 재시작 전에는 옛 코드가 응답해, 즉시 반영되는 프론트와 계약이 어긋난다.

- `pipeline/runtime.py`: 서버 시작 시각과 `backend/` .py 최신 수정 시각을 비교. `GET /api/spine/admin/runtime`(`stale`, 바뀐 파일, 경과 분).
- 운영 점검 '백엔드 코드 반영'(서버 프로세스에서만 붙임): 시작 후 코드가 바뀌었으면 비정상 "재시작 필요 — N분 전 파일 변경".
- 화면 배너: 계약 오류가 있을 때만 런타임을 조회해 `stale`이면 "백엔드가 N분 전 바뀐 코드로 아직 재시작되지 않았습니다"를 함께 보인다.
- 작업 규칙: CLAUDE.md 'API 계약', 절차 `.claude/skills/api-contract/SKILL.md`, Codex용 `AGENTS.md`.

## 화면 상태 규약

`components/shared/QueryState.tsx`는 아직 성공 응답이 없는 undefined와 정상적인 null/빈 배열을 구별한다.

| 상황 | 표시 |
| --- | --- |
| 최초 요청 중 | 스켈레톤, status/aria-busy |
| 응답 전 실패 | 오류 메시지와 재시도 |
| 오프라인으로 요청 보류 | 연결 대기, 연결 후 자동 재개 |
| 비활성 조회 | 조회 조건 선택 안내 |
| 성공했지만 데이터 없음 | 빈 상태 안내 |
| 성공 | 데이터 표시 |
| 기존 데이터 갱신 중 | 데이터 유지, 업데이트 중 안내 |
| 기존 데이터 갱신 실패 | 데이터 유지, 이전 결과 안내와 재시도 |

홈 메뉴·문서 검색·기업 분석 진입 외에 저장 목록, 인물 목록/상세, 미국 기업 목록/상세, 실적발표 목록/모멘텀, 소스/문서 상세, 포트폴리오 요약/이력/원칙/규칙 상태/노출/이벤트/알림/자료 흐름에 QueryState를 적용했다. 문서 관련 자료의 독립적인 조회 실패도 숨기지 않는다. 기존 ErrorState/EmptyState/WidgetState에도 접근 가능한 상태 알림을 추가했다.

기존 상태 분기를 사용하는 화면에도 `ActiveQueryStatus`가 실패와 연결 대기를 지속적으로 표시한다. 현재 화면의 활성 observer만 추적하므로 이전 화면·prefetch·비활성 조회 오류는 보이지 않는다. 재시도는 실패한 활성 요청만 대상으로 하며 정상 데이터와 무관한 요청은 다시 실행하지 않는다. 토스트만 사라지고 오류가 보이지 않는 상태를 막는다.

페이지 경계는 URL이 바뀌면 초기화되며 메뉴를 유지한다. 홈 위젯은 개별 경계로 격리한다. 최상위 경계는 레이아웃 오류까지 보호한다. 경계의 재시도는 실패한 활성 Query만 다시 요청하며 정상 캐시를 초기화하지 않는다. 렌더 오류 경계는 비동기 이벤트 핸들러의 예외를 대신 처리하지 않으므로 수동 async 작업은 try/catch 또는 mutation 상태 처리를 유지해야 한다.

## 검증

- `cd frontend && npm run test:api`: HTTP 오류, 실제 지연 timeout/abort, JSON/중첩 타입 오류, 빈 결과, 캐시 유지, 스켈레톤/오류/재시도, 렌더 경계 테스트.
- `cd frontend && node --test tests/*.test.mjs`: 기존 회귀 테스트.
- `cd frontend && npm run build`: 타입 검사와 프로덕션 번들.
- 로컬 백엔드의 기업 검색/상세, 홈 메뉴, 문서 피드, 지수, 최근 실적발표, 추적 기업 조회를 읽기 전용으로 호출하여 실제 응답 계약을 확인했다.
- `cd frontend && npm run contracts:check`: 생성물 최신성/재현성 검사.
- `cd frontend && npm run lint`: ESLint flat config를 추가해 실행 가능하게 했다. 생성물은 제외하며 기본 오류와 Hooks 호출 순서를 검사한다. 미사용 선언/이름 검사는 TypeScript build가 담당한다.
- 추가로 그룹·재무·주가·검색·저장·인물·유튜브·포트폴리오·실적발표 모멘텀·분석 실행/전략 등 실제 조회 16개가 자동 생성 계약을 통과함을 확인했다.
