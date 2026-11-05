# 앱 셸 — 상단 6탭 · 2칸 (본문 · AI 대화)

- 상태: P3a 구현 계약 (2026-10-16). [dock-navigation](dock-navigation.md)과 [follow-rail](follow-rail.md)을 대체한다.
- 2026-11-04 화면 구조 개편 1단계(C안): 대메뉴 6개(홈 · 피드 · 탐색 · 산업 · 포트폴리오 · Thesis), 캔버스 없앰, 왼쪽 '내 목록' 제거, 운영 상태는 누르면 창. 라우트는 그대로 두고 메뉴만 바꿨다(리다이렉트·새 주소는 이후 단계).
- 2026-11-05 개편 3단계(3a): 홈 L2 = 시스템 고정 탭 다섯 개(대시보드 · 한국 시장 · 미국 시장 · 매크로 · 내 종목, [home-widgets §0](home-widgets.md)). 사용자 메뉴(`home_boards`) 탭과 '+ 새 메뉴'는 없앴고 옛 홈 주소는 리다이렉트한다.
- 범위: 상단 바, L1·L2 내비게이션, 오른쪽 'AI 대화' 패널, 좁은 화면, 단축키.
- 범위 밖(후속): URL 체계 이전(`/canvas/*`, `/explore/*` 등)과 리다이렉트(P3b), 홈 위젯 대시보드(P4), 하위 탭 안 화면 통합(P5~P7). P3a에서 새 탭은 지금 URL을 가리킨다.

## 1. 배치

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ E Explorer   홈  피드  탐색  산업  포트폴리오  Thesis   [검색 ⌘K] ● 운영 ⓘ ⚙ ◨ │  상단 바 52px
├─────────────────────────────────────────────────────────────┬───────────────┤
│ L2 하위 탭 (탭이 둘 이상일 때)                                   │ AI 대화         │
│ 본문 (Outlet)                                                 │ (aside 360px)  │
└─────────────────────────────────────────────────────────────┴───────────────┘
```

| 영역 | 컴포넌트 | 기본 상태 | 토글 |
|---|---|---|---|
| 상단 바 | `layout/TopBar` | 항상. <768은 L1 탭 없이 아이콘만 | — |
| 하단 탭바 | `layout/TabBar` | 폭 <768에서만 (L1 6탭) | — |
| AI 대화 | `chat/ChatPanel` (aside) | 폭 ≥1440 펼침, 아래는 접힘. <1024는 오른쪽 Sheet. `/chat`에서는 숨김 | 상단 ◨, ⌘J |

패널 열림 상태는 화면 상태가 아니라 사용자 편의라 localStorage에 둔다(`explorer.shell.ai`). 읽기·쓰기 실패 시 기본값.

## 2. 내비게이션 (navConfig 단일 소스)

| L1 | L2 → 현재 URL | 이 L1로 판정하는 경로 |
|---|---|---|
| 홈 | 대시보드 `/home` · 한국 시장 `/home/kr` · 미국 시장 `/home/us` · 매크로 `/home/macro` · 내 종목 `/home/stocks` | `/home` (단 `home_view=feed` 제외)·`/home/b/:id`(→ `/home`) → 대시보드, `/home/kr`·`/retail`·`/actions`(→ `/home/kr#actions`, `?code=X`는 → `/analyze/X/summary#actions`) → 한국 시장, `/home/us`·`/home/briefing`(→ `/home/us`) → 미국 시장, `/home/macro`·`/home/risk`(→ `/home/macro`)·`/regimes`(→ `/home/macro#history`) → 매크로, `/home/stocks` → 내 종목 |
| 피드 | 피드 `/feed` · 저장됨 `/feed/saved` | `/feed`, `/doc/`, `/source`, `/feed/saved`, 옛 `/home?home_view=feed`(→ `/feed`)·`/follow/saved`(→ `/feed/saved`) |
| 탐색 | 종목 발견 `/discover` · Peer 그룹 `/discover/peers` · 컨콜 `/follow/transcripts` · 인물 `/people` | `/discover`, 옛 `/explore`(→ `/discover#signals`) → 종목 발견, `/discover/peers`, 옛 `/analyze/compare`(→ `/discover/peers`) → Peer 그룹, `/follow/transcripts`, 옛 `/us`(→ `/follow/transcripts`) → 컨콜, `/people`, `/person` |
| 산업 | 산업·섹터 `/map` · 수출입 `/follow/trade` · 대만 공급망 `/follow/taiwan` · 밸류체인 `/value-chain` · 회사채 `/follow/credit` | `/map`, `/follow/universe`, `/discover/industry`, `/follow/trade`, `/follow/taiwan`, `/value-chain`, `/follow/credit` |
| 포트폴리오 | 개요 `/portfolio` · 보유 · 원칙 · 일정 · 종목 묶음 `/follow/stocks` | `/portfolio`, `/follow/stocks`, `/follow` |
| Thesis | 지금 `/narrative` · 그래프 `/knowledge/ontology` · 내 판단 `/questions` · 스터디 `/study` | `/narrative`, `/knowledge`, `/questions`, `/question/`, `/thesis`, `/report`, `/proxy-boards`(→ `/questions?view=proxies` 리다이렉트), `/study` |

- *기울임* 탭은 이행 중이다. 대체 화면(종목 발견 '오늘의 신호', 도시에 개요의 기업활동)이 생기면 옛 경로를 리다이렉트로 바꾸고 탭을 뺀다. 옛 경로를 대체 화면보다 먼저 지우지 않는다. 탐색 › 신호는 2026-11-05(개편 4c)에 종목 발견 첫 화면 '오늘의 신호'로 옮겨 탭을 뺐다 — `/explore`는 `/discover#signals`로(`?list=<type>`은 `?signal=<type>` 목록 시트로), `/discover/signals`도 같은 곳으로. 기업활동 탭은 2026-11-05(후속 묶음, D-300)에 뺐다 — 시장 전체 목록은 홈 › 한국 시장 `#actions` 블록으로 옮겼고 `/actions`(코드 없음)는 `/home/kr#actions`로 리다이렉트(쿼리 유지), `/actions?code=X`는 2026-11-05(개편 4e) 그 종목 도시에 개요 `#actions`로 리다이렉트(쿼리 유지, 리다이렉트 전 판정은 홈 › 한국 시장). 산업 › 국면 이력은 2026-11-05(개편 3c)에 홈 › 매크로로 옮겨 탭을 뺐다 — `/regimes`는 `/home/macro#history`로 리다이렉트(쿼리 유지, 해시는 쿼리 뒤).
- 대만 공급망 탭(`/follow/taiwan`)은 2026-11-05(개편 4b)에 더했다. 홈 › 한국 시장 맨 아래에 임시로 있던 대만 두 블록은 이 화면으로 옮겼다(위젯 `explore.twRevenue`·`explore.twLinks`의 전체 보기도 이 주소).
- Thesis의 코드 key는 `world` 그대로다(이름만 바꿈).
- 소스 관리는 관리자 › 소스(`/admin/sources`, 관리자 보기 = 작업·신선도 · 관측 · 소스 · 자동 정리)다(2026-11-05 개편 4a, 자동 정리 `?view=curation`은 4h). 옛 `/admin?view=sources`는 `/admin/sources`로 보낸다. 옛 `/sources`는 리다이렉트(쿼리 유지). 설정 메뉴 '소스 관리'·⌘K·피드 왼쪽 칸 '소스 관리'가 이리로 온다.
- 하위 탭 판정: 위 표의 '판정 경로'를 L2 단위로도 같은 규칙으로 묶는다(예: `/us`·`/follow/transcripts` → 컨콜, `/follow/universe`·`/discover/industry` → 산업·섹터, `/thesis`·`/report`·`/question/` → 내 판단, `/knowledge` → 그래프 — 2026-11-05부터 `/knowledge`는 `/knowledge/ontology`로 리다이렉트).
- 종목 도시에(`/analyze/:code/*`, `/us/:ticker`, `/company`)는 L1이 아니다. L1은 비활성으로 두고, L2 자리에 도시에 탭(개요·실적·사업·자료)과 종목명을 보인다(기존 `analyzeTabs`).
- `/chat`, `/admin`, `/admin/sources`, `/archive` 등은 L1 비활성, L2 없음.
- `/feed?view=documents`(문서 검색)도 L2는 피드 · 저장됨이다. 문서 검색의 소스 칩은 화면 안에 있다(옛 `FEED_TABS` L2는 4a에서 없앰).

## 3. 상단 바

왼쪽부터: 로고(→ `/home`) · L1 6탭(react-router `Link`, 활성·`aria-current`는 `locate()` 판정 — `NavLink`는 쿼리를 보지 않아 `/home?home_view=feed`에서 홈까지 활성으로 잡으므로 쓰지 않는다. 활성은 아래 2px 선) · 검색 버튼(옴니바 열기, ⌘K) · 운영 상태(`GET /api/spine/admin/health`: 전부 ok면 초록, stale·error가 있으면 주황 + `운영 n/m`. 누르면 shadcn Popover 창 — 요약 한 줄, 지연·오류 목록[이름 · 핵심 표시 · 지연/오류 · 사유], '관리자 화면 ›') · 승인 인박스 · 저장 인박스(기존 `Inboxes`) · 설정 메뉴(shadcn DropdownMenu: 테마, 소스 관리, 관리자, 보관함) · AI 대화 토글.

**검색(옴니바, ⌘K) 배치**(2026-11-05 개편 4j, 시안 Search · ia-redesign §4.14): 빈 상태 = 최근 본 종목(행 + 국내/미국 배지) · 오늘 켜진 신호(종목 · 규칙 · 묶음 · 날짜, '내 종목에서 전체 보기' → `/home/stocks`) · 바로 가기 칩 6(종목 발견 · 대화 · 스터디 · 문서 검색 · 내 종목 · 실적 시즌). 결과 = 종목 행(이름 · 코드 / 시장 · 업종 · 시총 / 시세 · 등락 · 묶음 배지) · 미국 종목(국내 이름이 검색어로 시작하지 않으면 맨 위 — 미국 기업 탭 대신 주 진입로) · 묶음·프로젝트 · 인물·테마 · '이 글자로'(문서 검색 · 종목 발견 조건 검색). 종목 행에서 Tab = 종목 행동: 머리 줄(이름 · 코드 · 시장 · 시세) + 기업 개요 · 실적·사업 · 자료 · 가격·근거 조사(국내) · 묶음에 추가(고르는 단계) · 스터디 프로젝트에 자료 추가(국내, 고르는 단계). '이 종목으로 대화'는 대화 태그 기능(D-306)과 함께 정한다.

## 4. 내 목록 (제거됨, 2026-11-04)

왼쪽 사이드바 '내 목록'(`layout/MyListPanel`)과 그 토글(상단 ◧, ⌘B)을 없앴다. 데이터·API(`stock_groups`, 팔로우, 저장됨)는 그대로다. 종목 묶음은 포트폴리오 › 종목 묶음, 저장됨은 피드 › 저장됨과 상단 저장 인박스, 최근 본 종목은 옴니바에서 본다.

## 5. AI 대화 패널 (ChatPanel)

- `/chat`의 부품을 그대로 쓴다: `useChat`, `AssistantMessage`, `UserMessage`, `Composer`, 드래그 인용. 폭 360px 기준으로 본문 15px → 14px.
- 스레드: 패널 머리의 '대화 목록' 버튼 → Popover 안 `ThreadRail`. 새 대화 버튼. 활성 스레드 id는 localStorage(`explorer.shell.thread`). '전체 화면' 버튼 → `/chat?id=`.
- **화면 맥락**: 현재 위치를 `page_context`로 질문과 함께 보낸다. 입력 카드 첨부 칩 줄에 "보고 있는 화면 · {label}" 칩을 보이고 × 로 이번 질문에서 뺄 수 있다(2026-11-05 개편 4j, chat-page.md §8).

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

| 폭 | 상단 바 | L1 | AI 대화 |
|---|---|---|---|
| ≥1024 | 전체(검색 버튼은 ≥1280에서 넓게, 아래는 아이콘) | 상단 가운데 | 옆 칸 360px |
| 768–1023 | 로고 글자·운영 상태 숨김 | 상단 가운데 | 오른쪽 Sheet(최대 28rem) |
| <768 | 로고·검색·인박스·설정·AI 아이콘(누르는 칸 40px). 운영 상태는 숨김(설정 › 관리자로 접근) | 하단 `TabBar` 6칸(홈·피드·탐색·산업·포트폴리오·Thesis) | 아래에서 올라오는 Sheet(높이 88dvh, 화면을 옮기면 닫힘, 2026-11-05 4i) |

- 하단 탭바 높이 `--tabbar-height`(3.5rem) + 안전 영역. <768에서 `--dock-reserve`가 탭바를 포함하므로 `--shell-offset`을 쓰는 풀하이트 화면은 따로 계산하지 않는다.
- 좁은 화면에서 패널을 여닫아도 데스크톱 기본값(`explorer.shell.*`)에 쓰지 않는다. <1024에서는 패널이 늘 닫힌 채 시작한다.
- L2는 본문 첫 줄 SubNav가 가로 스크롤로 맡는다. <768에서는 줄 높이 h-10 + mb-3(합계는 데스크톱과 같다)으로 누르는 칸을 40px로 둔다.
- 상세 화면(`shared/DetailLayout`)은 <768에서 `mobileTop`(위 바를 줄인 버튼)·`mobileBar`(하단 탭 위 고정 행동 바)를 받는다. 문서 보기(`/doc/:id`)는 위 바 '‹ 출처로 · 원문 사이트 ›', 행동 바 '저장 · 스터디로 · 이 자료로 대화'. '이 자료로 대화'는 질문을 보내지 않고 AI 시트만 연다(`lib/aiPanel.openAi`, 보는 화면 칩 자동 첨부). 맥락 열은 본문 끝 블록(연결된 대상 + 출처 한 줄)으로, 복사 버튼·설명 줄은 숨긴다(ia-redesign §4.32).
- 홈 고정 탭의 섹션은 <768에서 1열로 쌓인다(home-widgets.md §0).

## 7. 단축키

| 키 | 동작 |
|---|---|
| ⌘K, `/` | 옴니바 |
| ⌥1~6 | 홈 · 피드 · 탐색 · 산업 · 포트폴리오 · Thesis |
| ⌘J | AI 대화 토글 (열 때 입력창 포커스) |

## 8. 높이 계약

전체 높이 화면(대화·리더·워크스페이스)은 `calc(100dvh - var(--shell-offset))`를 쓴다. 셸이 `--shell-offset = 상단 바(52px) + 본문 위아래 여백 + (L2가 있으면) L2 높이`를 확정한다. 하단 도크 예약(`--dock-reserve`)은 본문 아래 여백으로만 남긴다.

## 9. 검증

- `npx tsc --noEmit -p tsconfig.app.json`, `node --test frontend/tests/*.test.mjs`(navConfig 판정 표 테스트 포함)
- `tests/app-shell-nav.test.mjs`: App.tsx의 모든 라우트가 판정 표에 있는지(빠지면 실패), 각 라우트의 (L1, L2), 탭 순서, 탭 경로가 자기 탭으로 돌아오는지
- 실제 화면: L1 6개·대표 L2 각 1개 진입(데스크톱·390px), 도시에 진입 시 L2 대체, 운영 상태 창, 패널 토글·단축키, 대화 패널에서 질문 → 답변 도착, 1023px에서 안내 화면
- 백엔드: `page_context`가 라우터 프롬프트에 들어가고 메시지 저장에는 안 들어가는 테스트
