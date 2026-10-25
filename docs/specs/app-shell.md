# 앱 셸 — 상단 5탭 · 3칸 (내 목록 · 본문 · AI 대화)

- 상태: P3a 구현 계약 (2026-10-16). [dock-navigation](dock-navigation.md)과 [follow-rail](follow-rail.md)을 대체한다.
- 범위: 상단 바, L1·L2 내비게이션, 왼쪽 '내 목록', 오른쪽 'AI 대화' 패널, 데스크톱 전용 안내, 단축키.
- 범위 밖(후속): URL 체계 이전(`/canvas/*`, `/explore/*` 등)과 리다이렉트(P3b), 홈 위젯 대시보드(P4), 하위 탭 안 화면 통합(P5~P7). P3a에서 새 탭은 지금 URL을 가리킨다.

## 1. 배치

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ◧ Explorer     홈  탐색  포트폴리오  캔버스  월드모델    [검색 ⌘K] ● 운영 ⓘ ⚙ ◨ │  상단 바 52px
├──────────────┬──────────────────────────────────────────────┬───────────────┤
│ 내 목록        │ L2 하위 탭 (탭이 둘 이상일 때)                    │ AI 대화         │
│ (Sidebar)    │ 본문 (Outlet)                                  │ (aside 360px)  │
└──────────────┴──────────────────────────────────────────────┴───────────────┘
```

| 영역 | 컴포넌트 | 기본 상태 | 토글 |
|---|---|---|---|
| 상단 바 | `layout/TopBar` | 항상. <768은 L1 탭 없이 아이콘만 | — |
| 하단 탭바 | `layout/TabBar` | 폭 <768에서만 (L1 5탭) | — |
| 내 목록 | `layout/MyListPanel` (shadcn Sidebar, 왼쪽) | 폭 ≥1440 펼침, 아래는 접힘. <768은 Sheet | 상단 ◧, ⌘B |
| AI 대화 | `chat/ChatPanel` (aside) | 폭 ≥1440 펼침, 아래는 접힘. <1024는 오른쪽 Sheet. `/chat`에서는 숨김 | 상단 ◨, ⌘J |

패널 열림 상태는 화면 상태가 아니라 사용자 편의라 localStorage에 둔다(`explorer.shell.left`, `explorer.shell.ai`). 읽기·쓰기 실패 시 기본값.

## 2. 내비게이션 (navConfig 단일 소스)

| L1 | L2 → 현재 URL | 이 L1로 판정하는 경로 |
|---|---|---|
| 홈 | 대시보드 `/home` | `/home` (단 `home_view=feed` 제외) |
| 탐색 | 종목 발견 `/discover` · 신호 `/explore` · 컨콜 `/follow/transcripts` · 산업·섹터 `/map` · 수출입 `/follow/trade` · 회사채 `/follow/credit` · 인물 `/people` · 기업활동 `/actions` | `/discover`, `/analysis/backtests`, `/explore`, `/follow/transcripts`, `/us`(목록), `/map`, `/follow/universe`, `/discover/industry`, `/follow/trade`, `/follow/credit`, `/people`, `/person`, `/actions` |
| 포트폴리오 | 개요 `/portfolio` · 종목 묶음 `/follow/stocks` | `/portfolio`, `/follow/stocks`, `/follow` |
| 캔버스 | 피드 `/home?home_view=feed` · 스터디 `/study` · 저장됨 `/follow/saved` · 소스 `/sources` | `home_view=feed`, `/feed`, `/doc/`, `/source`, `/synthesis/`, `/study`, `/follow/saved`, `/sources` |
| 월드모델 | 지금 `/narrative` · 그래프 `/knowledge/ontology` · 내 판단 `/questions` | `/narrative`, `/knowledge`, `/questions`, `/question/`, `/thesis`, `/report` |

- 하위 탭 판정: 위 표의 '판정 경로'를 L2 단위로도 같은 규칙으로 묶는다(예: `/us`·`/follow/transcripts` → 컨콜, `/follow/universe`·`/discover/industry` → 산업·섹터, `/thesis`·`/report`·`/question/` → 내 판단, `/knowledge` → 그래프).
- 종목 도시에(`/analyze/:code/*`, `/us/:ticker`, `/company`)는 L1이 아니다. L1은 비활성으로 두고, L2 자리에 도시에 탭(개요·실적·사업·자료)과 종목명을 보인다(기존 `analyzeTabs`).
- `/chat`, `/admin`, `/archive` 등은 L1 비활성, L2 없음.
- `/feed?view=documents`(문서 검색)는 캔버스 › 피드 안에서 기존 소스 탭(`FEED_TABS`)을 L2로 보인다.

## 3. 상단 바

왼쪽부터: 내 목록 토글 · 로고(→ `/home`) · L1 5탭(react-router `NavLink`, 활성은 아래 2px 선) · 검색 버튼(옴니바 열기, ⌘K) · 운영 상태 점(`GET /api/spine/admin/health`: 전부 ok면 초록, stale·error가 있으면 주황 + 개수, 클릭 → `/admin`) · 승인 인박스 · 저장 인박스(기존 `Inboxes`) · 설정 메뉴(shadcn DropdownMenu: 테마, 소스 관리, 관리자, 보관함) · AI 대화 토글.

## 4. 내 목록 (MyListPanel)

| 섹션 | 원천 | 행 |
|---|---|---|
| 종목 묶음 | `GET /api/spine/groups` + 선택한 묶음의 `GET /api/spine/groups/{id}` | 묶음 칩(포트폴리오·관심 …) → 종목 이름 · 등락률(상승 빨강/하락 파랑) → 클릭 시 도시에 |
| 최근 본 종목 | 옴니바 최근 종목(localStorage, `lib/recentStocks`) | 이름 → 도시에 |
| 팔로우 인물 | `GET /api/spine/follows` (인물) | 이름 → `/person?name=` |
| 저장됨 | 개수 + `/follow/saved` 링크 | — |

진실원천은 `stock_groups`다. 레거시 `watchlist`는 읽지 않는다. 텔레그램·블로그·유튜브 채널 목록은 캔버스 › 소스로 옮긴다(기존 FollowRail의 소스 섹션은 이 패널에 두지 않는다).

5-state: 묶음 로딩 중 Skeleton 3행, 묶음 0개면 "종목 묶음을 만들면 여기 보입니다" + `/follow/stocks` 링크, 오류면 섹션별 다시 시도.

## 5. AI 대화 패널 (ChatPanel)

- `/chat`의 부품을 그대로 쓴다: `useChat`, `AssistantMessage`, `UserMessage`, `Composer`, 드래그 인용. 폭 360px 기준으로 본문 15px → 14px.
- 스레드: 패널 머리의 '대화 목록' 버튼 → Popover 안 `ThreadRail`. 새 대화 버튼. 활성 스레드 id는 localStorage(`explorer.shell.thread`). '전체 화면' 버튼 → `/chat?id=`.
- **화면 맥락**: 현재 위치를 `page_context`로 질문과 함께 보낸다. 머리 아래 칩 "보는 화면: {label}"을 보이고 × 로 이번 질문에서 뺄 수 있다.

```ts
interface PageContext {
  kind: 'stock' | 'us_stock' | 'doc' | 'narrative' | 'question' | 'page'
  label: string        // '종목 SK하이닉스(000660) · 개요', '홈 · 대시보드'
  path: string         // 현재 경로+쿼리
  ref?: string         // stock_code | ticker | doc_id | topic | question id
}
```

- 백엔드: `POST /api/spine/ask` 본문에 `page_context?: PageContext`. 라우터·종합 프롬프트에 "[사용자가 지금 보고 있는 화면]" 블록으로 들어가 '이 종목·이 문서' 같은 지시어를 해석하게 한다. 사용자 메시지 본문에는 저장하지 않는다(대화 기록은 질문 원문만). 스터디 맥락·드래그 인용과 함께 올 수 있다.
- 답변 도착 전역 알림(AnswerWatcher)은 그대로. 패널이 열려 있고 같은 스레드면 토스트를 띄우지 않는다.

## 6. 좁은 화면 (2026-10-25, 데스크톱 전용 안내 대체)

모든 폭에서 앱을 쓴다. 분기점은 `hooks/useMediaQuery`의 두 쿼리.

| 폭 | 상단 바 | L1 | 내 목록 | AI 대화 |
|---|---|---|---|---|
| ≥1024 | 전체(검색 버튼은 ≥1280에서 넓게, 아래는 아이콘) | 상단 가운데 | 옆 칸(offcanvas) | 옆 칸 360px |
| 768–1023 | 로고 글자 숨김 | 상단 가운데 | 옆 칸(offcanvas) | 오른쪽 Sheet(최대 28rem) |
| <768 | 내 목록·로고·검색·인박스·설정·AI 아이콘. 운영 상태 점은 숨김(설정 › 관리자로 접근) | 하단 `TabBar` | Sheet(고르면 닫힘) | 전체 폭 Sheet(화면을 옮기면 닫힘) |

- 하단 탭바 높이 `--tabbar-height`(3.5rem) + 안전 영역. <768에서 `--dock-reserve`가 탭바를 포함하므로 `--shell-offset`을 쓰는 풀하이트 화면은 따로 계산하지 않는다.
- 좁은 화면에서 패널을 여닫아도 데스크톱 기본값(`explorer.shell.*`)에 쓰지 않는다. <1024에서는 패널이 늘 닫힌 채 시작한다.
- L2는 본문 첫 줄 SubNav가 가로 스크롤로 맡는다.
- 홈 위젯은 <768에서 1열 읽기 전용(home-widgets.md §1).

## 7. 단축키

| 키 | 동작 |
|---|---|
| ⌘K, `/` | 옴니바 |
| ⌥1~5 | 홈 · 탐색 · 포트폴리오 · 캔버스 · 월드모델 |
| ⌘B | 내 목록 토글 |
| ⌘J | AI 대화 토글 (열 때 입력창 포커스) |

## 8. 높이 계약

전체 높이 화면(대화·리더·워크스페이스)은 `calc(100dvh - var(--shell-offset))`를 쓴다. 셸이 `--shell-offset = 상단 바(52px) + 본문 위아래 여백 + (L2가 있으면) L2 높이`를 확정한다. 하단 도크 예약(`--dock-reserve`)은 본문 아래 여백으로만 남긴다.

## 9. 검증

- `npx tsc --noEmit -p tsconfig.app.json`, `node --test frontend/tests/*.test.mjs`(navConfig 판정 표 테스트 포함)
- 실제 화면: L1 5개·대표 L2 각 1개 진입, 도시에 진입 시 L2 대체, 패널 토글·단축키, 대화 패널에서 질문 → 답변 도착, 1023px에서 안내 화면
- 백엔드: `page_context`가 라우터 프롬프트에 들어가고 메시지 저장에는 안 들어가는 테스트
