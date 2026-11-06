# 캔버스 — 피드 · 스터디 · 저장됨 · 소스

- 상태: P5 구현 계약 (2026-10-16). 셸은 [app-shell](app-shell.md), 피드 조회 계약은 [home-feed](home-feed.md), 스터디는 [study-mode](study-mode.md).
- 목적: 좋은 자료를 읽고, 공부하고, 남기는 작업대.
- 범위 밖(후속): URL 이전(`/canvas/*`)과 리다이렉트, 통합 타임라인(`/feed?feed_*`)·문서 교차 종합 같은 휴면 기능 정리(D-241에서 제거 완료).

| L2 | 지금 URL | 화면 |
|---|---|---|
| 피드 | `/feed` (4a, 옛 `/home?home_view=feed`) | `feed/FeedPage`·`feed/ChannelReader`(D-325 옛 리더 구성) — [home-feed](home-feed.md) '현행' |
| 스터디 | `/study` | 프로젝트 목록·책상, 단일 문서 스터디 |
| 저장됨 | `/feed/saved` (4a, 옛 `/follow/saved`) | 북마크 + 메모 |
| 소스 | `/admin/sources` (4a, 옛 `/sources`) | 텔레그램·블로그·뉴스·유튜브 등록·활성 |

## 1. 피드

### 소스 디렉터리

- 검색어가 없을 때(전체·Explorer 플랫폼): **사람 소스(텔레그램·블로그·유튜브)를 먼저**, 시스템 소스는 맨 아래 접힌 **Explorer 묶음** 안에 둔다. 순수 함수 `lib/canvas.ts` `groupDirectory()`.
  - Explorer 묶음 머리: 시스템 소스 수 + 안 읽음 합계 배지. 기본 접힘(선택한 소스가 시스템 소스이거나 플랫폼이 Explorer면 펼침).
  - 묶음 안: 'Explorer 업데이트 전체 보기'(플랫폼 Explorer로 전환), 한 개짜리 종류(내러티브·리포트·파급·수출입)는 한 줄씩, 많은 종류(기업 요약·컨콜·인물 요약)는 하위 묶음(소스 수 + 안 읽음 배지, 기본 접힘).
  - 접힘 상태는 화면 편의라 URL에 두지 않는다.
- 검색어가 있으면 묶음 없이 평평한 목록(모든 소스에서 찾는다).
- '전체' 리더(`팔로우한 소스 전체`)는 사람 소스만 보인다(`scope=sources`). Explorer 게시물은 Explorer 묶음에서 본다 — AI 생성물이 타임라인에 섞이지 않게.
- 리더 머리에 **문서 검색**(`/feed?view=documents`) 진입.

### AI가 최근 만든 것 — 상단 바로 (D-325)

- 4a에서 피드 화면이 바뀌며 빠졌고, 7단계(2026-11-05)에서 `home/AiActivityFeed`·`useAiActivity`·`GET /api/spine/home/ai-activity`까지 지웠다.
- 2026-11-06 D-325로 상단 바 아이콘(`layout/AiOutputs`, [app-shell](app-shell.md) §3)으로 되살렸다. 원천은 지운 API를 되살리지 않고 Explorer 묶음과 같은 타임라인(`scope=system`)을 쓴다 — 옛 카드에 있던 유튜브 AI 정리본은 이 원천에 없어 빠진다.

## 2. 공통 선택 팔레트

`shared/SelectionPalette` — 컨테이너 안에서 텍스트를 고르고 마우스를 떼면 선택 위에 동작 버튼이 뜬다(shadcn Popover, 가상 기준점). 선택 문장(≤500자)과 문단(블록 요소·`data-selection-block`, 줄글이면 빈 줄로 나뉜 문단, ≤1,200자)을 마우스를 뗀 순간 잡는다. 화면마다 지원하는 동작만 넘긴다.

| 화면 | 동작 |
|---|---|
| 문서 읽기 `/doc/:id` | 설명 · 검토(정해진 질문으로 AI 패널에 바로 보냄) · 스터디에 담기(기존 프로젝트 선택 창) · **AI에게 묻기** |
| 스터디(읽기 모드) `/study/:id`, 프로젝트 책상 | 강조 · 이해하기 · 검토하기 · 관련 자료 · 코멘트(기존 의도별 하이라이터와 같은 동작) · **AI에게 묻기**. 도구를 먼저 고르는 기존 흐름도 그대로 |
| 대화 답변(패널·`/chat`) | 인용해서 질문(근거 칩을 걷어내고 문단·선택 안 근거를 함께) |

### AI에게 묻기 — 패널 다리

`lib/aiPanel.ts`: `askAi({quote, question?, send?})`가 `explorer:ask-ai` 이벤트를 쏘고 요청을 한 칸 대기열에 둔다. 셸(Layout)은 듣고 AI 패널을 연다. `ChatPanel`은 듣거나(열려 있을 때) 마운트하며 대기 요청을 가져가(닫혀 있었을 때) 인용을 입력 위 칩으로 붙이고 입력창에 포커스한다. `send`면 바로 보낸다(답변 생성 중이면 칩만 붙인다).

인용 형태(`POST /api/spine/ask`의 `quote`):

```ts
{ message_id?: number          // 답변에서 지목
  doc_id?: number; doc_title?: string   // 문서·스터디 자료에서 지목
  selected: string; block: string; citations: Citation[] }
```

백엔드 `_quote_block`은 `message_id` 없이 `doc_id`/`doc_title`이 오면 머리를 '직전 답변' 대신 `문서 「제목」(doc_id N)를 읽다가 지목한 대목 … 전체가 필요하면 open_doc(doc_id)`로 쓴다. 붙여넣은 스터디 자료(doc_id 없음)는 `자료 「제목」`. 화면 맥락(`page_context`)은 함께 간다.

## 3. 캔버스 위젯 — 제거

옛 홈 위젯 4종(`widgets/canvas.tsx`: 안 읽은 소스·AI가 최근 만든 것·오늘의 주제·이어서 공부하기)은 홈 고정 탭 어디에도 쓰이지 않아 7단계(2026-11-05)에서 지웠다.

## 4. 저장됨·소스

셸 아래에서 `PageHeader`로 제목을 맞춘다(저장됨: '북마크와 메모 · N건'). 소스 관리의 '피드로 돌아가기'는 L2 탭이 대신해 뺐다.

## 5. 검증

- `npx tsc --noEmit -p tsconfig.app.json`, `node --test tests/*.test.mjs`(`canvas.test.mjs`: 디렉터리 묶음)
- 백엔드 `tests/test_chat_doc_quote.py`(문서 인용 머리·붙여넣은 자료·답변 인용 유지·API 통과)
- 실제 화면: 피드 디렉터리 묶음 펼침, 문서·스터디·대화 답변에서 선택 → 팔레트 → AI에게 묻기(닫힌 패널이 열리고 인용 칩·포커스)
