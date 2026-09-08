# Explorer 디자인 시스템

> 최종 갱신: 2026-07-11 · 참고 모델: Meta astryx (CSS 변수 테마 · 강한 컨벤션 · 조합 가능한 컴포넌트 · "guidance over enforcement")
> 관련: CLAUDE.md 프론트엔드 Hard Rules · docs/policies/number-formatting.md · docs/policies/ui-states.md

## 원칙 (astryx에서 차용)

1. **테마 = CSS 커스텀 프로퍼티 오버라이드 집합.** 색·라운딩은 `index.css`의 `:root`(light) / `.dark`에서만 정의하고, 컴포넌트는 semantic 토큰만 소비한다. 하드코딩 hex 금지.
2. **강한 컨벤션.** 같은 패턴은 한 가지 방식으로만 구현한다 (세그먼트 토글 4종 난립 금지 → ToggleGroup 하나).
3. **조합 가능성.** shadcn atom(ui/)을 잠그지 말고 shared/에서 조합해 서비스 컴포넌트를 만든다. 최상위 API 뒤에 감추지 않는다.
4. **사람과 에이전트 모두를 위한 문서.** 이 문서는 LLM이 새 화면을 만들 때 그대로 따를 수 있게 규칙·예외를 명시한다.

## 1. 레이아웃 컨트랙트

### 셸 (App.tsx Layout — shadcn Sidebar 기반, D-017)

```
<div min-h-screen>
  <Omnibar/>                              ⌘K 오버레이 (CommandDialog)
  <SidebarProvider defaultOpen={≥1280px} --sidebar-width:16rem>
    <SidebarInset>                        메인 컬럼 (=main)
      <Header>          h-14 · sticky · 보더 없음 · 단일 검색=옴니바 트리거
      <ModeNavigation>  보더 없음
      <div mx-auto max-w-[var(--layout-shell)] p-6>  ← 페이지 렌더 슬롯
    </SidebarInset>
    <FollowRail/>                         shadcn <Sidebar side=right collapsible=offcanvas>
  </SidebarProvider>
</div>
```

- 폭 상한 토큰: `--layout-shell: 1440px` (index.css). Header·ModeNavigation·본문이 **반드시 이 토큰을 공유** — 개별 하드코딩 금지.
- 페이지는 `p-6` 슬롯 안에서 렌더되므로 **자체 padding·margin·max-w를 지정하지 않는다.**
- **팔로우 레일 = 공식 shadcn Sidebar**. 넓은 데스크톱(≥1280px)=펼침, 이하=토글(헤더 패널버튼/⌘B), 모바일=Sheet 오버레이 자동. 헤더/네비는 이제 inset 폭 안에 있음(레일 열림 시 축소).
- **보더리스**: 헤더·네비에 `border-b` 없음 — 카드색(card) vs stone 바탕 대비로 층 표현. 카드는 ring+shadow. 표 행 구분선·인풋·세그먼트는 유지.

### 페이지 컨테이너 (shared/PageContainer)

모든 라우팅 페이지의 최상위는 `<PageContainer>`:

| prop | 값 | 용도 |
|---|---|---|
| `width` | `full`(기본) | 데이터 밀집 화면 — 셸 폭 전부 |
| | `reading` | max-w-3xl — 읽기 문서 (doc·source·archive) |
| `gap` | `md`(기본, space-y-6) | 카드·차트 중심 화면 |
| | `sm`(space-y-4) | 리스트·테이블 밀집 화면 |

**예외 — 풀하이트 앱형 페이지** (ChatPage): PageContainer 대신
`h-[calc(100dvh-var(--shell-offset))]` + 내부 `overflow-y-auto`. `--shell-offset` 토큰만 사용, 매직넘버 금지.

### 반응형 규칙

- 다열 그리드는 **반드시 모바일 1열에서 시작**: `grid-cols-1 md:grid-cols-2` / `lg:grid-cols-3`. 무분기 `grid-cols-N` 금지.
- 고정폭 컬럼(`grid-cols-[240px_1fr]` 등)은 `lg:` 이상에서만, 이하는 1열 스택.
- 가로 스크롤은 **컨테이너 안에서만**: 넓은 표·스트립은 자신을 감싼 `overflow-x-auto` 안에서 스크롤. 페이지(body) 가로 스크롤은 항상 버그다.
- 뷰포트 높이는 `dvh` 사용 (모바일 주소창 대응).

## 2. 토큰 카탈로그 (index.css)

| 그룹 | 토큰 | 규칙 |
|---|---|---|
| shadcn semantic | `--color-background/foreground/card/primary/muted/accent/border…` | 모든 UI 색상의 기본 어휘 |
| 도메인: 주가 | `--color-up`(빨강) `--color-down`(파랑) | 한국 컨벤션. 등락 표시는 이 둘만 |
| 도메인: 인식론 | `--color-fact`(초록) `--color-hypothesis`(주황) | LLM 산출=hypothesis 스타일 필수 |
| 차트 | `--color-chart-revenue/profit/ratio/negative/warning`, `--color-chart-1~5` | 신규 차트는 semantic 우선, 팔레트(1~5)는 시리즈 나열용 |
| 레이아웃 | `--layout-shell` `--shell-offset` | §1 참조 |
| 라운딩 | `--radius`(0.75rem) 파생 sm~4xl | 카드=`rounded-xl` |

폰트: Inter Variable + Noto Sans KR fallback, 숫자는 전역 `tabular-nums` (td/th 자동).

## 3. 컴포넌트 계층과 컨벤션

```
ui/      shadcn 공식 CLI 설치본만. 수정·수제작 금지.
shared/  ui/를 조합한 서비스 공통 (PageContainer, SegmentTabs, ChartCard, DataTable…)
layout/  셸 전용 (Header, ModeNavigation, FollowRail)
charts/  lightweight-charts 래퍼
{page}/  shared 조합. shared에 있으면 shared 우선.
```

### 패턴 → 지정 구현 (다르게 만들지 말 것)

| 패턴 | 구현 |
|---|---|
| 단일선택 세그먼트/토글 | `ui/toggle-group` (Radix) — shared/SegmentTabs·PeriodToggle·YearToggle·FilterChips가 이것을 래핑 |
| 접기/펼치기 | `ui/collapsible` (Radix) — useState+조건부 렌더 수제 금지 |
| 콤보박스/검색 팔레트 | `ui/command` (+Popover/CommandDialog) — 예: CompanySearchCombobox, Omnibar |
| 데이터 테이블 | `ui/table` (자동 overflow-x 래퍼 내장) 또는 shared/DataTable |
| 온/오프 | `ui/switch` · 체크 다중선택: `ui/checkbox` |
| 버튼·인풋 | `ui/button`(variant: default/ghost/outline, size: sm) · `ui/input` — raw `<button>`/`<input>` 금지 |
| 사이드바/레일 | `ui/sidebar` (Radix, 반응형 offcanvas+모바일 Sheet) — 예: layout/FollowRail |
| 모달 확인 | `ui/alert-dialog` — native `confirm()` 금지 |
| 진행률 | `ui/progress` — 수제 width 바 금지 |
| 오버레이 드로어 | `ui/sheet` |
| 강조 카드 (AI/hypothesis·primary) | **배경 틴트로 강조**: `bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]` (AI) / `var(--primary)` (홈 브리핑). 좌측 보더(`border-l-*`) 강조는 변칙 — 금지. 예외: 리스트 선택 마커·인용 들여쓰기·다이어그램 헤더는 보더 유지 (D-018). **/chat 어시스턴트 본문은 말풍선·틴트 없이 풀폭 텍스트 — LLM 산출 마커는 `text-hypothesis` 라벨 행으로**(D-135, docs/specs/chat-page.md §4) |
| 빈/로딩/에러 | shared/Skeleton · shared/ErrorState (5-state 정책) |

### 허용된 예외 (grandfathered — 신규 작성 금지, 점진 이관)

| 파일 | 사유 |
|---|---|
| `actions/RightsProTable.tsx` | sticky 첫 컬럼 + `w-max` 밀집 테이블 — raw table 유지, `overflow-x-auto` 래퍼 필수 |
| `discovery/ScreenerPage.tsx` · `industry/IndustryPage.tsx` 내부 Th/Td | 정렬 헤더 로컬 헬퍼 — 토큰 준수 확인됨 |
| `layout/ModeNavigation.tsx` | 라우터 연동 네비 — Radix Tabs 의미론(패널 전환)과 다름. Link+border-b 유지 |

이 표에 없는 raw HTML atom 사용은 전부 위반이다.

## 4. 신규 화면 체크리스트

- [ ] 최상위 `<PageContainer>` (width·gap 선택) — 자체 max-w/padding 없음
- [ ] 그리드는 `grid-cols-1`에서 시작하는 반응형
- [ ] 넓은 표는 ui/table 또는 `overflow-x-auto` 래퍼
- [ ] 색상은 semantic 토큰만 · 등락=up/down · LLM 산출=hypothesis
- [ ] 5-state (Empty/Loading/Partial/Error/Ideal) + FreshnessStamp
- [ ] 숫자 포맷은 utils/format.ts
- [ ] 새 atom 필요 시 `npx shadcn@latest add <c>` CLI 설치 (수제 금지)
