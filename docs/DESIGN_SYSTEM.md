# Explorer 디자인 시스템

> 최종 갱신: 2026-09-10 · 참고 모델: Meta astryx (CSS 변수 테마 · 강한 컨벤션 · 조합 가능한 컴포넌트 · "guidance over enforcement")
> 관련: CLAUDE.md 프론트엔드 Hard Rules · docs/policies/number-formatting.md · docs/policies/ui-states.md

## 2026-09-10 점검 상태

### 승인된 통합안 — 구현 계약 (D-152, D-153)

사용자가 마켓 홈 통합안 구현을 승인했다. 첫 적용 범위는 전역 토큰·Card/Button/Input 기본값, 공통 페이지 레이아웃, 홈·통합 피드·문서 검색, 도크 재질이다. 나머지 페이지의 개별 조합과 임의 글자 크기는 후속 이행 대상으로 남긴다.

- 서체: 자체 호스팅 IBM Plex Sans / Sans KR 400·500·600·700. 페이지 24/32, 섹션 18/26, 카드 제목 16/24, 읽기 본문 14/22, UI 14/20, 캡션 12/18. 일반 콘텐츠 기본은 14px이며 Markdown h1/h2/h3는 20/18/16px로 본문보다 크게 유지한다. 숫자는 tabular-nums.
- 단색 중립 배경 + 기존 멀버리 액션색. 카드 radius 20px, control 10px, overlay 16px. 카드 패딩 20px(모바일 16px), 열 간격 24px. 그림자는 도크·오버레이에 제한.
- PageLayout의 header / overview / toolbar / footer / children 슬롯. mode=document|workspace|reader, width=full|reading. 문서형은 페이지 스크롤. SplitWorkspace는 label·content·surface를 가진 두 패널을 조합하고 URL 상태는 페이지가 소유한다.
- Home은 상단 시장/피드 모드 전환. 시장 document는 가용 폭 1000px부터 모듈 2열. 피드 reader는 760px부터 300px 목록 + 연속 본문, 그 미만은 목록/본문 전환. 화면 높이 740px 미만은 문서 스크롤로 복귀한다. SplitWorkspace의 900px 두 열 계약은 다른 사용처를 위해 보존한다. 셸이 외부 여백·도크 예약과 --shell-offset을 소유한다.
- 피드는 하나의 둥근 표면 + 아티클 구분선. 카드/행 표현은 FeedPost의 명시적 variant로 구분하며 데이터 모델·링크·필터·펼침은 보존한다.
- 브리핑은 사용자 후속 요청에 따라 일반 Card 표면을 사용한다. 별도 반전 대비는 해제했다. 날짜·데이터·차트·상태·새로고침 기능은 보존한다.
- 글래스는 도크·일부 탐색 버튼만. reduced-transparency / 미지원 브라우저에서는 불투명 배경으로 폴백한다.
- 공식 shadcn/Radix의 동작·API는 유지하며 기반 스타일의 관리된 수정을 허용한다. 기존 ui/ 수제작 금지는 새 동작 재구현에 적용하고, 승인된 토큰·기본값 수정은 허용한다.

- DetailLayout은 PageLayout 위에서 복귀/context/header/actions/navigation/body/aside/related를 조합한다. /doc, 주제 내러티브, 버전 상세에 적용했다. 본문 최대 760px, 보조 220px는 가용 폭 1000px부터 옆에, 그 미만은 아래로 배치한다. 단일 Card 표면·14px 본문·24px 제목. 상세에서는 팔로우 레일과 월드모델 서브탭을 기본 크롬에서 내린다.
- 원문/요약·내러티브 상세 탭·선택 버전은 URL에 보존한다. DetailLink는 출발 경로/이력 상태를 전달하고, 탭 단위 UI 메모리는 스크롤·포커스만 최대 100개 보존한다. 직접 링크는 출처·목록 fallback을 사용한다.

아래 과거 규칙과 충돌하면 이 구현 계약을 우선한다. 적용 범위와 남은 이행 작업은 DESIGN_REVIEW에서 관리한다.

후속 사용자 피드백으로 시각 방향을 **마켓 홈 통합안**으로 좁혔다: 나의 마켓 홈의 둥근 표면·대비 브리핑, 정밀한 분석 데스크의 하나로 이어지는 피드, 도크·일부 탐색 요소의 절제된 글래스. 배경은 단색이며 무지개 형태의 다색 그라데이션은 사용하지 않는다. [기존 제품 사례 HTML](prototypes/product-design-study.html)의 기본 화면을 이 조합으로 갱신했다. 채택된 라운딩·테마·서체는 위 구현 계약에 반영했다. HTML은 비교 이력으로 유지한다.

[제품 사례 연구·시각 방향 3안](prototypes/product-design-study.html)은 Revolut·Stripe·Apple·Linear·Mercury의 공식 자료를 바탕으로 균형형 레이아웃의 표면·정보 위계·상호작용을 비교한다. 글래스는 탐색 층에 한정한 후보이며, 기존 토큰 기획안과 다른 크기·라운딩은 채택 시 이 문서의 단일 기준으로 통합한다. 채택된 통합안은 위 구현 계약으로 적용했다.

사용자가 레이아웃 방향으로 **균형형 워크스페이스**를 선택했다. [디자인 토큰·컴포넌트 HTML 기획안](prototypes/balanced-design-system.html)에서 IBM 타이포그래피, 색상·밀도, 컴포넌트 계약, 페이지 슬롯 및 단계별 적용을 검토한다. 당시 제안 중 채택된 값은 위 구현 계약에 통합했다. [앞선 레이아웃 3안](prototypes/page-layout-concepts.html)은 비교 이력이다.

[DESIGN_REVIEW](DESIGN_REVIEW.md)에 전체 코드 감사와 IBM Plex 기반 재설계 제안을 정리했다. 아래는 기존 규칙이며 코드와 불일치하는 항목(특히 CardHeader grid/flex, 카드 radius, 글자 크기)이 있다. **IBM Plex Sans/KR은 현재 자체 호스팅 폰트로 적용됐다.** 디자인 기준 개편 시 이 문서를 갱신하고, 감사/후속 문서를 별도로 늘리지 않는다.

## 원칙 (astryx에서 차용)

1. **테마 = CSS 커스텀 프로퍼티 오버라이드 집합.** 색·라운딩은 `index.css`의 `:root`(light) / `.dark`에서만 정의하고, 컴포넌트는 semantic 토큰만 소비한다. 하드코딩 hex 금지.
2. **강한 컨벤션.** 같은 패턴은 한 가지 방식으로만 구현한다 (세그먼트 토글 4종 난립 금지 → ToggleGroup 하나).
3. **조합 가능성.** shadcn atom(ui/)을 잠그지 말고 shared/에서 조합해 서비스 컴포넌트를 만든다. 최상위 API 뒤에 감추지 않는다.
4. **사람과 에이전트 모두를 위한 문서.** 이 문서는 LLM이 새 화면을 만들 때 그대로 따를 수 있게 규칙·예외를 명시한다.

## 1. 레이아웃 컨트랙트

### 셸 (App.tsx Layout — shadcn Sidebar 기반, D-017 → 상단 크롬 제거·하단 도크, D-136)

```
<div min-h-screen>
  <Omnibar/>                              ⌘K 오버레이 (CommandDialog)
  <SidebarProvider defaultOpen={≥1280px} --sidebar-width:16rem>
    <SidebarInset>                        메인 컬럼 (=main) — 상단 크롬 없음
      <div mx-auto max-w-[var(--layout-shell)] px-6 pt-6 pb-[var(--dock-reserve)]>
        <SubNav/>                         모드 안 L2 (있을 때만, h-8 + mb-5 = --subnav-height)
        ← 페이지 렌더 슬롯
      </div>
    </SidebarInset>
    <Dock/>                               fixed bottom-4 · 뷰포트 중앙 · 플로팅 pill (docs/specs/dock-navigation.md)
    <FollowRail/>                         shadcn <Sidebar side=right collapsible=offcanvas>
  </SidebarProvider>
</div>
```

- 폭 상한 토큰: `--layout-shell: 1440px` (index.css). 본문 슬롯이 이 토큰을 쓴다. 도크는 뷰포트 중앙 고정(레일 열림/닫힘에 흔들리지 않게).
- 페이지는 슬롯 안에서 렌더되므로 **자체 padding·margin·max-w를 지정하지 않는다.**
- **도크(layout/Dock.tsx)** = `[검색] │ Home ┃ 팔로우 · 피드 · 월드모델 ┃ 대화 │ [열린 도시에] │ 승인 · 저장 · 레일 · 더보기`. 아이템=아이콘 20+라벨 11 상시(`DockItem`), 활성=primary 틴트+하단 점, 배지=우상단 원형 숫자(승인=hypothesis, 저장=primary). L2가 있는 항목은 호버 250ms → `ui/hover-card` 팝오버(모드 간 점프). `<768`은 전폭 하단 탭바(5모드+더보기, 활성 탭 재탭 → L2 Sheet).
- **SubNav(layout/SubNav.tsx)** = 모드 안 형제 탭 한 행(pill). 탭 목록은 `layout/navConfig.ts` 한 곳 — 도크 팝오버와 공유.
- **팔로우 레일 = 공식 shadcn Sidebar**. 넓은 데스크톱(≥1280px)=펼침, 이하=토글(도크 '레일'/⌘B), 모바일=Sheet 오버레이 자동.
- **보더리스**: 카드색(card) vs stone 바탕 대비로 층 표현. 카드는 ring+shadow. 도크는 `bg-card/85 backdrop-blur ring-1 shadow-lg`.
- 토스트(sonner)는 **우상단** — 하단은 도크·대화 컴포저 자리.

### 레거시 페이지 컨테이너 (shared/PageContainer)

미이행 페이지는 `<PageContainer>`로 호환 유지. 홈·피드는 위의 `PageLayout` 계약을 따른다:

| prop | 값 | 용도 |
|---|---|---|
| `width` | `full`(기본) | 데이터 밀집 화면 — 셸 폭 전부 |
| | `reading` | max-w-3xl — 읽기 문서 (doc·source·archive) |
| `gap` | `md`(기본, space-y-6) | 카드·차트 중심 화면 |
| | `sm`(space-y-4) | 리스트·테이블 밀집 화면 |

**예외 — 풀하이트 앱형 페이지** (ChatPage·SummaryPage): PageContainer 대신
`h-[calc(100dvh-var(--shell-offset))]` + 내부 `overflow-y-auto`. `--shell-offset`(= 상단 p-6 + `--dock-reserve` + SubNav 있으면 `--subnav-height`)은 Layout이 인라인으로 확정한다 — 매직넘버 금지.

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
| 레이아웃 | `--layout-shell` `--dock-height` `--dock-reserve` `--subnav-height` `--shell-offset` | §1 참조 |
| 라운딩 | `--radius`(0.75rem) 파생 sm~4xl | 카드=`rounded-xl` |

폰트: 자체 호스팅 IBM Plex Sans / Sans KR, 숫자는 전역 `tabular-nums` (td/th 자동).

## 3. 컴포넌트 계층과 컨벤션

```
ui/      shadcn 공식 기반. 관리된 토큰·스타일 수정 허용(D-152), 동작 수제 재구현 금지.
shared/  ui/를 조합한 서비스 공통 (PageContainer, SegmentTabs, ChartCard, DataTable…)
layout/  셸 전용 (Dock·DockItem·Inboxes, SubNav, navConfig, FollowRail)
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
| `layout/SubNav.tsx` · `layout/Dock.tsx` 모드 Link | 라우터 연동 네비 — Radix Tabs 의미론(패널 전환)과 다름. Link(pill) 유지. 도크 아이템은 ui/button 기반 |

이 표에 없는 raw HTML atom 사용은 전부 위반이다.

## 4. 신규 화면 체크리스트

- [ ] 최상위 `<PageContainer>` (width·gap 선택) — 자체 max-w/padding 없음
- [ ] 그리드는 `grid-cols-1`에서 시작하는 반응형
- [ ] 넓은 표는 ui/table 또는 `overflow-x-auto` 래퍼
- [ ] 색상은 semantic 토큰만 · 등락=up/down · LLM 산출=hypothesis
- [ ] 5-state (Empty/Loading/Partial/Error/Ideal) + FreshnessStamp
- [ ] 숫자 포맷은 utils/format.ts
- [ ] 새 atom 필요 시 `npx shadcn@latest add <c>` CLI 설치 (수제 금지)
