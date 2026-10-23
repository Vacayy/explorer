# Spec 목록과 수명주기

이 파일은 설계 탐색의 단일 진입점이다. 현재 실행 구조는 [SYSTEM](../SYSTEM.md), 결정 이유·작업 우선순위·기획 청사진은 비공개 문서(`docs/private/`, 별도 저장소)에 있다(D-234). 이 목록은 공개 문서만 싣는다.

## 홈·피드

> `../prototypes/`의 HTML 기획안과 대화 인계 문서는 로컬 전용이다(D-207) — 이 저장소를 GitHub에서 볼 때는 해당 링크가 열리지 않는다.

| 문서 | 역할 | 상태 | 다음 단계 |
|---|---|---|---|
| [앱 셸](app-shell.md) | 상단 5탭·3칸(내 목록·본문·AI 대화)·L1/L2 판정 표·화면 맥락 첨부·데스크톱 전용 | P3a 구현(2026-10-16) | P3b URL 이전·리다이렉트, P4 홈 위젯 |
| [월드모델](world-model.md) | 지금·그래프·내 판단 구성 · 서사 체크포인트 · 읽기 전용 /api/spine/world · 월드모델 위젯 4종 | P7 구현(2026-10-16) | URL 이전(/world/*), 프록시 보드, 세계관·메가 생성 통합 |
| [밸류체인 지도](value-chain.md) | 최종 수요→대만 공급 단계→한국 종목 지도 · 엣지별 시차 측정(위약 보정) · /api/spine/tw/value-chain | 1~2단계 구현(2026-10-18) | 3단계 한국 확인 신호(수출입·공시), 4단계 번지는 중 화면 |
| [대만 월매출](tw-revenue.md) | 대만 92개사 월매출 수집(TWSE·TPEx Open API·MOPS)·API·위젯 `explore.twRevenue` | 구현(2026-10-17) | 묶음·프록시 보드 연결, 대상 조정 |
| [홈 위젯 대시보드](home-widgets.md) | 위젯 계약·격자·추가 창·프리셋·서버 저장·시장 위젯 10종 | P4 구현(2026-10-16) | 탐색·포트폴리오·캔버스·월드모델 위젯(P5~P7) |
| [탐색 핵심](explore-core.md) | 종목 발견 추천 묶음 단일 목록·신호 탭·컨콜 하위 탭과 실적 캘린더·산업·섹터 3뷰 통합·탐색 위젯 4종 | P6a 구현(2026-10-16) | 섹터 원천 두 개 통합 여부 결정 |
| [캔버스](canvas.md) | 피드 디렉터리(Explorer 묶음)·AI 생성물 한 곳·공통 선택 팔레트·AI에게 묻기 다리·캔버스 위젯 4종 | P5 구현(2026-10-16) | URL 이전(`/canvas/*`), 휴면 기능 정리 |
| [홈과 통합 피드](home-feed.md) | 피드 리더·원문/시스템 카드·조회 계약(Home 시장 탭 구성은 home-widgets가 대체) | 구현·검증 완료 | 캔버스 이전(P5) |
| [데이터 신선도 점검](ops-health.md) | 결과 데이터 최신 시점 감시 레지스트리·관리자 표·홈/텔레그램 경고 계약 | 구현(2026-10-14, D-222) | 실사용에서 오탐·누락 조정, 방문 트리거 작업 항목 보강 |
| [문서 상세 관련 자료](doc-related-claims.md) | 상세 하단 논점별 관련 자료(논점 LLM·연결 검색/리랭커·원문 인용) + 유사도 기반 목록 | 구현(2026-10-14, D-233) | 실사용에서 리랭커 오판 관찰, P1 관계 표시(보강/반대/사례) |
| [개인 투자 열기](retail-heat.md) | 신용융자·예탁금·개인 거래·참여의 변화 속도와 5년 백분위, 네 국면 규칙, 과열 구간 스냅샷, 도움말 | P0 구현(2026-10-16, D-231) | 활동계좌 경로, 개인 거래(한국거래소 계정 설정 뒤) 검증 |
| [탐색 › 수출입·회사채·인물·기업활동](explore-data.md) | 서버 판정을 첫 화면 정렬·배지로(수출입 기여도·회사채 1개월 확대·인물 7일 급상승·기업활동 원공시), 수출입 라벨·이중 집계 정리, 인물 디렉토리 단일 집계, 도시에 '최근 활동' 줄, 탐색 위젯 5종 | P6b 구현(2026-10-16) | 급등 품목 관련 종목 일괄 지목(이벤트 구동), 자사주·CB 분류, 인물 이름 중복 병합 |
| [회사채 스프레드](credit-spreads.md) | AI 설비투자 기업 대표 채권 수익률·같은 만기 국채 대비 스프레드·변화·내재 부도확률, 데이터 원천은 공개 저장소 밖 로컬 어댑터 | P0 구현(2026-10-15, D-230) | 체결 크기 필터·거래량 가중, 알림 |
| [Home Risk 모니터링](home-feed.md#risk-모니터링-구현-계약-2026-09-28) | 네 추이 차트·신용 비교·수집·실험 경계 조건 | P0 구현·실데이터 검증 완료 | 실험 규칙 예측력·장기 위기 구간 검증 |

## 기획: 종목 묶음·기술적 감시

| 문서 | 역할 | 상태 | 다음 단계 |
|---|---|---|---|
| [종목 추적 위젯](stock-tracker.md) | 종목마다 위젯 하나 — 내 원칙 조건·차트·기술적 신호·수급·이슈, 조건 충족·급등락·공시·새 신호 텔레그램 알림. 위젯 틀 multi·pick·titleOf 확장 | 구현(2026-10-20) | 가격 손절선은 진입 때 사용자가 입력, 조건 이력 화면 |
| [종목 묶음과 기술적 감시](portfolio-watch.md) | 포트폴리오·관심 종목을 묶음 하나로 통일, 종목별 조건의 일일 평가·신호 화면 계약 | P0 구현(2026-09-19, D-185): 묶음·규칙·일일 평가·신호 화면·레거시 이관 | P1: 수량·매수가 입력 UI, 매수가 기준 조건, 브리핑 한 줄 |
| [포트폴리오 거래 원장](portfolio-ledger.md) | 매수·매도·입출금 원장, 비율 전용 수익률(TWR)·비중, `/portfolio` 화면 계약과 프라이버시 경계 | P0 구현(2026-10-08, D-212) | P1: 배당·수수료, 벤치마크 대비, AI 비율 요약 도구 |
| [포트폴리오 인텔리전스](portfolio-intelligence.md) | 공통 변수(노출)·다가오는 이벤트·자료 흐름·논지 감시·운용 원칙 감시·관심 이유 감시 | P0 구현(2026-10-08, D-216 · 원칙/관심 이유 2026-10-14, D-227) | P1: 국내 숫자 지표 어댑터, 공통 변수 뉴스 알림, 그래프 노드 중복 정리 |

## 구현: 스터디 모드

| 문서 | 역할 | 상태 | 다음 단계 |
|---|---|---|---|
| [스터디 모드](study-mode.md) | 원문 읽기·영속 주석·질문 context·추가 리서치의 단일 계약 | 독립 프로젝트·의도별 하이라이터·표시별 AI/후속 질문·FIFO·통합 노트 구현 | 관련 자료 검색·웹 확인·실제 모델/브라우저 검증; 미수집 URL 자동 수집은 후속 |

## 구현·검증: 시장 데이터 CodeAct

제품 흐름과 클릭 가능한 화면 예시는 발견에서 판단까지 — HTML 기획안(로컬 전용 `prototypes/discovery-research-plan.html`)에서 확인한다. 후속 기능 설계이며, 가상 자료로 된 예시와 실제 구현·자료 현황을 구분한다.

| 문서 | 역할 | 상태 | 다음 단계 |
|---|---|---|---|
| [시장 데이터 CodeAct 분석](market-codeact.md) | 기존 시세의 읽기 전용 스냅샷·격리 실행·조건/결과·AG-UI/A2UI 계약 | macOS 구현·실제 모델 검증·별도 NAVER 이력 137만 행 수집. D-182 독립 발견 진입·후보/차트·원클릭 조사·선택 기업 자료 준비 구현 | 후속 질의의 조건 보존·조건식 확장·발견 맥락 전달, 공식 달력·미평가 확인 |
| [기술적 읽기 층](technical-reading.md) | 비전문가용 번역 층 — 자동 캔버스·한 줄 읽기(규칙 문장)·상황 렌즈 8개·후보→패널 진입 | 구현(2026-09-22, D-198), 격리 루트 실측 완료 | 렌즈 기본값에 시총·거래량 하한 검토, 실사용에서 문장 체감 확인 |
| [차트 구조 그리기](chart-structure.md) | 종목 하나의 채널·추세선을 결정적으로 그리는 계약 — 계산·해석 규칙·API·화면 5-state | P0·P1 구현(2026-09-21, D-195·D-196): 종목 발견 mode=draw 카드 + 기업 페이지 패널, 레벨·여러 종목·조건 변환·모델 보조·프리셋 | 실사용에서 프리셋 문장·조건 근사의 체감 확인, 사용자가 손으로 선을 옮기는 편집은 범위 밖 |
| [종목 발견 성능](market-discovery-performance.md) | 발견 실행의 단계별 병목 지도·측정 방법·개선 전후 기록 | 2026-09-21 측정: 자연어 46s(모델 65%)·선택 12~21s. finish 콜·스냅샷 재생성·순수 Python 계산이 병목 | 개선 1~5 적용하며 전후 수치 갱신, 해석 콜 haiku/Jev A/B |
| [시장 전략 도구](market-strategies.md) | 시세동향 19·지표신호 25·순위 6개 정의와 계산 기준 | 카탈로그·자연어 조건식·독립 검증, 전략 버전·재실행·목적/관측 추천 구현 | 검색 정의/실행 버전 구분·저장/재실행, 이유 있는 추천, 미지원 자료 확보 |
| [시장 전략 비교 백테스트](market-backtest.md) | 7개 기준·복합 전략의 사전 고정 조건, 다음 시가 체결, 비용·현금·평가 계약 | **제거됨 (D-241)** — 화면·API·엔진 삭제 | - |
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

- [analyze-summary](analyze-summary.md) — 화면 기획서: 요약 페이지 (Resizable 패널 레이아웃)
- [causal-worldview](causal-worldview.md) — 기획서 — 세계관 뷰 (인과 그래프 노드-링크 시각화)
- [chat-agent](chat-agent.md) — 대화 에이전트 아키텍처 — 라우터·도구·멀티턴 메모리 (B 단계, 2026-09-08)
- [chat-harness](chat-harness.md) — 대화(챗봇) 하네스 — 현황 분석 + 아키텍처 레퍼런스 (2026-09-08)
- [chat-page](chat-page.md) — /chat 화면 리뉴얼 — 메신저에서 "판단 도구"로 (2026-09-08)
- [chat-retrieval](chat-retrieval.md) — 대화 검색 품질 — 청크 인덱스 · 문맥 접두어 · 리랭커 (C 단계, 2026-09-08)
- [discover-screener](discover-screener.md) — 화면 기획서: 스크리너 — **제거됨 (D-241)**
- [discover-signals](discover-signals.md) — 화면 기획서: 시그널 피드 — **현행 신호 탭은 [explore-core](explore-core.md) §2**
- [doc-causal-extraction](doc-causal-extraction.md) — 기획서 — 문서 레벨 인과 추출 (제2 인과 공급원)
- [doc-synthesis](doc-synthesis.md) — 문서 교차 종합 (Doc Synthesis) — 고른 문서들을 엮어 읽기 — **제거됨 (D-241)**
- [dock-navigation](dock-navigation.md) — 셸 대개편 — 헤더·네비 제거, macOS 도크형 내비게이션 (2026-09-08) — **대체됨 → [app-shell](app-shell.md)**
- [follow-rail](follow-rail.md) — 팔로우 레일 — 사이드바 통합 — **대체됨 → [app-shell](app-shell.md) §4 내 목록**
- [geo-scope](geo-scope.md) — geo_scope — 인과 주장에 장소 정박 (A방향: 보편 노드 + 스코프 있는 엣지)
- [hypothesis-vault](hypothesis-vault.md) — 가설·메모 Vault — 소유권 분할 설계
- [ia-map](ia-map.md) — IA 지도 — 페이지 진입로 & 화면 구성 (현행)
- [knowledge-page](knowledge-page.md) — 화면 기획서 — 지식 체계 관측·주입 페이지 (`/knowledge` 개편) — 화면 배치(승격 대기 큐 등)는 **[world-model](world-model.md) §3이 대체**
- [image-reading](image-reading.md) — 이미지 해석 — 본문 속 차트·표를 '무엇을 말하려는가'로 바꿔 넣는다 + 블로그 줄바꿈 정규화 (구현 2026-10-23, 다음: 텔레그램·블로그 백로그 결정)
- [link-scrap](link-scrap.md) — 링크 스크랩 — URL만 올리는 채널의 원문 확장 + 미검증 소스 격리 (2026-09-09)
- [macro](macro.md) — 매크로·유동성 트래킹
- [market-regime](market-regime.md) — 시장 국면 — 홈 리스크 포스처 섹션
- [narrative-causal-phase1](narrative-causal-phase1.md) — 기획서 — 내러티브 인과 그래프 물질화 (Phase 1)
- [narrative-causal-phase2](narrative-causal-phase2.md) — 기획서 — 내러티브 인과 그래프 Phase 2 (순회·서사·머지·지식 루프)
- [phase1-etl-spine](phase1-etl-spine.md) — Phase 1 — ETL 척추 (greenfield spine)
- [phase2-rag](phase2-rag.md) — Phase 2 — RAG (검색 레이어 구현됨 / 생성은 LLM 키 대기)
- [question-proxy](question-proxy.md) — 핵심질문 ↔ 프록시 — 분할정복 질문 트래커 + 프록시 보드(D-240, 결정적 어댑터·보드 API 구현 계약)
- [research-catalysts](research-catalysts.md) — 화면 기획서: 카탈리스트 캘린더 — **제거됨 (D-241)**
- [research-memos](research-memos.md) — 화면 기획서: 투자메모 — **제거됨 (D-241)**
- [research-watchlist](research-watchlist.md) — 화면 기획서: 워치리스트 (대체됨 → portfolio-watch 기본 관심 묶음)
- [saved-items](saved-items.md) — 저장됨 (Saved / Bookmarks) — 산출물 북마크
- [sector-aggregation](sector-aggregation.md) — 섹터 집약 — 유니버스 그룹을 커버리지 단위로
- [signals-spine](signals-spine.md) — 신호(Signals) 계층 — 척추 위의 파생 분석 (기획 기록)
- [source-dossier](source-dossier.md) — 소스 도시에 — 채널/블로그 디테일 페이지
- [telegram-briefing](telegram-briefing.md) — 텔레그램 아침 브리핑 — 읽는 브리핑에서 **누르는 브리핑**으로
- [trade-follow](trade-follow.md) — 수출입(무역) 팔로우 — 품목별 추이 + 관련 종목
- [transcript-follow](transcript-follow.md) — Transcript 팔로우 — 미국 기업 실적발표·컨콜 수집 + 프록시 레지스트리·트래커
- [transcript-momentum](transcript-momentum.md) — 실적 발언 모멘텀 — 나스닥 100 컨콜·SEC 실적 보도자료에서 직전 분기 대비 새·가속 성장 동인 추리기 (D-217)
- [us-briefing](us-briefing.md) — 어젯밤 미국장 브리핑 — 분위기 파악 가속기
- [us-dossier](us-dossier.md) — 미국 종목 도시에 — `/us/:ticker` 경량 통합 뷰 (축 1)
- [us-movers](us-movers.md) — US 거래대금 상위 — 홈 리스트업
- [vocab-consolidation](vocab-consolidation.md) — 어휘 통합 (vocab consolidation) — theme·macro 노드 파편화 치유

## 로컬 평가 자료

`chat-eval-runs/`는 기존 대화 평가 산출물이며 gitignore 대상이다. 새 설계의 기준 문서로 간주하지 않는다.
