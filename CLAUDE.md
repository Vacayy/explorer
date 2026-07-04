# Stock Explorer — Project Instructions

## Product Orchestrator Workflow

멀티 디시플린 작업 시 아래 프로세스를 따른다:

```
Goal → Clarify(2-3질문) → Decompose → [Delegate → Checkpoint]* → Verify → Ship
```

### Phases (필요한 것만 선택)
1. **기획** — PRD, scope → 스펙: docs/specs/, docs/policies/
2. **화면설계** — Screen spec, 5-state 정의 → docs/specs/{feature}.md
3. **디자인리뷰** — Visual critique → docs/DESIGN_REVIEW.md
4. **백엔드** — API, DB, Service → backend/routers/, database.py
5. **프론트엔드** — Component, Hook, Type → frontend/src/
6. **검증** — tsc --noEmit, API curl, 5-state audit

### Delegation Rules
- 독립 Phase는 Agent 병렬 실행
- 각 Agent에 파일경로 + 데이터스키마 + 이전 Phase 산출물 전달 (Agent는 컨텍스트 없음)
- 기획/UX/디자인 후에만 stakeholder 확인 — 엔지니어링 결정은 자율

### Reference
- Phase 템플릿: skills/product-orchestrator/references/phases.md
- 전문가 프롬프트: skills/product-orchestrator/references/expert-prompts.md

---

## Integrity Rules (최우선 원칙)

### 정직한 보고
- **"완료"라고 보고하려면 실제로 요구사항을 충족해야 한다.** 비슷하게 흉내 낸 것은 완료가 아니다.
- "shadcn 기반으로 구현했습니다" → 실제로 Radix 프리미티브를 사용해야 한다. 네이티브 HTML에 Tailwind만 입힌 건 shadcn이 아니다.
- 기술적 제약(CLI interactive 등)으로 정확한 구현이 어려우면, **먼저 사용자에게 알리고 대안을 제시**한다. 조용히 대체 구현으로 넘어가지 않는다.
- 불확실하면 "이건 공식 shadcn이 아니라 비슷하게 직접 작성한 것입니다. CLI로 공식 설치하려면 `! npx shadcn@latest add <component>` 실행이 필요합니다"라고 명시한다.

### CLI/도구 실행이 필요할 때
- interactive CLI가 필요하면 **사용자에게 `!` 프리픽스 실행을 요청**한다. 직접 코드를 베껴쓰지 않는다.
- 예: `! npx shadcn@latest init`, `! npx shadcn@latest add select tabs tooltip`
- 공식 도구가 있는데 수동으로 재구현하는 것은 금지. 도구를 먼저 시도하고, 실패 시에만 수동 대안을 검토하되 사용자에게 상황을 보고한다.

### 요구사항 충족 기준
- 사용자가 "X를 사용해라"라고 하면, X의 **공식 구현**을 사용한다. "X와 비슷한 것"은 X가 아니다.
- 검증 시 기능 동작뿐 아니라 **구현 방식이 요구사항과 일치하는지**도 확인한다.

---

## Hard Rules (반드시 준수)

### 기획
- 새 기능은 반드시 `docs/specs/{feature}.md` 화면 기획서를 먼저 작성하거나 기존 스펙을 참조한 후 구현
- 모든 화면은 5-state 정의 필수: Empty / Loading / Partial / Error / Ideal (docs/policies/ui-states.md)
- PRD scope (P0/P1/P2) 외 기능을 임의로 추가하지 않는다
- Out of Scope 항목을 구현하려면 stakeholder 승인 필요

### 프론트엔드
- **UI atom은 반드시 shadcn 공식 컴포넌트를 사용**
  - shadcn 컴포넌트 추가: `npx shadcn@latest add <component>` CLI로 설치 (수동 작성 금지)
  - CLI가 interactive면 사용자에게 `! npx shadcn@latest add <component>` 실행 요청
  - Radix 기반 컴포넌트(Select, Tabs, Tooltip, Dialog 등)는 반드시 `@radix-ui/*` 패키지 사용
  - "shadcn 스타일로 직접 작성"은 shadcn이 아님. 공식 설치만 인정.
  - 현재 설치됨: Button, Card, Input, Select(Radix), Table, Badge, Textarea, Tabs, Separator, Tooltip
  - raw HTML 태그(`<select>`, `<button>` 등)를 UI 컴포넌트로 직접 쓰지 않는다
- **컴포넌트 계층 엄수**
  ```
  ui/        → shadcn atom만. 비즈니스 로직 없음.
  shared/    → ui/ 를 wrapping한 서비스 공통 컴포넌트. 도메인 로직 최소.
  layout/    → 전체 레이아웃 (Header, ModeNavigation, WatchlistSidebar)
  {page}/    → shared/를 조합. 직접 ui/도 사용 가능하나 shared/에 있으면 shared/ 우선.
  charts/    → lightweight-charts 기반 차트 (CandlestickChart, AreaSeriesChart 등)
  ```
- **새 페이지 컴포넌트 작성 시 체크리스트**
  - [ ] 5-state 모두 구현했는가? (Empty → Skeleton → ErrorState → Ideal)
  - [ ] 타입을 `types/index.ts`에 정의했는가?
  - [ ] hook을 `hooks/`에 분리했는가?
  - [ ] URL이 `App.tsx`에 등록되었는가?
  - [ ] 숫자 포맷이 `utils/format.ts` 함수를 사용하는가? (직접 toFixed/toLocaleString 금지)
- **디자인 토큰**
  - 색상은 `index.css`의 CSS 변수만 사용 (하드코딩 hex 금지)
  - 차트 색상: semantic 변수 사용 (`--color-chart-revenue`, `--color-chart-profit` 등)
  - Apple HIG 기반 디자인 시스템: 순백 배경, `#0071e3` primary, `rounded-xl` 카드
- **import 경로**: 항상 `@/` alias 사용 (상대경로 `../` 금지)
- **타입 체크**: 모든 FE 변경 후 `npx tsc --noEmit` 통과 필수

### 백엔드
- **새 API 추가 시 체크리스트**
  - [ ] `routers/{feature}.py`에 라우터 작성
  - [ ] `models/{feature}.py`에 Pydantic 스키마 작성
  - [ ] `main.py`에 라우터 등록
  - [ ] DB 테이블 필요 시 `database.py`의 `init_db()`에 추가
  - [ ] 기존 테이블 컬럼 추가 시 `ALTER TABLE ... ADD COLUMN` try/except 패턴 사용
- **DART 데이터**
  - 계정명 정규화: `_normalize_account_name()` 통해 변형 통합 (영업이익 = 영업이익(손실))
  - CFS 우선, OFS fallback
  - IS/CF는 분기 차감 (Q2=H1-Q1), BS는 시점 데이터 그대로
- **캐시**: 모든 외부 API 호출은 `cache_service.is_cached()` → `set_cache()` 패턴 사용
- **검증**: 모든 BE 변경 후 `python -c "from main import app"` 통과 필수

### 숫자 포맷 (docs/policies/number-formatting.md)
- 금액: 억/조 단위 자동 전환 (`formatKrw()`)
- 주가 변동: 상승=빨강(red), 하락=파랑(blue) — 한국 주식 컨벤션
- PER: 소수 1자리 + "배", PBR: 소수 2자리 + "배"
- 비율: 소수 1자리 + "%", 변동: "+1.5%p"
- null/빈값: 항상 `-` 표시

### 네비게이션 (docs/policies/navigation.md)
- 기업 선택 → `/analyze/:stockCode/summary` 자동 이동
- URL이 유일한 상태 소스 (useState로 모드/탭 관리 금지)
- 레거시 URL 리다이렉트 유지 (`/company/*` → `/analyze/*`)

---

## Tech Stack
- Backend: FastAPI + SQLite + OpenDartReader + pykrx + yfinance
- Frontend: React 19 + TypeScript + Vite + Tailwind CSS v4 + shadcn/ui + Recharts + lightweight-charts + TanStack Query
- Routing: react-router-dom v6 (URL = single source of truth)

## Component Hierarchy
```
ui/        ← shadcn atoms (Button, Card, Input, Table, Badge, Select, Textarea, Tabs, Separator, Tooltip)
shared/    ← 서비스 공통 (ChartCard, DataTable, PeriodToggle, YearToggle, SegmentTabs, FilterChips, HeroKpiCards, Skeleton, ErrorState)
layout/    ← 레이아웃 (Header, ModeNavigation, WatchlistSidebar)
charts/    ← lightweight-charts 래퍼 (CandlestickChart, AreaSeriesChart, MultiLineChart)
{page}/    ← 각 페이지 (shared + charts를 조합)
```

## URL Structure
```
/discover/industry | /discover/screener | /discover/signals | /discover/alt-data
/analyze/:stockCode/summary | financials | valuation | business | disclosures
/analyze/compare?stocks=...
/research/watchlist | /research/memos | /research/catalysts
```

## Key Policies
- 숫자 포맷: docs/policies/number-formatting.md
- 5-state UI: docs/policies/ui-states.md (Empty/Loading/Partial/Error/Ideal)
- 데이터 캐시: docs/policies/data-freshness.md
- 네비게이션: docs/policies/navigation.md
