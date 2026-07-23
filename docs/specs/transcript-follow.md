# Transcript 팔로우 — 미국 기업 실적발표·컨콜 수집 + 프록시 레지스트리·트래커

> 2026-07-23 기획. BACKLOG "리포트·액션 씨어리 후속 트랙" P0. 배경: 리포트의 **핵심 질문**(D-049)이
> 던지는 관찰 프록시(예: 하이퍼스케일러 CAPEX 추이)가 지금은 "미정"으로 비어 있다. 그걸 **실데이터로
> 채우는 1차 소스**가 실적발표·컨콜 transcript. 커넥터(수집)와 프록시 트래커(활용)를 한 묶음으로 착수.

## 관통 원칙 (비타협)
1. **기업 단위 팔로우** — 유니버스/팔로우처럼 사용자가 기업을 골라 구독. 전체 시장을 긁지 않는다(비용·소음).
2. **미국 기업 위주** — 한국 기업은 이미 DART·pykrx로 커버. transcript는 미국 빅테크·AI·에너지 중심.
3. **프록시는 사람이 세팅 → 기계가 트래킹** (D-048). 어떤 수치를 볼지는 편집 판단, 갱신은 자동.
4. **캐시 우선** — 모든 외부 호출은 `cache_service` 패턴. transcript는 불변(발표 후 고정)이라 영구 캐시.
5. **커넥터는 provider-추상** — 한 제공처에 락인되지 않게 어댑터 인터페이스로. 무료→유료 전환 무마찰.

---

## API 제공처 리서치 (2026-07 조사)

실적 컨콜 transcript는 상용 API가 성숙해 있어 **직접 크롤 불필요**. 미국 상장사 위주면 아래 후보들이 커버.

| 제공처 | 무료 티어 | 미국 커버리지 | 이력 | 화자 라벨 | 오디오 | 파이썬 SDK | 판단 |
|---|---|---|---|---|---|---|---|
| **Financial Modeling Prep (FMP)** | 250 req/day, 500MB/mo | 광범위 | 10+년 | △ | ✗ | ✓ | **1차 후보** — 무료 요청 예산 넉넉 + `transcript-dates-by-symbol`로 신규 콜 폴링 용이 |
| **earningscall.biz** | 브라우저 열람 무료, API는 유료(저렴·투명) | 9,000+ | 있음 | ✓ (CEO/CFO/analyst 역할 ID) | ✓ | ✓ 공식 | **업그레이드 경로** — 구조 최상(화자·역할), SDK 깔끔. 유료지만 스타트업 친화 |
| **Alpha Vantage** | 25 req/day, 5/min | 있음 | 15+년 | △ | ✗ | ✓ | **폴백** — LLM 감성점수 내장. 단 25/day는 백필에 빠듯 |
| **API Ninjas** | 무료(상업용 불가—개인은 무관) | 주요 상장사 | 2000~ | ✗ | ✗ | ✗ | 단순·저렴, 구조 약함 |
| **Finnhub** | 무료(rate limit) | 글로벌 | - | △ | ✓ 라이브 | ✓ | 라이브 스트리밍 강점, transcript는 부차 |
| **ROIC.ai** | 5 req/min, 2년 | 전 상장사 | 2년(무료) | - | ✗ | - | 무료 이력 짧음 |
| **Quartr** | 없음(영업 문의) | 14,500+ / 65개 시장 | 있음 | ✓ | ✓ | ✗ | 품질 최상·AI 최적화지만 **개인 도구엔 과함**(엔터프라이즈 가격) |

**권장 전략** — MVP는 **FMP 무료 티어**(요청 예산·dates-by-symbol 폴링)로 시작, 구조 품질이 필요해지면
**earningscall.biz**로 교체(화자·역할 라벨이 프록시 추출·발언 인용에 유리). 커넥터를 provider-추상으로
짜서 어댑터만 바꾸면 되게 한다. Alpha Vantage는 감성점수가 필요할 때 폴백.

> API 키는 `.env`에 `FMP_API_KEY` / `EARNINGSCALL_API_KEY` / `ALPHAVANTAGE_API_KEY`. 활성 provider는
> `TRANSCRIPT_PROVIDER=fmp|earningscall|alphavantage` 로 스위치.

**출처**: [koyfin 2026 비교](https://www.koyfin.com/blog/top-earnings-call-transcripts-platforms/) · [earningscall.biz best-apis-2026](https://earningscall.biz/blog/best-earnings-call-apis-for-developers-2026) · [FMP transcript docs](https://site.financialmodelingprep.com/developer/docs/stable/search-transcripts) · [FMP pricing](https://site.financialmodelingprep.com/pricing-plans) · [Alpha Vantage docs](https://www.alphavantage.co/documentation/) · [Quartr API](https://quartr.com/products/quartr-api)

---

## 온톨로지 편입 + LLM 정리 (핵심 — 사일로 금지)

**transcript 전문은 별도 테이블에 가두지 않고 `raw_documents`(모든 소스의 단일 현관, `source_type='transcript'`)로
넣는다.** 그러면 기존 파이프라인이 자동으로 흐른다 — 새 배관을 만들지 않는다:

```
FMP fetch → raw_documents(source_type='transcript', markdown=전문, source_id=ticker:year:period)
   │
   ├─ enrich.py      → 태깅 + entity_links (transcript ↔ 해당 기업 entity 연결)
   ├─ doc_causal.py  → 문서 레벨 인과 추출 → entity_relations = ★온톨로지 편입★ (제2 인과 공급원, D-028)
   ├─ digests.py     → LLM 핵심 정리 (유튜브 per-doc digest 경로에 'transcript' 추가 — "유튜브처럼")
   └─ doc_vec        → 임베딩 → RAG·관련문서
```

→ **온톨로지 편입 = YES**, 단 원래 기획서(사일로 테이블)를 이렇게 고쳐야 성립. transcript는 블로그·유튜브와
같은 현관을 쓰는 **고신호 인과 공급원**이 된다(컨콜은 경영진 1차 발언이라 doc_causal 품질이 특히 높음).
digest_status 게이트(현재 `source_type='youtube'`)를 `IN ('youtube','transcript')`로 확장 → 컨콜도 LLM 정리.

## 데이터 모델

```sql
-- 팔로우 대상 (기업 단위 구독)
CREATE TABLE transcript_follow (
  ticker        TEXT PRIMARY KEY,      -- 미국 티커 (AAPL, NVDA, CRWV, IREN ...)
  company_name  TEXT NOT NULL,
  entity_id     INTEGER,              -- entities 테이블 연결(있으면). 유니버스/팔로우와 크로스링크
  group_label   TEXT,                  -- 'M7' | 'hyperscaler' | 'ai-datacenter' | 'energy' | 'cpo' | 'web3' ...
  active        INTEGER DEFAULT 1,
  added_at      TEXT
);

-- transcript 인덱스 (얇은 메타 — 전문(body)은 raw_documents에 있고 여기선 안 중복 저장)
CREATE TABLE transcripts (
  id            INTEGER PRIMARY KEY,
  raw_doc_id    INTEGER NOT NULL,      -- ★전문·인과·정리·임베딩은 이 raw_documents 행을 통해 파이프라인에 흐름
  ticker        TEXT NOT NULL,
  fiscal_year   INTEGER,
  fiscal_period TEXT,                  -- 'Q1'..'Q4' | 'FY'
  call_date     TEXT,
  provider      TEXT,                  -- 어느 어댑터로 수집했는지
  fetched_at    TEXT,
  UNIQUE(ticker, fiscal_year, fiscal_period)
);
```

-- 프록시 레지스트리 (사람이 세팅 — "무엇을 볼지")
CREATE TABLE proxy_registry (
  id            INTEGER PRIMARY KEY,
  key           TEXT NOT NULL,         -- 'hyperscaler_capex' | 'oai_arr' | 'dc_groundbreaking'
  label         TEXT NOT NULL,         -- '하이퍼스케일러 CAPEX 추이'
  narrative_id  INTEGER,              -- 어느 지배 내러티브의 프록시인가 (D-049 핵심질문과 연결)
  tickers       TEXT,                  -- 관련 티커 CSV (추출 대상 컨콜)
  unit          TEXT,                  -- '$B' | '%' | 'MW' ...
  extract_hint  TEXT,                  -- 추출용 프롬프트 힌트 ("CAPEX 가이던스 수치·전분기 대비")
  active        INTEGER DEFAULT 1,
  created_at    TEXT
);

-- 프록시 관측치 (기계가 트래킹 — transcript에서 추출한 값, 시계열)
CREATE TABLE proxy_observations (
  id            INTEGER PRIMARY KEY,
  proxy_id      INTEGER NOT NULL,
  transcript_id INTEGER,              -- 출처 컨콜 (추적성)
  observed_at   TEXT,                  -- 관측 시점(컨콜 날짜)
  value_num     REAL,                  -- 파싱된 수치(가능하면)
  value_text    TEXT,                  -- 원문 인용/맥락 (수치화 불가 시)
  direction     TEXT,                  -- 'up' | 'down' | 'flat' vs 직전
  confidence    REAL,
  created_at    TEXT
);
```

**기본 팔로우 세트 시드** (미국 기업, 사용자 확정 2026-07-23 — 전력반도체·바이오 제외, 비상장 제외):
- **M7**: AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA
- **하이퍼스케일러/클라우드**: ORCL (M7 중복 제외)
- **나스닥 최상위/반도체**: AVGO, AMD
- **AI 데이터센터**: CRWV(코어위브), IREN(아이렌), NBIS(네비우스) *(ORCL은 위)*
- **우주/AI 하드웨어**: RKLB(로켓랩) *(비상장 스페이스X의 상장 프록시)*
- **에너지**: VST(비스트라), CEG(콘스텔레이션), 주요 발전·원전·천연가스
- **CPO(Co-Packaged Optics)**: COHR(코히런트), LITE(루멘텀)
- **소프트웨어**: SNOW(스노우플레이크) *(비상장 Databricks의 상장 대안)*
- **Web3**: COIN(코인베이스), HOOD(로빈후드)

> ⚠️ **비상장사 처리** (확정): OpenAI·Anthropic·SpaceX·Databricks·Securitize는 컨콜이 없다.
> transcript_follow에 넣지 않고, **인물사/뉴스(canon·feed)로 별도 추적** 유지(이미 있음). 상장 시 편입 후보 표시.
> **제외**(이번 세트): 전력 반도체·바이오 — 추후 필요 시 추가.
> 정확한 티커·회사명은 시드 스크립트에서 확정(위 목록 기준, 섹터 "주요…"는 대표 1~2개로).

---

## 커넥터 설계 (provider-추상)

```
pipeline/transcript.py
  class TranscriptProvider(Protocol):
      list_available(ticker) -> [{year, period, date}]   # 신규 콜 폴링
      fetch(ticker, year, period) -> {title, body, raw}   # 전문 수집
  FMPProvider / EarningsCallProvider / AlphaVantageProvider  (어댑터)
  get_provider() -> env TRANSCRIPT_PROVIDER 로 선택
```

**수집 흐름 (cron, ops.run_job로 게이트)**:
1. `transcript_follow` active 티커 순회
2. provider.list_available → 이미 `transcripts`에 있는 것 제외(불변 캐시)
3. 신규 콜만 fetch → **`raw_documents`(source_type='transcript') INSERT** → `transcripts` 인덱스 행 INSERT(raw_doc_id FK)
4. 이후는 기존 파이프라인이 인수: enrich → doc_causal(온톨로지) → digests(LLM 정리) → doc_vec
5. 해당 티커가 걸린 `proxy_registry` 항목 → 추출 잡 큐잉 (digest와 별개로 프록시 특정 수치 추출)

**프록시 추출 (haiku/sonnet)**:
- 신규 transcript × 관련 proxy_registry → LLM에 `extract_hint`로 해당 수치/발언 추출
- → `proxy_observations` INSERT (value_num/value_text/direction)
- 실패·부재 시 조용히 스킵(거짓 수치 금지 — 정직 원칙)

---

## 화면 (IA 결정 2026-07-23)

세 후보 중 **전용 페이지를 본진, 피드 '컨콜' 탭을 공짜 보조**로. 기업 페이지(옵션 1)는 `/analyze`가
DART 기반 **한국 종목 전용**이라 미국 티커엔 페이지가 없어 **보류**(미국 기업 도시에 신설 시 재검토).

### 1. Transcript 전용 페이지 (`/follow/transcripts` — 팔로우 모드 하위 탭) — **2분할 브라우저**
```
┌ Transcript ───────────────────────────────────┐
│ ▼ M7        │  NVDA — FY26 Q1 (5/28)           │
│   AAPL      │  ┌ LLM 핵심 정리 ──────────────┐ │
│  ▶NVDA      │  │ · 데이터센터 수요 …          │ │
│   MSFT      │  │ · CAPEX 가이던스 상향 …      │ │
│ ▼ AI DC     │  └────────────────────────────┘ │
│   CRWV      │  프록시: CAPEX 🔺 / ARR –        │
│   IREN      │  ── 원문 전문 (펼침) ──          │
│ ▼ 에너지     │  Operator: Thank you…            │
└─────────────────────────────────────────────────┘
```
- **좌 레일**: 팔로우 기업을 그룹별(M7·AI DC·에너지·CPO·Web3…) 접힘 리스트. 각 기업 옆 미읽음 배지·최근 분기.
  선택 시 하이라이트. 상단 "+ 기업 추가"(티커 검색 → transcript_follow INSERT) + 구독 on/off.
- **우 본문**: 선택 기업의 최신 콜 → **LLM 핵심 정리(digest) 먼저**(유튜브식) → **프록시 델타 줄**
  (이 컨콜에서 갱신된 proxy_observations) → **원문 전문(펼침)**. 상단에 분기 셀렉터(과거 콜 전환).
- 좌 레일이 곧 구독 관리, 별도 관리 화면 불필요.

### 2. 피드 '컨콜' 소스 탭 (`/feed?source=transcript`) — 거의 공짜
- FEED_TABS에 `{ key: "transcript", label: "컨콜" }` 한 줄 추가. raw_documents(source_type='transcript')를
  기존 피드 렌더가 그대로 시간순 노출 → "방금 어떤 컨콜이 떴나" 스트림. 상세는 전용 페이지로 링크.

### 3. 프록시 대시보드 (전용 페이지 상단 탭 or 내러티브/리포트 인라인)
- proxy_registry 항목별 카드: label · 최신 관측치 · direction 화살표 · 미니 스파크라인(proxy_observations 시계열)
- 출처 링크(어느 컨콜에서 나온 값인지 → 추적성)
- **리포트 핵심질문(D-049)의 "관찰 프록시" 줄이 여기로 링크** — "미정" → 실데이터

### 5-state (docs/policies/ui-states.md 준수)
- **Empty**: 팔로우 0 → 좌 레일에 "미국 기업을 팔로우해 실적 컨콜을 모으세요" + 기본 세트 원클릭 시드 버튼
- **Loading**: Skeleton (좌 레일 + 우 본문)
- **Partial**: 팔로우는 있으나 아직 수집 전 → 우 본문 "다음 실적 대기 중"
- **Error**: 커넥터 실패 → ErrorState + 재시도(provider 상태 표시)
- **Ideal**: 좌 그룹 리스트 + 우 정리·프록시·원문

---

## 백엔드
- `routers/transcript.py`: GET `/transcripts/follow`(목록) · POST `/transcripts/follow`(추가/해제) ·
  GET `/transcripts/{ticker}`(분기 리스트) · GET `/transcripts/{ticker}/{year}/{period}`(전문) ·
  GET `/proxies`(레지스트리+최신관측) · POST `/proxies`(세팅) · GET `/proxies/{id}/observations`(시계열)
- `models/transcript.py`: Pydantic 스키마
- `main.py` 라우터 등록 · `database.py init_db()` 4개 테이블 추가
- cron: `scripts/collect_transcripts.py` + `scripts/extract_proxies.py` → `ops.run_job`로 관리자 게이트

---

## 구현 순서
1. **DB(follow·transcripts 인덱스·proxy 2종) + FMP 어댑터** → M7 시드 →
   raw_documents(source_type='transcript') 적재 검증 → 기존 enrich·doc_causal이 온톨로지에 엣지 만드는지 확인
2. **digest 경로 확장** — digest_status 게이트에 'transcript' 추가 → 컨콜 LLM 핵심 정리 생성 확인
3. **Transcript 전용 페이지** (2분할 브라우저, 5-state) → 기본 세트 원클릭 시드 버튼
   + **피드 '컨콜' 탭** 한 줄 추가(FEED_TABS) — 거의 공짜
4. **proxy_registry + 추출 잡** → 프록시 대시보드 → 리포트 핵심질문(D-049)과 링크
5. **cron 편입** (ops.run_job 게이트 + 관리자 페이지 노출) — earningscall.biz 어댑터는 필요 시 추가

## Out of Scope (이번 착수)
- 라이브(실시간) 컨콜 스트리밍 — 발표 후 배치 수집으로 충분
- 오디오 저장 — 텍스트만
- 한국 기업 transcript — DART·pykrx로 대체
- 비상장사(OpenAI·Anthropic·SpaceX·Databricks) — 상장 시 편입, 그전엔 canon·feed로 추적
- 프록시 자동 수치 차트의 정교한 파싱(단위 정규화) — 1차는 value_text 인용 우선, 수치화는 점진

## 참조
- 핵심질문·프록시 근거: docs/DECISIONS.md D-048·D-049 · 리포트 엔진: docs/specs/report-v2-agents.md
- 팔로우/유니버스 연결: docs/specs/universe-curation.md · docs/specs/follow-rail.md
