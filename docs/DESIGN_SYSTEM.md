# Explorer 디자인 시스템

> 최종 갱신: 2026-11-05 · 참고 모델: Meta astryx (CSS 변수 테마 · 강한 컨벤션 · 조합 가능한 컴포넌트 · "guidance over enforcement")
> 관련: CLAUDE.md 프론트엔드 Hard Rules · docs/policies/number-formatting.md · docs/policies/ui-states.md

## 2026-11-05 · 현행 계약 — Daylight·Midnight 디자인 시스템 (D-320)

이 절이 아래의 모든 과거 규칙(화이트 플랫·멀버리·IBM Plex 단독·빨강 상승)보다 우선한다. 값의 원본은 `frontend/src/index.css`다.

### 토큰 (시안 이름 그대로)

| 토큰 | 라이트 Daylight | 다크 Midnight | 쓰임 |
|---|---|---|---|
| `--bg` · `--surface` · `--surface-2` | #FCFFFF · #FFFFFF · #F2F7F9 | #02070A · #081014 · #0D181E | 페이지 · 카드·표 · 입력·hover |
| `--ink` · `--ink-2` · `--ink-3` | #0E1A22 · #46555F · #5F6F7A | #EAF2F7 · #A6B6C1 · #8396A2 | 본문·주 버튼 · 보조 · 캡션 |
| `--line` · `--line-2` | ink 10% · 18% | ink 10% · 18% | 면 경계 · 컨트롤 테두리·표 머리 |
| `--up` · `--up-ink` · `--up-tint` | #D83995 · #B4237A · 10% | #FC734D · #FC8A68 · 12% | 상승(막대·점 · 숫자 · 배지) |
| `--down` · `--down-ink` · `--down-tint` | #0593C6 · #04709A · 10% | #0297DE · #3DB2EE · 14% | 하락 |
| `--hyp` · `--hyp-tint` | #6E46CF · 8% | #B79BFF · 10% | AI 해석(LLM 산출) |
| `--fact` · `--fact-tint` | #0B7A5E · 8% | #4FD1A5 · 10% | 사실 확인·신선 |
| `--warn` · `--warn-tint` | #A35F00 · 10% | #F2C14E · 12% | 지연·경고·미평가 |
| `--action` · `--action-ink` | ink · bg | ink · bg | 주 버튼·선택 상태 |
| `--chip` | ink 6% | 흰색 7% | 보조 버튼·입력·세그먼트 바탕 |
| `--series` · `--grid` | ink 26% · 7% | ink 28% · 7% | 차트 시리즈(회색) · 격자 |
| `--closed` | #C8372D | #F25F5C | 장 마감 점 · 파괴적 행동(`--destructive`) |
| `--field` · `--ribs` · `--glass` · `--glass-line` · `--veil` | | | 기상도 전용(아래) |

shadcn 변수는 이 토큰에 잇는다: `--background=--bg`, `--card/--popover=--surface`, `--foreground=--ink`, `--muted=--surface-2`, `--muted-foreground=--ink-3`, `--primary=--action`, `--secondary/--accent=--chip`, `--border=--line`, `--input=--line-2`, `--ring=--ink`, `--hypothesis=--hyp`, `--chart-warning=--warn`. 기존 이름(`--color-up`·`--chart-*` 등)은 별칭으로 남아 있다.

### 테마

- `<html class="dark">` 하나로 전환한다. 테마·설정 메뉴(상단 바 해·달 아이콘, D-323)의 세그먼트에서 시스템·라이트·다크를 고른다. 기본은 시스템(`prefers-color-scheme`), 선택은 localStorage `theme`(next-themes)에 남는다.
- `index.html`의 인라인 스크립트가 첫 그림 전에 `.dark`를 붙여 깜빡임을 막는다.
- 캔버스 차트(lightweight-charts)는 `components/charts/chartTheme.ts`의 `useChartTheme()`로 토큰을 읽고, 테마가 바뀌면 다시 칠한다. Recharts·SVG는 `var(--token)`을 그대로 쓴다.

### 서체 (Google Fonts, 실패하면 시스템 서체)

| 역할 | 서체 | 크기 |
|---|---|---|
| 페이지 제목 | Geist 400 (`font-display text-page`) | 30/36, 자간 −0.02em |
| 기상도 헤드라인 | Geist 300 + 강조는 Instrument Serif 이탤릭(`font-serif italic`) | 64/66 (`text-weather`). 홈 날짜는 34 |
| 섹션 제목 | IBM Plex Sans KR 600 (`text-section`) | 15/21. 블록 머리 13.5 |
| 본문 | IBM Plex Sans KR 400 (`text-reading`) | 14/22 |
| 캡션 | IBM Plex Sans KR 400 (`text-caption`) | 12/18 |
| 숫자 | Geist Mono, tabular (`tabular-nums`이면 자동으로 모노) | 부호는 −(U+2212) |

### 면과 모서리

- 데이터 면은 평평하다: 1px `--line`, 모서리 0, 카드 사이 간격 0(선 공유, `surface-grid`·`surface-stack`), 그림자 없음.
- 모서리: 컨트롤 필 999px(`rounded-control`) · 배지 6(`rounded-badge`, 높이 22) · 패널 0(`rounded-card`) · 기상도 20(`rounded-weather`) · 오버레이 12(`rounded-overlay`). 그림자는 오버레이에만(`shadow-overlay`).
- 분위기(그라디언트 필드 + 세로 리브 + 유리 패널, blur 18)는 **홈 상단 기상도에만** 쓴다(`.weather`·`.glass`). 분홍·파랑 타원의 크기·농도는 `--weather-up`(상승 비율 0~1)을 따른다. 투명도 줄이기(`prefers-reduced-transparency`)·blur 미지원이면 불투명 면(`--glass-opaque`)으로 바뀐다.

### 색의 의미

- 등락색 = 브랜드색. 상승 분홍(다크 오렌지), 하락 파랑, 0은 회색. **가격 방향에만** 쓴다. 숫자 글자는 `text-up-ink`·`text-down-ink`.
- 버튼·선택 상태는 글자색(`--action`)으로 칠한다. 등락색을 버튼에 쓰지 않는다.
- AI 해석은 보라 라벨 행 + 옅은 보라 틴트(`shared/AiBlock`). 좌측 보더 강조 금지. 사실 확인은 초록, 지연·미평가는 `--warn`.
- 차트 시리즈는 회색(`--series`), 선택한 시리즈만 굵은 선. 값 라벨만 등락색. 선택 선의 색은 화면 시안을 따른다 — Peer 성과 비교·업종 간 비교·산업 섹터 Peer 그룹은 분홍(`--up`) 굵은 선 + 분홍 라벨(`--up-ink` 600, 시안 Explore-Peers·Industry-Sector), Peer 구성 종목 차트 위에는 범례 칩 줄(고른 종목 = 분홍 테두리·틴트 칩, 나머지 회색 점 칩), 실적 시즌 섹터는 글자색 굵은 선. 다중 선 차트는 값 상자 대신 선 끝 라벨 한 열(이름 `--ink-2`, 고른 것 600, 값만 등락색, 13~15px 간격으로 겹침 풀기) — lightweight-charts는 `MultiLineChart endLabels`(축 왼쪽), Recharts는 `season/SectorView`의 `EndLabels`. 폰은 라벨 없이 선만.

### 컴포넌트 기본값 (shadcn 동작은 그대로, 스타일만)

| 컴포넌트 | 기본 |
|---|---|
| Button | 필. 기본 36 · sm 32 · lg 44 · xs 28. `default`=글자색 채움, `outline`=선 `--line-2`, `secondary`=chip, `ghost`=글자 ink-2, `ai`=보라 틴트(AI 생성 행동만) |
| Badge | 높이 22 · 모서리 6 · 12px. `neutral`(=default·secondary) · `outline` · `up` · `down` · `hyp` · `fact` · `warn` |
| Input · Select · Textarea | chip 바탕, 테두리 없음, 포커스 링 글자색 2px. Input·Select는 필 |
| Tabs · ToggleGroup(SegmentTabs·PeriodToggle) | chip 바탕(모서리 10, 안쪽 3) 안에 항목 모서리 8 · 선택 = 표면색 + 1px 선 |
| Table | 머리 12px `--ink-3` + `--line-2` 아래선, 셀 13px, 숫자 열은 오른쪽 정렬 |
| Dropdown · Popover · Command · Dialog · Select 목록 · HoverCard | 모서리 12 + 그림자 + `--line-2` 테두리. 항목 모서리 8 |
| Tooltip | `--bg` 바탕 · `--line-2` 테두리 · 모서리 10 · 12.5px `--ink-2` |
| 블록 머리(home/BlockHead) | 대시보드형: 13.5px 600 + 아래선 · 기준 시각 11.5px + 점(신선 = `--fact`, 지연 = `--warn`) · 링크 12px `--ink-2`. `section`(홈 시장 탭·시안 Home-KR/US): 선 없음 · 15px 600 · 칸 여백 16 · 링크 13px, 블록 사이 16. `display`(Market Overnight/Today): Geist 24 · 유리 알약 링크 · 칸 여백 22 · 둥근 16 |
| 상세(shared/DetailLayout, 시안 Doc) | 위 행동 줄(outline 알약 · 원문 링크는 ghost) → 본문 칸(표면·선, 여백 22/26) \| 맥락 칸 260(표면·선, 제목 15/600 + ⓘ). 폰은 칸 없이 본문, 제목 22/600 |
| 5-state | Skeleton = chip 사각형(모서리 0) · 오류(BlockError·ErrorState·WidgetState) = `--surface-2` 상자 + `--line-2` 선 · 경고 아이콘 + 13px 문구 + '다시 시도'(outline 30) · '자세히' |
| 페이지 제목 | PageHeader Geist 400 30/36(폰 26). 홈 하위 탭(한국·미국·매크로)은 화면 제목 없이 하위 메뉴 칩이 대신한다(sr-only h1) |

## 2026-10-31 · 화이트 플랫 공통 기준 (D-320에서 토큰·서체·모서리·등락색 대체, 평평한 면은 유지)

이 절은 아래의 과거 표면·라운딩·카드 간격 규칙보다 우선한다.

- 라이트 모드의 페이지·사이드바·카드·위젯 헤더는 순백색(`--background`, `--sidebar`, `--card`). 다크 모드의 대비 색상은 유지한다.
- 카드·읽기 패널은 `--radius-card: 0`, 그림자·광택·블러 없이 얇은 테두리로 구분한다. 선택·오류·경고·AI 해석의 의미 색상은 유지한다.
- 카드 묶음에는 `surface-grid` 또는 `surface-stack`을 지정한다. 카드 간격은 0, 카드 본문 패딩은 홈 위젯과 같은 12px, 헤더는 가로 12px·세로 8px이다. Card 자체의 중복 세로 패딩과 헤더/본문 사이 gap은 0이다. 제목·필터·서로 다른 섹션은 12px 간격을 기본으로 하며 폼 필드 간격과 문서 읽기 여백은 유지한다.
- 버튼·입력·탭의 control 라운딩, 아바타·상태 점·차트 모양, 오버레이의 구분용 그림자와 포커스 링은 유지한다.
- 홈은 별도 시안 쿼리 없이 동일한 기본 스타일이다. 저장된 배치 단위(22px)는 유지하고 여백을 카드 면적으로 흡수한다. 데스크톱·모바일 모두 카드 간격은 0이다.
- Loading / Empty / Partial / Error / Ideal의 데이터·행동·메시지는 그대로 유지한다. 표면 변화가 상태 표시를 지우지 않는다.

## 2026-09-10 점검 상태

### 승인된 통합안 — 구현 계약 (D-152, D-153)

첫 적용 범위는 전역 토큰·Card/Button/Input 기본값, 공통 페이지 레이아웃, 홈·통합 피드·문서 검색, 도크 재질이다. 나머지 페이지의 개별 조합과 임의 글자 크기는 후속 이행 대상으로 남긴다.

- 서체: 자체 호스팅 IBM Plex Sans / Sans KR 400·500·600·700. 페이지 24/32, 섹션 18/26, 카드 제목 16/24, 읽기 본문 14/22, UI 14/20, 캡션 12/18. 일반 콘텐츠 기본은 14px이며 Markdown h1/h2/h3는 20/18/16px로 본문보다 크게 유지한다. 숫자는 tabular-nums.
- 단색 중립 배경 + 기존 멀버리 액션색. 카드 radius 10px, control 8px, overlay 12px(2026-10-17 덜 둥글게 — 기본 `--radius` 8px, shadcn atom의 2xl~4xl은 10~12px로 묶음, 탭 목록 8px·배지 4px대). 카드 패딩 20px(모바일 16px), 열 간격 24px. 그림자는 오버레이에 제한.
- PageLayout의 header / overview / toolbar / footer / children 슬롯. mode=document|workspace|reader, width=full|reading. 문서형은 페이지 스크롤. SplitWorkspace는 label·content·surface를 가진 두 패널을 조합하고 URL 상태는 페이지가 소유한다.
- Home은 상단 시장/피드 모드 전환. 시장 document는 가용 폭 1000px부터 모듈 2열. 피드 reader는 760px부터 300px 목록 + 연속 본문, 그 미만은 목록/본문 전환. reader는 본문 슬롯만 창 높이(`100dvh - --shell-offset`)로 고정하고 위 슬롯은 페이지 스크롤(D-209). 화면 높이 740px 미만은 문서 스크롤로 복귀한다. SplitWorkspace의 900px 두 열 계약은 다른 사용처를 위해 보존한다. 셸이 외부 여백·하단 여백(--dock-reserve)과 --shell-offset을 소유한다.
- 피드는 하나의 둥근 표면 + 아티클 구분선. 카드/행 표현은 FeedPost의 명시적 variant로 구분하며 데이터 모델·링크·필터·펼침은 보존한다.
- 브리핑은 일반 Card 표면을 사용한다. 별도 반전 대비는 해제했다. 날짜·데이터·차트·상태·새로고침 기능은 보존한다.
- 글래스는 일부 탐색 버튼만. reduced-transparency / 미지원 브라우저에서는 불투명 배경으로 폴백한다.
- 공식 shadcn/Radix의 동작·API는 유지하며 기반 스타일의 관리된 수정을 허용한다. 기존 ui/ 수제작 금지는 새 동작 재구현에 적용하고, 승인된 토큰·기본값 수정은 허용한다.

- DetailLayout은 PageLayout 위에서 복귀/context/header/actions/navigation/body/aside/related를 조합한다. /doc, 주제 내러티브, 버전 상세에 적용했다. 본문 최대 760px, 보조 220px는 가용 폭 1000px부터 옆에, 그 미만은 아래로 배치한다. 단일 Card 표면·14px 본문·24px 제목. 상세에서는 팔로우 레일과 월드모델 서브탭을 기본 크롬에서 내린다.
- 원문/요약·내러티브 상세 탭·선택 버전은 URL에 보존한다. DetailLink는 출발 경로/이력 상태를 전달하고, 탭 단위 UI 메모리는 스크롤·포커스만 최대 100개 보존한다. 직접 링크는 출처·목록 fallback을 사용한다.

아래 과거 규칙과 충돌하면 이 구현 계약을 우선한다. 적용 범위와 남은 이행 작업은 DESIGN_REVIEW에서 관리한다.

시각 방향을 **마켓 홈 통합안**으로 좁혔다: 나의 마켓 홈의 둥근 표면·대비 브리핑, 정밀한 분석 데스크의 하나로 이어지는 피드, 도크·일부 탐색 요소의 절제된 글래스. 배경은 단색이며 무지개 형태의 다색 그라데이션은 사용하지 않는다. 기존 제품 사례 HTML(로컬 전용 `prototypes/product-design-study.html`)의 기본 화면을 이 조합으로 갱신했다. 채택된 라운딩·테마·서체는 위 구현 계약에 반영했다. HTML은 비교 이력으로 유지한다.

제품 사례 연구·시각 방향 3안(로컬 전용 `prototypes/product-design-study.html`)은 Revolut·Stripe·Apple·Linear·Mercury의 공식 자료를 바탕으로 균형형 레이아웃의 표면·정보 위계·상호작용을 비교한다. 글래스는 탐색 층에 한정한 후보이며, 기존 토큰 기획안과 다른 크기·라운딩은 채택 시 이 문서의 단일 기준으로 통합한다. 채택된 통합안은 위 구현 계약으로 적용했다.

레이아웃 방향은 **균형형 워크스페이스**다. 디자인 토큰·컴포넌트 HTML 기획안(로컬 전용 `prototypes/balanced-design-system.html`)에서 IBM 타이포그래피, 색상·밀도, 컴포넌트 계약, 페이지 슬롯 및 단계별 적용을 검토한다. 당시 제안 중 채택된 값은 위 구현 계약에 통합했다. 앞선 레이아웃 3안(로컬 전용 `prototypes/page-layout-concepts.html`)은 비교 이력이다.

DESIGN_REVIEW(비공개 문서)에 전체 코드 감사와 IBM Plex 기반 재설계 제안을 정리했다. 아래는 기존 규칙이며 코드와 불일치하는 항목(특히 CardHeader grid/flex, 카드 radius, 글자 크기)이 있다. **IBM Plex Sans/KR은 현재 자체 호스팅 폰트로 적용됐다.** 디자인 기준 개편 시 이 문서를 갱신하고, 감사/후속 문서를 별도로 늘리지 않는다.

## 원칙 (astryx에서 차용)

1. **테마 = CSS 커스텀 프로퍼티 오버라이드 집합.** 색·라운딩은 `index.css`의 `:root`(light) / `.dark`에서만 정의하고, 컴포넌트는 semantic 토큰만 소비한다. 하드코딩 hex 금지.
2. **강한 컨벤션.** 같은 패턴은 한 가지 방식으로만 구현한다 (세그먼트 토글 4종 난립 금지 → ToggleGroup 하나).
3. **조합 가능성.** shadcn atom(ui/)을 잠그지 말고 shared/에서 조합해 서비스 컴포넌트를 만든다. 최상위 API 뒤에 감추지 않는다.
4. **사람과 에이전트 모두를 위한 문서.** 이 문서는 LLM이 새 화면을 만들 때 그대로 따를 수 있게 규칙·예외를 명시한다.

## 1. 레이아웃 컨트랙트

### 셸 (App.tsx Layout — 상단 6탭 · 2칸, docs/specs/app-shell.md)

```
<TooltipProvider>
    <Omnibar/>                            ⌘K 오버레이 (CommandDialog)
    <div flex-col min-h-svh>
      <TopBar/>                           sticky · h-(--topbar-height)=65px(폰 57px, 검색·AI만 — 로고 'Explorer'를 누르면 아래 시트에 인박스·저장됨·관리자·테마, D-322) · L1 6탭(홈·피드·탐색·산업·포트폴리오·Thesis)·검색·운영 상태(Popover)·인박스·설정·AI 토글
      <div flex>
        <main>                            본문
          <div mx-auto max-w-[var(--layout-shell)] px-6 pt-6 pb-[var(--dock-reserve)]>
            <SubNav/>                     L2 (탭이 둘 이상일 때, h-8 + mb-5 = --subnav-height)
            ← 페이지 렌더 슬롯
          </div>
        </main>
        <ChatPanel/>                      aside sticky · w-(--ai-panel-width)=360px · /chat에서는 숨김 · <1024는 Sheet
      </div>
      <TabBar/>                           <768 하단 L1 6탭 (fixed, --tabbar-height + 안전 영역)
    </div>
</TooltipProvider>
```

- 폭 상한 토큰: `--layout-shell: 1440px` (index.css). 본문 슬롯이 이 토큰을 쓴다.
- 풀하이트 화면은 `calc(100dvh - var(--shell-offset))`. 셸이 상단 바·여백·L2 유무로 `--shell-offset`을 확정한다.
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
| 도메인: 주가 | `--up`·`--up-ink`·`--up-tint`(분홍/다크 오렌지) `--down`…(파랑) | D-320. 등락 표시는 이 둘만, 가격 방향에만 |
| 도메인: 인식론 | `--fact`(초록) `--hyp`(보라, 별칭 `--hypothesis`) `--warn`(주의) | LLM 산출 = hyp(AiBlock), 지연·미평가 = warn |
| 차트 | `--color-chart-revenue/profit/ratio/negative/warning`, `--color-chart-1~5` | 신규 차트는 semantic 우선, 팔레트(1~5)는 시리즈 나열용 |
| 레이아웃 | `--layout-shell` `--dock-height` `--dock-reserve` `--subnav-height` `--shell-offset` | §1 참조 |
| 라운딩 | `--radius-control`(999) `--radius-badge`(6) `--radius-card`(0) `--radius-weather`(20) `--radius-overlay`(12). `--radius`(8) 파생 sm·md·lg = 4·6·8, xl~4xl = 12 | 위 현행 계약 참조 |

폰트: Google Fonts — Geist·Geist Mono·IBM Plex Sans KR·Instrument Serif. 숫자는 `tabular-nums`(Geist Mono로 바뀜), td/th는 tabular 자동.

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
| AI 해석 문장(LLM 산출) | **shared/AiBlock** — 보라 라벨 행 + 틴트, 좌측 보더 금지 |
| 홈 상단 분위기 | `.weather`(그라디언트·리브, `--weather-up`) + `.glass`(유리 패널) — home/HomeDashboard 기상도에만 |
| 패널 안에서 더 보기(요약 → 전체) | **shared/DropletReveal** — `ui/collapsible` 위 조합. 패널을 덮으며 Droplet reveal 모션으로 펼치고 패널 높이를 바꾸지 않는다(아래 §모션) |

### 허용된 예외 (grandfathered — 신규 작성 금지, 점진 이관)

| 파일 | 사유 |
|---|---|
| `actions/RightsProTable.tsx` | sticky 첫 컬럼 + `w-max` 밀집 테이블 — raw table 유지, `overflow-x-auto` 래퍼 필수 |
| `discovery/ScreenerPage.tsx` 내부 Th/Td | 정렬 헤더 로컬 헬퍼 — 토큰 준수 확인됨 |
| `layout/SubNav.tsx` · `layout/Dock.tsx` 모드 Link | 라우터 연동 네비 — Radix Tabs 의미론(패널 전환)과 다름. Link(pill) 유지. 도크 아이템은 ui/button 기반 |

이 표에 없는 raw HTML atom 사용은 전부 위반이다.

## 모션

이름 붙은 모션만 쓴다. 새 모션이 필요하면 여기와 `index.css` `@theme`에 이름을 먼저 등록하고 재사용한다. 운영체제 '동작 줄이기'가 켜지면 전역 규칙이 모든 애니메이션을 끈다(index.css).

| 이름 | 토큰 · 클래스 | 동작 | 쓰는 곳 |
|---|---|---|---|
| **Droplet reveal**(물방울 등장) | `--animate-droplet` · `animate-droplet` (680ms) + 내용 `animate-droplet-rise` (520ms, 200ms 지연) | 패널 바닥 가운데부터 원이 퍼지며(clip-path circle) 흐림이 걷히고, 내용은 아래에서 살짝 떠오른다 | 요약 패널에서 전체 내용 펼치기 — `shared/DropletReveal`(홈 Market Overnight '브리핑 전체 보기' 등). 화면 전체를 덮는 오버레이는 `ui/sheet`·`ui/dialog`를 쓴다 |

## 4. 신규 화면 체크리스트

- [ ] 최상위 `<PageContainer>` (width·gap 선택) — 자체 max-w/padding 없음
- [ ] 그리드는 `grid-cols-1`에서 시작하는 반응형
- [ ] 넓은 표는 ui/table 또는 `overflow-x-auto` 래퍼
- [ ] 색상은 semantic 토큰만 · 등락=up/down · LLM 산출=hypothesis
- [ ] 5-state (Empty/Loading/Partial/Error/Ideal) + 기준 시각(블록 머리 `BlockHead`의 `asOf`)
- [ ] 숫자 포맷은 utils/format.ts
- [ ] 새 atom 필요 시 `npx shadcn@latest add <c>` CLI 설치 (수제 금지)
