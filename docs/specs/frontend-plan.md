# Frontend 구현 계획 — 디자인 시스템 → 컴포넌트 → API 정책

> 참조: ~/Desktop/projects/RWA-WALLET-QA-DASHBOARD (CVA + data-slot 스타일 shadcn,
> api/ 도메인 파일 + queryKey factory + 매핑 계층, 전역 에러 토스트).
> 기존 explorer CLAUDE.md 규칙(5-state, 컴포넌트 계층, format.ts, URL 단일 소스)은 전부 유지.

## Phase A — 디자인 시스템 (선행)

### A1. 디자인 토큰 재정비 + 다크모드
- `index.css`의 CSS 변수를 **semantic 토큰**으로 재정비: `--background/--foreground/--muted/
  --primary/--destructive/…` (shadcn 표준) + 도메인 토큰 `--color-up`(상승·빨강),
  `--color-down`(하락·파랑), `--color-chart-*`, `--color-fact`, `--color-hypothesis`.
- 다크모드: `next-themes` 도입, `.dark` 클래스 이중 정의. 상승/하락 색은 다크에서 채도 조정.
- 모든 컴포넌트는 토큰만 사용 (하드코딩 hex 금지 — 기존 규칙).

### A2. shadcn atoms 정비
- 기존 23개 atoms(Radix 기반, 공식 CLI 설치분) 유지.
- 누락 atoms 추가는 **공식 CLI로만**: `npx shadcn@latest add <component>`
  (interactive면 사용자에게 `!` 실행 요청 — CLAUDE.md 규정).
- 참조 프로젝트의 CVA variants·`data-slot` 패턴은 **새로 추가하는 atoms에 적용**,
  기존 atoms는 동작 변경 없이 유지 (surgical).

### A3. shared 도메인 컴포넌트 (ui/ 위에 조립)
| 컴포넌트 | 역할 | 사용처 |
|---|---|---|
| `SignalCard` | 신호 카드 프레임 + signal_type별 본문 슬롯 | /signals, /today |
| `DocumentCard` | 문서 카드 (제목·요약·소스·엔티티칩·원문링크) | /feed, /today, 근거문서 목록 |
| `EntityChip` | 종목/산업/토픽 칩 (클릭=필터 적용, confidence 낮으면 흐림) | 전역 |
| `SourceBadge` | telegram/blog/dart 소스 뱃지 | 카드류 |
| `EpistemicBadge` | 사실/가설 구분 뱃지 (+모델 출처: keyword/LLM) | 태그·해석 표시부 |
| `FreshnessStamp` | "n분 전 수집" 표시 | 섹션 헤더 |
| `StatDelta` | "7일 10회 (직전 1회)" 증감 강조 | SignalCard |
| `CalendarStrip` | 주간 이벤트 가로 스트립 | /today |
| `SparkLine` | 미니 주가 차트 (P1, lightweight-charts 래핑) | SignalCard |

## Phase B — 백엔드 읽기 API (spine 라우터, additive)

greenfield 원칙 유지: 새 라우터 파일로만 추가, 기존 라우터 미변경.
```
routers/spine_feed.py     GET /api/spine/feed?source=&stock=&industry=&topic=&page=
                          → raw_documents ⨝ enrichments ⨝ entity_links
routers/spine_signals.py  GET /api/spine/signals?type=&days=
                          → signals ⨝ entities (payload_json 포함)
routers/spine_today.py    GET /api/spine/today
                          → 캘린더(catalysts) + 신규 신호 + 24h 하이라이트 + 왓치리스트 펄스
```
- Pydantic 모델 `models/spine.py`. 모든 응답에 `fetched_at`/`as_of` 포함 (FreshnessStamp용).
- 기존 feed 라우터들은 cutover 완료 후 별도 커밋에서 은퇴.

## Phase C — FE API 계층 (TanStack Query 정책)

참조 프로젝트 패턴 도입, 기존 구조(hooks/ 분리)와 절충:
```
api/client.ts      axios 인스턴스 + 응답 에러 인터셉터(전역 sonner 토스트)  ← 참조 패턴
api/spine.ts       spine 엔드포인트 함수 + API응답→UI모델 매핑 + queryKey factory
hooks/useSpineFeed.ts / useSpineSignals.ts / useToday.ts   ← 기존 규칙(hooks/ 분리)
types/index.ts     UI 모델 타입 추가
```
**Query 정책:**
| 항목 | 정책 |
|---|---|
| queryKey | factory 패턴: `spineKeys.feed(filters)`, `spineKeys.signals(type)`, `spineKeys.today()` |
| staleTime | 피드/신호 5분, today 60초 (cron 주기 30분이므로 공격적 refetch 불필요) |
| 페이지네이션 | `placeholderData: keepPreviousData` (깜빡임 방지) |
| 에러 | 인터셉터 전역 토스트 + 화면은 ErrorState 컴포넌트 (5-state) |
| 필터 상태 | URL 쿼리 파라미터가 단일 소스 → queryKey에 그대로 반영 |
| mutation | 왓치리스트 토글 등: onSuccess에서 관련 key invalidate |

## Phase D — 화면 조립 (P0 순서)

1. `/today` — 신규. 섹션 4개, 각 섹션 독립 로딩(부분 실패 허용 = Partial state)
2. `/signals` — SignalCard 시스템. 기존 discover/signals 라우트를 새 화면으로 교체
3. `/feed` — 통합 피드 + 필터. 기존 feed/telegram·feed/blogs → 리다이렉트
4. 네비게이션 갱신: Today를 첫 탭으로

## 검증 (각 Phase 완료 시)
- `npx tsc --noEmit` 통과 (기존 규칙)
- 5-state 감사: Empty/Loading/Partial/Error/Ideal 전부 구현했는가
- 실데이터 확인: 백엔드 기동 → 실제 91+건 문서·신호 2건이 화면에 렌더
- 다크/라이트 두 테마에서 색상 대비 확인 (특히 상승빨강/하락파랑)

## 구현 순서 요약
```
A1 토큰+다크 → A2 atoms → B spine API → C query 계층 → A3+D 화면 (컴포넌트는 화면과 함께)
```
A3의 shared 컴포넌트는 실제 사용 화면(D)과 같은 단계에서 만든다 — 미리 만들면 추측 설계가 됨.
