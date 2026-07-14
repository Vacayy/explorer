# Explorer — 의사결정 로그 (append-only)

> **규칙**: 이 파일은 결정의 *이유*를 보존하는 append-only 로그다.
> - 기존 항목은 **수정·삭제 금지**. 결정을 뒤집으면 새 항목으로 쓰고, 원 항목 끝에 `→ D-0XX에서 번복` 한 줄만 추가한다.
> - 최신 항목이 **맨 위**. 번호는 시간순 오름차순(다음 번호 = 최대 번호 + 1).
> - 기록 대상: 되돌리기 비싼 결정, 대안을 기각한 결정, "왜 이렇게 돼 있지?"가 나올 결정.
>   사소한 구현 선택·버그 수정은 커밋 메시지로 충분 — 여기 쓰지 않는다.
> - 형식: 결정 / 맥락·이유 / 기각한 대안 / 참조(커밋·파일·문서).
> - 현재 시스템 구조는 [SYSTEM.md](SYSTEM.md), 전략·지표는 [STRATEGY.md](STRATEGY.md), 우선순위는 [BACKLOG.md](BACKLOG.md).

---

## D-020 · 2026-07-14 · RS 활용 = 승인 게이트형 리서치 제안 (항상-켜짐 4분면 기각)

**결정**: 산업 맵의 RS 지표를 펀더멘탈과 결합하는 방식으로, **전 종목 RS×펀더멘탈 4분면을 매일 opus로 돌리지 않고**, 값싼 감지로 후보를 골라 **제안 → 사용자 승인 시에만 opus 리서치**를 실행. 감지(LLM 0) = 관심 유입(단기 RS≥70 & 1주 대비 +8pp↑) ∩ 규모(시총 5000억+) ∩ 화두(theme_surge 테마와 초점 문서 공동언급). 승인 = stock_brief(opus) 실행 → 추정치 방향 콜(up/down/hold) 기록. 표면: 신호 탭 '리서치 제안' 섹션(ApprovalsCard와 동일한 기계 제안→사람 결정 패턴).

**맥락·이유**: 비싼 자원은 opus 리서치 하나뿐 — RS 계산·시총·테마 공동언급은 전부 공짜 SQL. 후보 감지를 값싸게 하고 비싼 노동을 사람 판단 뒤로 미루면 opus 호출이 (RS 상승 전 종목 매일) → (승인한 소수)로 ~10배 감소. 프로젝트 철학 "노동은 기계가, 판단은 사람이"와 정확히 일치. 사용자 제안이 원안(항상-켜짐 4분면)보다 싸다는 계산을 확인하고 채택.

**기각한 대안**: ① RS×펀더멘탈 4분면 상시 계산(전 종목 매일 opus) — 비용 과다, 대부분 안 볼 종목까지 리서치 ② 펀더멘탈 축을 값싼 신호(컨센서스 방향·감성)로만 채운 상시 배지 — 컨센서스 이력이 하루치라 방향 판정 부정확, 승격 후 재검토. ③ 종목↔테마 연결을 MEMBER_OF(KSIC)로 — theme_surge(투자언어 테마)와 taxonomy 불일치 → 문서 공동언급으로, 시황 요약글(종목 링크 6개 초과)은 오염원이라 제외.

**참조**: pipeline/research_candidates.py, routers/spine_research.py, database.py(research_candidates), scripts/compute_signals.py, ExplorePage.tsx

## D-019 · 2026-07-12 · 세계관 브리핑 — 지식 종합과 주간 갈무리를 하나로

**결정**: "지식 기반 세계관 브리핑"(아이디어 1)과 "인물·채널 주간 갈무리"(아이디어 2)를 별개 기능으로 만들지 않고 **하나의 세계관 브리핑**으로 통합. 내부 3단 구조가 두 아이디어를 흡수: [자리 잡은 전제(느린 층 지식) / 도전받는 것(contested·반박) / 이번 주 달라진 것(빠른 층 관측·신호)] + 만장일치 경고 1줄. 표면: /knowledge 상단 카드, 게으른 생성(hash 가드), 종합=sonnet.

**맥락·이유**: 두 아이디어의 본질적 차이는 pace layer(느린/빠른)일 뿐 — 위계 설계가 정확히 이 구분을 위해 존재하므로 기능을 나누면 중복·중구난방(stakeholder 우려)이 된다. §G "시장의 통념 계량"의 1호 소비 표면.

**기각한 대안**: ① 별개 두 기능(지식 브리핑 + 주간 갈무리) — 재료 중복, 소비 지점 분산 ② 아침 텔레그램 브리핑에 통합 — 세계관은 매일 갱신될 이유가 없음(지식 상태 변경 시에만).

**참조**: 커밋 80fa90a, pipeline/worldview.py, knowledge-hierarchy-design.md §G

## D-018 · 2026-07-11 · 강조 카드 = 좌측 보더 → 배경 틴트

**결정**: 강조 카드(홈 브리핑·AI 응답 말풍선·AI 요약/브리프/다이제스트/소스요약)의 `border-l-2 border-l-primary|hypothesis`를 제거하고 **불투명 배경 틴트**로 강조: `bg-[color-mix(in_srgb,var(--{primary|hypothesis})_8%,var(--card))]`. 두 강조 유형을 동일 8% 강도로 평행하게. 적용 6곳: HomePage 브리핑, ChatPage AI 말풍선, StockBriefCard, DigestSection, DocPage·SourcePage AI 요약.

**맥락·이유**: 좌측 보더 강조는 나머지 카드 언어(ring+shadow, 배경 대비)와 어긋나는 변칙. 배경 틴트가 일관적. `color-mix`로 카드색 위에 얹어 불투명하게 만들어 카드 입체감·다크모드 대비를 유지(저알파 `bg-x/5`는 다크에서 카드 표면을 잃어 부적합).

**유지(강조 카드 아님)**: 채팅 스레드 선택 마커(`border-l-primary` 활성 표시, 사이드바 선택 패턴과 동일)·인용 들여쓰기(`border-l-2 border-border`)·밸류체인 다이어그램 헤더.

**참조**: docs/DESIGN_SYSTEM.md §3 패턴표 · 6개 파일

---

## D-017 · 2026-07-11 · shadcn-first 정책 + 헤더 정리 + 보더리스 + 팔로우 레일 Sidebar화

**결정**:
1. **shadcn-first (정책)**: 기능에 대응하는 shadcn 공식 컴포넌트가 있으면 반드시 CLI 설치해 쓴다. atom뿐 아니라 Sidebar·Sheet·Dialog·Progress·AlertDialog 등 복합 컴포넌트 포함. 그 위에 토큰+wrapper만 씌운다. 수제 div/raw HTML 금지.
2. **헤더 정리**: 중복 검색(360px 검색창 + "이동·검색·질문 ⌘K" 버튼)을 단일 필드형 검색 진입점으로 통합 — 클릭·⌘K 모두 Omnibar 오픈(Omnibar가 이미 회사검색·이동·문서검색·질문 커버). 헤더 회사 배지 제거(ModeNav pill과 중복). raw kbd→`Kbd`.
3. **보더리스**: "아웃라인→면(surface)"으로 전환. 헤더·네비의 `border-b` 제거(카드색 vs stone 바탕 대비로 층 표현). 카드는 이미 ring+shadow. 표 행 구분선·인풋·세그먼트는 스캔/조작에 필요하므로 유지.
4. **팔로우 레일 = shadcn Sidebar**: 수제 `<aside>`(fixed·localStorage·✕)를 공식 `Sidebar`(side=right, collapsible=offcanvas)로 교체. 앱 셸을 `SidebarProvider`+`SidebarInset`로 재구성(헤더/네비가 inset 안으로). 넓은 데스크톱(≥1280px)=펼침, 그 이하=토글(헤더 패널버튼/⌘B), 모바일=Sheet 오버레이 자동.
5. **감사 후속 일괄 교체**: 패널토글 2곳(Financials·Industry)→SegmentTabs, 카탈리스트 기간필터→FilterChips·펼침→Collapsible, native `confirm()` 2곳→AlertDialog, 수제 진행바→Progress. **미교체(사유 있음)**: UnifiedFeed 전문펼침(요약숨김+이미지리사이즈 얽힘)·SignalCard 부분리스트노출(slice)·Expandable(fade+높이클램프)·인라인 추가폼(Dialog화는 UX 변경이라 보류).

**맥락·이유**: 공식 컴포넌트 CLI 설치가 접근성·키보드·포커스·엣지케이스 안정성을 보장(사용자 지시). 헤더 번잡함의 원인은 검색 중복+겹치는 하드보더였음.

**기각/주의**: Sheet 오버레이(항상 보이는 레일 목적과 상충), Sidebar in-flow collapsible=none(반응형 접힘 안 됨) → offcanvas 채택. shadcn Sidebar는 뷰포트 우측 고정·전체높이 모델이라 기존 '중앙 셸+전폭 헤더 위' 구조에서 **헤더/네비가 inset 폭으로 축소**되는 레이아웃 변화 수반(사용자가 반응형 collapse 의도를 확인해 수용). CLI가 파일을 `@/` 경로에 잘못 생성 → 필요한 것만 `src/`로 이동, 재생성된 button/input 등은 커스텀 보존 위해 폐기.

**참조**: memory `shadcn-first-policy` · App.tsx(SidebarProvider) · FollowRail.tsx · Header.tsx · index.css(sidebar 토큰은 D-016) · 설치: sidebar·sheet·progress·alert-dialog·toggle·toggle-group·checkbox

---

## D-016 · 2026-07-11 · 라이트/다크 팔레트 재설계 — 멀버리 정체성

**결정**: Apple HIG 캔디블루(#0071e3) 팔레트를 버리고 **멀버리(#8e4162) 프라이머리** 중심으로 라이트/다크를 하나의 정체성으로 재설계. 확정값(index.css):
- **낮 (쿨 스톤 & 멀버리)**: ground `#f9f8f9` · card `#ffffff` · primary `#8e4162` · secondary `#ebedf0`(서늘한 회석) · accent `#f6eef2` · border `#e0e2e7`
- **밤 (더스크 플럼)**: ground `#282130` · card `#332a3c` · primary `#e199ba` · secondary `#3f3447` · accent `#402d49` · border `#504358` · primary-foreground `#23121b`
- 등락 빨강/파랑·사실 초록·가설 주황 컨벤션 유지(형광기만 조정). 차트 캔디블루(#0071e3→#1268c3 / #409cff→#5aa6f5)만 팔레트에 맞춰 눅임 — 나머지 차트 시리즈색은 유지(별도 검토 대상).

**맥락·이유**: 기존 라이트가 "촌스럽다"는 사용자 피드백. 원인은 순백+캔디블루+진한 보더의 강한 평면 대비. 멀버리는 AI 서비스가 거의 안 쓰는 좌표라 차별화되고 금융 에디토리얼(FT 계열) 헤리티지가 있음. 다크는 "라이트 반전"이 아니라 **같은 방 불 끈 상태**로 설계 — 프라이머리가 바탕에도 흐르는 정체성. 다크 밝기는 사용자 눈 편안함 기준으로 순검정(#17121b) 대신 더스크 플럼(#282130)까지 올림(halation 완화).

**기각한/킵한 대안** (재검토 시 참조 — 값은 스크래치패드 아티팩트에 목업 존재):
- 낮 뉴트럴: L-1 딥 블러시 `secondary #f4e2ea`(무드) · L-2 웜 샌드 `#efeae1`(절제). L-3 쿨 스톤 선택 — "앤트로픽 크림 느낌"이 가장 덜함.
- 낮 프라이머리 후보: 코발트 인디고 #3b5bdb, 딥 틸 #0f766e, 딥 네이비 #2f4f96 — 멀버리로 확정.
- 밤 온도/밝기: 웜 오베르진 진함(#17121b)~살짝(#1c1621)~중간(#221b28) · 쿨 슬레이트 계열 — 더스크 플럼(#282130) 선택. **더 밝혀도 무방**하다는 사용자 의견 있음(추후 조정 여지).

**참조**: frontend/src/index.css `:root`·`.dark` · 어제까지의 Apple HIG 값은 git 히스토리 · docs/DESIGN_SYSTEM.md §2

---

## D-015 · 2026-07-11 · 프론트 레이아웃 컨트랙트 + 디자인 시스템 명문화

**결정**: ① 모든 라우팅 페이지의 최상위는 `shared/PageContainer`(width: full|reading, gap: sm|md) — 페이지가 자체 max-w/padding을 갖지 않고 폭은 셸 토큰 `--layout-shell`(1440px)이 단독 결정. ② 풀하이트 페이지(Chat)는 `--shell-offset` 토큰 기반 `calc` 예외. ③ 다열 그리드는 반드시 `grid-cols-1`에서 시작하는 반응형. ④ 단일선택 세그먼트는 Radix ToggleGroup, 접기/펼치기는 Radix Collapsible로 단일화. ⑤ 전체 규약을 docs/DESIGN_SYSTEM.md로 명문화 (Meta astryx의 CSS-변수 테마·강한 컨벤션·조합성 원칙 차용).

**맥락·이유**: 페이지마다 max-w(없음/2xl/3xl)·간격(space-y-4/5/6)·자체 패딩이 제각각이라 화면 넘침/미달이 혼재했고, 같은 세그먼트 토글이 4곳에서 다르게 수제 구현돼 있었다. 폭 결정권을 셸+PageContainer 두 곳으로 좁히면 규격 불일치가 구조적으로 불가능해진다.

**기각한 대안**: 페이지별 개별 수선(재발 방지 안 됨) · shadcn Tabs로 세그먼트 대체(패널 전환 의미론이라 부적합, 값 토글은 ToggleGroup이 정합) · 셸 폭 무제한 확대(초광폭 모니터 가독성 저하).

**참조**: docs/DESIGN_SYSTEM.md · shared/PageContainer.tsx · index.css 레이아웃 토큰 · grandfathered 예외 목록(DESIGN_SYSTEM.md §3)

---

## D-014 · 2026-07-11 · 컨텍스트 3층 문서 체계 + 유지 규율

**결정**: 프로젝트 문서를 변경 빈도별 3층으로 고정하고, CLAUDE.md에 갱신 규칙을 명문화한다.
- **규칙층** CLAUDE.md — 매 세션 자동 로드, 거의 불변
- **상태층** docs/SYSTEM.md — 살아있는 시스템 지도, 구조가 바뀌는 커밋에 *같이* 갱신
- **결정층** docs/DECISIONS.md(본 파일) — append-only, 중요 결정마다 추가

**맥락·이유**: ARCHITECTURE.md가 초기 커밋(7/4) 이후 방치돼 일주일 만에 낡은 문서가 됐고, SYSTEM.md에 "본 문서가 현행" 면책 문구가 필요해졌다. 낡은 문서는 없는 것보다 나쁘다(다음 세션의 LLM이 믿고 판단). 유지 비용이 0에 가까운 구조(append-only 로그 + 커밋 동반 갱신)만이 지속된다.

**기각한 대안**: ① 매 작업 세션별 작업일지 — 의식이 무거워 몇 주 내 붕괴 예상, "어떻게 했는지"는 git 히스토리가 이미 담당. ② CLAUDE.md에 아키텍처 내용 직접 기술 — 매 세션 컨텍스트를 태움, CLAUDE.md는 규칙+포인터만. ③ codebase-memory MCP의 ADR 기능 — md 파일이 git 리뷰·이식성에서 우위.

**참조**: CLAUDE.md "Context Discipline" 섹션 · 구 문서는 docs/archive/로 이동

---

## D-013 · 2026-07-10 · 앤티-분산(anti-sprawl) 정책 — 새 기능은 새 탭 0개

**결정**: 새 기능은 원칙적으로 새 페이지·새 탭을 만들지 않고 기존 화면에 편입한다. IA 확장은 명시적 결정이 있을 때만.

**맥락·이유**: 기능이 붙을 때마다 탭이 늘면 "매일 아침 여는 터미널"이 미로가 된다. 북극성 지표(주간 열람일수)는 화면 수가 아니라 홈·피드의 밀도에서 나온다. 소스 건강 모니터·보관함부터 첫 적용(새 탭 0개).

**기각한 대안**: 기능별 전용 페이지 — 발견성은 옴니바(⌘K)가 대체.

**참조**: 커밋 7a45160 · 옴니바 52d7e86

---

## D-012 · 2026-07-10 · 지표 체계 — 북극성 = 주간 열람일수, OMTM = "홈이 조용한 날" < 10%

**결정**: 북극성 지표는 주간 열람일수(5일 만점), 당면 단일 지표(OMTM)는 "홈이 조용한 날" 비율 < 10%. 레버는 소스 확충·키워드·별칭 recall.

**맥락·이유**: 실사용 피드백에서 검증된 가치 패턴은 "기계가 읽고·모으고·연결"이고 "기계가 종합 판단"은 시기상조. 따라서 매일 열 이유(delta 밀도)가 제품의 생명선. 조용한 날이 시장 탓인지 수집 고장 탓인지 구분하기 위해 소스 건강 모니터가 OMTM 방어 장치로 함께 도입됨.

**기각한 대안**: AI 답변 품질을 당면 지표로 — 문서 1,000+건 축적 전에는 측정 무의미(가설 H3, 월말 재평가).

**참조**: docs/STRATEGY.md · 커밋 5a71cbb

---

## D-011 · 2026-07-10 · SQLite 유지 + WAL + busy_timeout 30s — Postgres·AWS는 보류

**결정**: 단일 SQLite 파일(WAL 모드, busy_timeout 30초)을 유지한다. Postgres 전환과 AWS 배포는 멀티유저(S2) 트리거가 실제로 당겨질 때 함께 진행.

**맥락·이유**: 로컬 개인 도구에서 SQLite는 운영 비용 0·백업 단순. 30분 cron 수집 쓰기와 API 읽기가 충돌해 락 오류가 났고, WAL + busy_timeout 30s로 해결(543148c). 이 해법의 한계(단일 라이터)는 인지하고 있으며 멀티유저 전 Postgres 리프트&시프트 설계는 논의 완료 상태로 보류.

**기각한 대안**: 즉시 Postgres — 현 단계에서 운영 복잡도만 증가. 사용자가 AWS 배포 명시적 보류.

**참조**: 커밋 543148c · docs/BACKLOG.md "AWS 배포(사용자 보류)"

---

## D-010 · 2026-07-10 · 텔레그램 수집 = 공개 프리뷰(t.me/s) 스크랩만, 이미지는 로컬 보관

**결정**: 텔레그램은 로그인 없는 공개 프리뷰 페이지 스크랩으로만 수집한다(공개 채널, 최근 ~20개 창). 첨부 이미지는 CDN URL 만료에 대비해 `media/telegram/`에 결정적 파일명(채널_메시지ID_순번)으로 다운로드 보관.

**맥락·이유**: Telethon(계정 로그인) 방식은 비공개 채널·과거분 수집이 가능하지만 계정 보안·약관 리스크가 있어 보안 논의를 선행 조건으로 보류. 프리뷰 창이 좁은 대신 30분 cron이 촘촘히 돌아 실질 유실은 적다.

**기각한 대안**: Telethon 즉시 도입 — 보안 논의 선행. CDN URL 직접 참조 — 만료로 이미지 유실.

**참조**: backend/services/telegram_service.py · pipeline/connectors/telegram.py · 커밋 a62b047

---

## D-009 · 2026-07-09 · LLM 계층 = Claude Code headless(구독 인증) + 용도별 모델 티어

**결정**: LLM 호출은 API 키 대신 Claude Code headless(`claude -p`) 구독 인증으로 구동. 용도별 티어 고정 — 태깅·요약·비전·다이제스트 = haiku, RAG 질의응답 = sonnet, 임베딩 = 로컬 fastembed(다국어 MiniLM 384d). `ANTHROPIC_API_KEY` 설정 시 자동 API 모드 전환(코드 준비됨).

**맥락·이유**: 개인 도구에서 LLM 한계비용을 0으로(구독에 포함). 문서당 1회 원칙 + `content_hash` 멱등 캐시로 재수집 시 재호출 방지. keyword 엔진 → LLM 자동 백필로 모델 티어 업그레이드 경로 확보.

**기각한 대안**: API 키 직접 사용 — 종량 비용 발생, 단 전환 스위치는 유지. 임베딩도 LLM API — 로컬 fastembed로 충분하고 무료.

**참조**: 커밋 2f32680 · backend/pipeline/enrich.py · SYSTEM.md §3

---

## D-008 · 2026-07-08 · 검색 = FTS5(BM25) + sqlite-vec 하이브리드, RRF 융합

**결정**: 피드 검색은 SQLite 내장 FTS5(BM25)와 sqlite-vec 벡터 검색을 RRF(Reciprocal Rank Fusion)로 융합한 하이브리드로 구현. FTS 인덱스는 트리거로 동기화.

**맥락·이유**: 한국어 종목명·별칭은 키워드 매칭이 강하고, 문맥 질의는 벡터가 강함 — 단독으로는 어느 쪽도 recall이 부족. 별도 검색 인프라(Elasticsearch 등) 없이 단일 SQLite 안에서 해결(D-011과 일관).

**참조**: 커밋 8b93569 · backend/pipeline/search.py

---

## D-007 · 2026-07-08 · vault 소유권 분할 — 대칭 sync 금지

**결정**: Obsidian vault와 DB의 동기화는 단방향 2개로만. 자동수집 데이터 = **DB가 원본** → vault/entities/로 투영(generated). 사람의 가설·메모 = **마크다운이 원본**(vault/notes/, `[[위키링크]]`) → DB로 흡수. 양방향 sync는 금지.

**맥락·이유**: 대칭 sync는 충돌 해소 로직이 필요해지고, 어느 쪽이 진실인지 모호해진다. 데이터 종류별로 원본 소유자를 고정하면 충돌이 원천 불가능. 위키링크는 confidence 1.0 엔티티 링크로 흡수(사람이 직접 연결한 것이 가장 신뢰도 높음).

**기각한 대안**: 양방향 동기화 — 충돌 해소 복잡도. vault 없이 DB만 — 가설 작성 UX는 Obsidian이 압도적.

**참조**: 커밋 8b93569 · scripts/vault_sync · SYSTEM.md 비타협 원칙

---

## D-006 · 2026-07-06~08 · entity_links 신뢰도 계층 (5단계)

**결정**: 문서↔엔티티 링크는 출처별 고정 confidence를 갖는다: 위키링크 1.0 > LLM 추출 0.9 > 사용자 키워드 0.7 > 정식명 substring 0.6 > 태그 0.5. UI는 저신뢰 링크를 흐리게 표시(EntityChip).

**맥락·이유**: 초기 substring 매칭이 오탐을 냈고(8f64e4a에서 수정), "누가 이 링크를 만들었나"를 보존해야 오탐 정리·재enrich 시 stale 링크 제거가 가능. 사람이 만든 링크(위키링크·키워드)는 기계보다 위.

**참조**: backend/pipeline/store.py · 커밋 8f64e4a · SYSTEM.md §4-1

---

## D-006 · 2026-07-12 · 지식 위계 K0 게이트 조기 해제 (stakeholder 지시)

**결정**: K0(공고화 계층)의 문서 1,000건 게이트를 해제하고 즉시 구현·가동. 승격 배치는 주 1회(일 07:00 cron), 산출은 승인 큐(홈 카드)로 — 자동 확정 없음(D-005 설계 결정 유지).

**맥락·이유**: 설계 문서(knowledge-hierarchy-design.md v4)가 문헌 검증(부록 F)까지 마쳐 승인됨. 게이트의 목적은 '반복 관측이 잡히기 시작하는 규모'였는데, 조기 가동의 해악이 없음 — 초기엔 후보가 적게 나올 뿐이고, 승인 큐가 품질 관찰 창 역할. 코퍼스(~550건)가 쌓이는 대로 배치 산출이 자연 증가.

**기각한 대안**: 1,000건 대기 — 승인 큐 품질 관찰을 늦출 이유가 없음.

**참조**: docs/specs/knowledge-hierarchy-design.md · D-004(게이트 설정)·D-005 · pipeline/consolidation.py

---

## D-005 · 2026-07-06 · 그래프 엣지는 단방향 저장, epistemic_type 필수

**결정**: entity_relations 엣지는 단방향만 저장(`SUPPLIES` A→B만, "고객사"는 질의로 역전). 모든 엣지는 `epistemic_type`(fact | hypothesis) 필수 — fact는 공시·통계로 검증 가능한 것만, hypothesis는 confidence + source_doc_id 필수.

**맥락·이유**: 양방향 저장은 정합성 깨짐의 근원. 사실/가설을 섞으면 월드모델이 "그럴듯한 쓰레기"가 된다 — 목표는 믿는 자동 오라클이 아니라 **출처 달린 가설 트래커**. 이 원칙은 UI까지 관통(가설 = 주황 hypothesis 스타일, 모델명 표시).

**참조**: docs/ontology.md 설계 원칙 · SYSTEM.md 비타협 원칙

---

## D-005 · 2026-07-11 · P2-2 게이트 해제 — 전면 개편 즉시 진행 (stakeholder 지시)

**결정**: D-004의 "P2-2는 2주 질문 데이터 관찰 후" 게이트를 해제하고 대화 UI(/chat 스레드)와 L1 재편(오늘·탐색·피드·대화)을 즉시 진행. 분석 L1 pill 제거(도시에는 목적지 — 분석 화면에서만 컨텍스트 pill+서브탭 노출), 리서치 서브탭 그룹 해체, catch-all `*`→/home. /ask는 /chat으로 리다이렉트(쿼리 보존).

**맥락·이유**: 사용자(stakeholder) 피드백 — 원했던 것은 프로덕트 전체 리브랜딩·플로우 재정의인데 단계적 접근이 "디테일 페이지 조금 바뀐 수준"으로 체감됨. 데이터 게이트는 리스크 관리 장치였지 목표가 아니므로, 눈에 보이는 개편을 앞당기고 A1~A3 가정 검증은 출시 후 관찰로 전환.

**기각한 대안**: 게이트 유지(2주 관찰 후 개편) — stakeholder가 명시적으로 기각.

**참조**: docs/specs/product-v3.md §5 · D-004

---

## D-004 · 2026-07-06 · 온톨로지 스코프 규율 — 렌즈 1개 end-to-end 먼저

**결정**: 세상 전체를 day1에 모델링하지 않는다. 노드/엣지 타입 어휘는 미리 선언(reserved)하되, 메모리/AI 렌즈 1개를 end-to-end로 완성해 루프를 증명한 뒤에만 다음 렌즈(인물·지정학·매크로)를 채운다. 렌즈가 늘어도 DB는 1개 — entity_type/relation_type 어휘만 확장.

**맥락·이유**: 온톨로지는 넓히기는 쉽고 채우기는 비싸다. 빈 스키마 확장은 복잡도만 늘린다. observations/models 테이블도 스키마만 만들고 무역 커넥터 단계까지 비워두는 것이 같은 원칙.

**참조**: docs/ontology.md · SYSTEM.md §4-1 (observations/models 0행)

---

## D-004 · 2026-07-11 · Phase 2 — 판단 루프 축 + 대화 프리미티브 승격 (feat/phase2 분기)

**결정**: ① Phase 2 UI/UX 개편의 중심 축을 "판단 루프"(유입→델타→맥락→판단)로 삼고, 대화(채팅)를 스트림·도시에에 이은 **세 번째 프리미티브**로 승격. ② 질문·후속질문·답변 히스토리를 데이터 자산으로 영속화(conversations/chat_messages) — 웹 /ask와 텔레그램 봇 공용 풀. ③ **에코챔버 방지 불변 원칙**: AI 답변은 검색 인덱스(doc_fts/doc_vec)에 절대 넣지 않는다 — 질문은 시그널, 답변은 파생물. ④ 마이그레이션은 "데이터부터, UI는 증거 뒤에" — P2-0(영속화, UI 무변화)을 먼저 깔고, 대화 UI(P2-2)는 2주 질문 데이터 관찰 후 결정. ⑤ 작업은 feat/phase2 브랜치 — feat/etl-spine을 안정 복귀점으로 유지. ⑥ OMTM(주간 열람일수)에 텔레그램 문답을 '열람'으로 포함하도록 재정의.

**맥락·이유**: ia-map.md 진단 — 최대 허브(/analyze/summary, 13+ 엣지)가 spine과 단절된 dead-end, 판단 레이어(투자메모)가 보관함에 유배, 루프가 안 닫힘. 질문 히스토리는 이 제품이 쌓는 유일한 "사용자 의도" 데이터인데 현재 전부 버려짐(/ask 일회성, 봇 stateless). 반복 질문의 브리핑 승격은 3단계(자율 에이전트)로 가는 다리 — 에이전트의 할 일을 질문 패턴이 정의한다.

**기각한 대안**: 대화를 전역 채팅 패널로(레일과 경쟁, 산만) — 엔티티 앵커 스레드 + 도시에 내 섹션으로 대체. AI 답변도 raw_documents로 적재(검색 대상화) — 자기 참조 오염 위험으로 기각. UI 먼저 대개편 — A1~A3 가정(질문 빈도) 미검증 상태라 기각.

**참조**: docs/specs/product-v3.md(리스크 가정 10건·킬 기준 포함) · docs/specs/ia-map.md · 사용자 승인 2026-07-11

---

## D-003 · 2026-07-06 · ETL 척추(spine) greenfield — raw_documents 단일 진실원천

**결정**: 소스별 테이블(telegram_messages, blog_posts)에 각자 적재하던 구조를 버리고, 모든 소스가 `SourceConnector` 프로토콜(discover→fetch)을 구현해 **raw_documents 단일 테이블**(UNIQUE(source_type, source_id), content_hash 멱등)로 수렴하는 척추를 신설. 기존 도메인 테이블(companies, stock_prices, financial_statements…)은 삭제하지 않고 유지 — 척추가 읽기 참조하는 "옛 세계".

**맥락·이유**: 검색·태깅·요약·신호가 소스마다 중복 구현되는 것을 차단. 새 소스 추가 = 커넥터 1개 작성으로 수렴. 옛 테이블을 파괴하지 않은 것은 종목 디테일·스크리너 등 기존 화면의 안정성 때문 — 점진 cutover 후 telegram_messages 등은 휴면 처리(D-003 이후 ffcee21에서 피드 cutover 완료).

**기각한 대안**: 소스별 테이블 유지 + 뷰로 통합 — 태깅·검색 파이프라인이 소스 수만큼 분기. 옛 테이블 즉시 삭제 — 리스크 대비 이득 없음.

**참조**: 커밋 5449eec(도입)·ffcee21(cutover) · backend/pipeline/ · SYSTEM.md §4

---

## D-002 · 2026-07-04 · DART 재무 데이터 처리 규칙

**결정**: ① 연결(CFS) 우선, 없으면 별도(OFS) fallback. ② 손익계산서·현금흐름표는 분기 차감(Q2 = 반기 − Q1), 재무상태표는 시점 데이터 그대로. ③ 계정명은 `_normalize_account_name()`으로 변형 통합(영업이익 = 영업이익(손실)). ④ 모든 외부 API 호출은 cache_meta 캐시 패턴 필수.

**맥락·이유**: DART 원본은 누적 기준·계정명 표기가 회사마다 달라 그대로 쓰면 분기 비교가 불가능. 이 규칙 없이는 재무 화면 전체가 오염된다. opendartreader는 0.2.2 핀(0.3.x는 패키지 구조 변경으로 import 불가, 8f64e4a).

**참조**: backend/services/dart_service.py · CLAUDE.md 백엔드 규칙 · requirements.txt 핀 주석

---

## D-001 · 2026-07-04 · 초기 스택 — FastAPI + SQLite + React 19, 로컬 우선

**결정**: 백엔드 FastAPI + SQLite, 프론트 React 19 + TypeScript + Vite + Tailwind v4 + shadcn/ui, 차트는 Recharts + lightweight-charts, 서버 상태는 TanStack Query. 전부 로컬 실행(백엔드 :8000, 프론트 :5173), 배포 없음.

**맥락·이유**: 1인 사용 개인 리서치 도구 — 무료 데이터(DART·pykrx·yfinance·FDR) + 구독 LLM + 로컬 실행으로 월 운영비 ~0원. URL을 상태의 단일 소스로 삼는 것(useState 모드 관리 금지), 전 화면 5-state, 상승=빨강/하락=파랑(한국 컨벤션) 등 UI 규약은 CLAUDE.md·docs/policies/에 규칙화.

**참조**: 커밋 e34bc3c · CLAUDE.md · docs/policies/
