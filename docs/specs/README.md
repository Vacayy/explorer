# Spec 목록과 수명주기

이 파일은 설계 탐색의 단일 진입점이다. 현재 실행 구조는 [SYSTEM](../SYSTEM.md), 결정 이유는 [DECISIONS](../DECISIONS.md), 작업 우선순위는 [BACKLOG](../BACKLOG.md)에 있다.

## 홈·피드

| 문서 | 역할 | 상태 | 다음 단계 |
|---|---|---|---|
| [홈과 통합 피드](home-feed.md) | 홈 두 열 배치·원문/시스템 카드·조회 계약·UX 조사 | 구현·검증 완료 | 실사용에서 정보 밀도 확인 |

## 기획: 종목 묶음·기술적 감시

| 문서 | 역할 | 상태 | 다음 단계 |
|---|---|---|---|
| [종목 묶음과 기술적 감시](portfolio-watch.md) | 포트폴리오·관심 종목을 묶음 하나로 통일, 종목별 조건의 일일 평가·신호 화면 계약 | P0 구현(2026-09-19, D-185): 묶음·규칙·일일 평가·신호 화면·레거시 이관 | P1: 수량·매수가 입력 UI, 매수가 기준 조건, 브리핑 한 줄 |

## 구현: 스터디 모드

| 문서 | 역할 | 상태 | 다음 단계 |
|---|---|---|---|
| [스터디 모드](study-mode.md) | 원문 읽기·영속 주석·질문 context·추가 리서치의 단일 계약 | 독립 프로젝트·의도별 하이라이터·표시별 AI/후속 질문·FIFO·통합 노트 구현 | 관련 자료 검색·웹 확인·실제 모델/브라우저 검증; 미수집 URL 자동 수집은 후속 |

## 진행 중: 기대 변화 관측

| 문서 | 역할 | 상태 | 다음 단계 |
|---|---|---|---|
| [공통 설계](expectation-observatory-greenfield.md) | 제품·데이터·시간·기대 비교 계약 | 수집 자료 읽기 → 기존 챗봇 대화 연결 구현, 원장은 보조 | 일상 질문에서 자료 누락·비교 품질 확인 |
| [메모리 커버리지](memory-semiconductor-coverage.md) | 기업·제품·쟁점·파일럿 준비 | 범위 확정, 코퍼스 감사·실자료 추출 smoke | 초기 8개 사례 채점 후 20~30개로 확장 |

두 파일의 역할은 중복하지 않는다. 실행 결과와 개인 소스 명단은 `logs/memory-coverage/`, 재현 도구는 `scripts/audit_memory_coverage.py`. 새 감사/후속/최종 spec을 만들지 않고 위 담당 파일을 갱신한다.

## 구현·평가 중: Weekly 시장 진단

| 문서 | 역할 | 상태 | 다음 단계 |
|---|---|---|---|
| [Weekly 에이전트 인계](weekly-agent-handoff.md) | 외부 대화 맥락과 기존 수집·분석 구조의 접점 | 설계 제안, 미확정. 2026-09-14 코드·보유 데이터 대조 | 원문·차트 재확보, 한 주차 질문·기간·사례·반증 조건 파일럿 구체화 |
| [Weekly 분석 하네스 설계 (HTML)](weekly-harness-design.html#final-harness-design) | 브리핑 생산·실행/개선루프·결정 근거와 현행 CLI/API·시점 계약의 기준 문서 | D-173: [쟁점별 원문 조사·반론 재조사·판단·집필 실행](weekly-harness-design.html#research-runtime)을 기존 v2 경로에 연결. D-171·172 [목표 설계·다이어그램](../../logs/weekly-harness/final-design/index.html)은 유지하며 자동개선·릴리스 실행기는 보류. [보강 인계](weekly-agent-handoff%20(1).md) 참조 | [최종 Weekly](../../logs/weekly-harness/comparisons/weekly-research-20260916-r2/corrected.html)·[구현과 원문 대조](../../logs/weekly-harness/comparisons/weekly-research-20260916-r2/implementation-review.html) 완료(본문 추가 검사 통과·전문가 품질 미확정). 유가·펀더멘탈 분석 깊이 개선 → 미사용 주차 전문가 평가. 신규 외부 수집·사건별 계산·주간 갱신은 후속 |

## 구현·검증: 시장 데이터 CodeAct

제품 흐름과 클릭 가능한 화면 예시는 [발견에서 판단까지 — HTML 기획안](../prototypes/discovery-research-plan.html)에서 확인한다. 후속 기능 설계이며, 가상 자료로 된 예시와 실제 구현·자료 현황을 구분한다.

| 문서 | 역할 | 상태 | 다음 단계 |
|---|---|---|---|
| [시장 데이터 CodeAct 분석](market-codeact.md) | 기존 시세의 읽기 전용 스냅샷·격리 실행·조건/결과·AG-UI/A2UI 계약 | macOS 구현·실제 모델 검증·별도 NAVER 이력 137만 행 수집. D-182 독립 발견 진입·후보/차트·원클릭 조사·선택 기업 자료 준비 구현 | 후속 질의의 조건 보존·조건식 확장·발견 맥락 전달, 공식 달력·미평가 확인 |
| [종목 발견 성능](market-discovery-performance.md) | 발견 실행의 단계별 병목 지도·측정 방법·개선 전후 기록 | 2026-09-21 측정: 자연어 46s(모델 65%)·선택 12~21s. finish 콜·스냅샷 재생성·순수 Python 계산이 병목 | 개선 1~5 적용하며 전후 수치 갱신, 해석 콜 haiku/Jev A/B |
| [시장 전략 도구](market-strategies.md) | 시세동향 19·지표신호 25·순위 6개 정의와 계산 기준 | 카탈로그·자연어 조건식·독립 검증, 전략 버전·재실행·목적/관측 추천 구현 | 검색 정의/실행 버전 구분·저장/재실행, 이유 있는 추천, 미지원 자료 확보 |
| [시장 전략 비교 백테스트](market-backtest.md) | 7개 기준·복합 전략의 사전 고정 조건, 다음 시가 체결, 비용·현금·평가 계약 | 격리 계산·독립 원장 검산·결과 UI·실제 개발/평가 비교 완료 | 과거 상장/상폐·시총 이력, 기업행동·거래일 검증, 더 긴 미관측 구간 |
| [기업 리서치와 발견 연결](company-research.md) | 기업 개요·실적·자료 읽기와 기술적 발견 이후의 조사·팔로우업 | 기업 화면·발견 맥락·근거 조사·판단 버전·수동 팔로우업, D-182 재무·공시 자동 준비 및 결과 중심 UX 구현 | 발견 이유 보존, 시장·전방·콜·수출입 근거 연결과 날짜 검증, 기존 질문/스터디 재사용 |

## 문서를 늘리기 전 규칙

1. 같은 기능/계약이면 기존 담당 문서를 수정한다. 날짜·라운드·v2/v3를 이유로 파일을 추가하지 않는다.
2. 새 문서는 독립적으로 관리할 계약이나 커버리지가 있을 때만 만든다. 이 목록에 역할·상태·다음 단계를 같이 등록한다.
3. 새 문서 첫머리에 제안/구현중/구현됨/대체됨 상태와 상위 문서를 명시한다. 실측 결과와 제안 수치를 구분한다.
4. 원문·평가 실행 결과·개인 큐레이션은 로컬 산출물에 둔다. spec에는 방법·판정 규칙·요약된 준비 상태와 위치만 적는다.
5. 구현 완료 시 SYSTEM에 실행 구조를 반영하고 spec은 유지할 동작 계약만 남긴다. 구현되지 않은 설계를 현행으로 표시하지 않는다.
6. 대체/폐기 시 대체 문서와 이유를 기록하고 archive로 이동하며 링크를 함께 고친다. 원자료·평가 스냅샷을 문서 정리와 함께 삭제하지 않는다.
7. 기존 문서는 실제 소유 기능을 점검할 때 통합한다. 이번 목록화만으로 최신/폐기 상태를 추정하거나 일괄 삭제하지 않는다.

## 기존 기능 문서 — 상태 검토 대기

아래는 누락 방지를 위한 목록이다. 각 문서의 구현 여부·중복·최신성은 이번 작업에서 전수 감사하지 않았다. 담당 기능을 변경할 때 대표 문서를 선택하고 중복 문서를 정리한다. 기능별 실제 상태는 SYSTEM 및 문서 내용을 대조한다.

- [0725-graph-improvement-plan](0725-graph-improvement-plan.md) — 결론부터
- [action-thesis](action-thesis.md) — action_thesis — 이벤트 → 수혜 종목 → 조건부 업사이드/하방 (에이전트화 다음 단계)
- [agent-proposals](agent-proposals.md) — 기획서 — 에이전트 제안함 (진화계획 3단계, 제안-전용)
- [analyze-summary](analyze-summary.md) — 화면 기획서: 요약 페이지 (Resizable 패널 레이아웃)
- [causal-worldview](causal-worldview.md) — 기획서 — 세계관 뷰 (인과 그래프 노드-링크 시각화)
- [chat-agent](chat-agent.md) — 대화 에이전트 아키텍처 — 라우터·도구·멀티턴 메모리 (B 단계, 2026-09-08)
- [chat-harness](chat-harness.md) — 대화(챗봇) 하네스 — 현황 분석 + 아키텍처 레퍼런스 (2026-09-08)
- [chat-page](chat-page.md) — /chat 화면 리뉴얼 — 메신저에서 "판단 도구"로 (2026-09-08)
- [chat-retrieval](chat-retrieval.md) — 대화 검색 품질 — 청크 인덱스 · 문맥 접두어 · 리랭커 (C 단계, 2026-09-08)
- [discover-screener](discover-screener.md) — 화면 기획서: 스크리너
- [discover-signals](discover-signals.md) — 화면 기획서: 시그널 피드
- [doc-causal-extraction](doc-causal-extraction.md) — 기획서 — 문서 레벨 인과 추출 (제2 인과 공급원)
- [doc-synthesis](doc-synthesis.md) — 문서 교차 종합 (Doc Synthesis) — 고른 문서들을 엮어 읽기
- [dock-navigation](dock-navigation.md) — 셸 대개편 — 헤더·네비 제거, macOS 도크형 내비게이션 (2026-09-08)
- [follow-rail](follow-rail.md) — 팔로우 레일 — 사이드바 통합
- [frontend-plan](frontend-plan.md) — Frontend 구현 계획 — 디자인 시스템 → 컴포넌트 → API 정책
- [geo-scope](geo-scope.md) — geo_scope — 인과 주장에 장소 정박 (A방향: 보편 노드 + 스코프 있는 엣지)
- [hypothesis-vault](hypothesis-vault.md) — 가설·메모 Vault — 소유권 분할 설계
- [ia-map](ia-map.md) — IA 지도 — 페이지 진입로 & 화면 구성 (현행)
- [integrated-report](integrated-report.md) — 통합 리포트 — 공유 인과 내러티브 취합 → 종목 다각도 재분석 → Top-down 리포트
- [investor-lens](investor-lens.md) — 투자 렌즈 — 가치/추세 관점의 종목 판단 (원칙 원장 기반)
- [knowledge-hierarchy-design](knowledge-hierarchy-design.md) — 지식 위계 설계 — 관찰, 종합, 스키마 (knowledge-system.md ②의 설계 게이트 산출물)
- [knowledge-page](knowledge-page.md) — 화면 기획서 — 지식 체계 관측·주입 페이지 (`/knowledge` 개편)
- [knowledge-system](knowledge-system.md) — 지식 체계 고도화 — 3축 로드맵 (승인: 2026-07-11)
- [link-scrap](link-scrap.md) — 링크 스크랩 — URL만 올리는 채널의 원문 확장 + 미검증 소스 격리 (2026-09-09)
- [macro](macro.md) — 매크로·유동성 트래킹
- [market-regime](market-regime.md) — 시장 국면 — 홈 리스크 포스처 섹션
- [narrative-causal-graph](narrative-causal-graph.md) — 내러티브 진화 청사진 — 인과 그래프 위의 살아있는 월드모델
- [narrative-causal-phase1](narrative-causal-phase1.md) — 기획서 — 내러티브 인과 그래프 물질화 (Phase 1)
- [narrative-causal-phase2](narrative-causal-phase2.md) — 기획서 — 내러티브 인과 그래프 Phase 2 (순회·서사·머지·지식 루프)
- [phase1-etl-spine](phase1-etl-spine.md) — Phase 1 — ETL 척추 (greenfield spine)
- [phase2-rag](phase2-rag.md) — Phase 2 — RAG (검색 레이어 구현됨 / 생성은 LLM 키 대기)
- [product-v2](product-v2.md) — Explorer v2 — 서비스 기획 (Product Spec)
- [product-v3](product-v3.md) — Product v3 — Phase 2 UI/UX 대개편 스펙 (초안)
- [question-proxy](question-proxy.md) — 핵심질문 ↔ 프록시 — 분할정복 질문 트래커
- [report-v2-agents](report-v2-agents.md) — 리포트 엔진 v2 — 다중 에이전트 리서치 (analyst 팀 → bull/bear debate → 리드 판정 → 섹션 작성)
- [research-catalysts](research-catalysts.md) — 화면 기획서: 카탈리스트 캘린더
- [research-memos](research-memos.md) — 화면 기획서: 투자메모
- [research-watchlist](research-watchlist.md) — 화면 기획서: 워치리스트
- [saved-items](saved-items.md) — 저장됨 (Saved / Bookmarks) — 산출물 북마크
- [sector-aggregation](sector-aggregation.md) — 섹터 집약 — 유니버스 그룹을 커버리지 단위로
- [signals-spine](signals-spine.md) — 신호(Signals) 계층 — 척추 위의 파생 분석 (기획 기록)
- [source-dossier](source-dossier.md) — 소스 도시에 — 채널/블로그 디테일 페이지
- [telegram-briefing](telegram-briefing.md) — 텔레그램 아침 브리핑 — 읽는 브리핑에서 **누르는 브리핑**으로
- [thesis-audit](thesis-audit.md) — 논지 감사 — 내 thesis를 축적된 인과그래프에 대질 (thesis audit)
- [trade-follow](trade-follow.md) — 수출입(무역) 팔로우 — 품목별 추이 + 관련 종목
- [transcript-follow](transcript-follow.md) — Transcript 팔로우 — 미국 기업 실적발표·컨콜 수집 + 프록시 레지스트리·트래커
- [universe-curation](universe-curation.md) — 담당 유니버스 큐레이션 — 산업 맵(밸류체인)을 유니버스로 (action_thesis 후속)
- [us-briefing](us-briefing.md) — 어젯밤 미국장 브리핑 — 분위기 파악 가속기
- [us-dossier](us-dossier.md) — 미국 종목 도시에 — `/us/:ticker` 경량 통합 뷰 (축 1)
- [us-movers](us-movers.md) — US 거래대금 상위 — 홈 리스트업
- [vocab-consolidation](vocab-consolidation.md) — 어휘 통합 (vocab consolidation) — theme·macro 노드 파편화 치유

## 로컬 평가 자료

`chat-eval-runs/`는 기존 대화 평가 산출물이며 gitignore 대상이다. 새 설계의 기준 문서로 간주하지 않는다.
