# 미국 종목 도시에 — `/us/:ticker` 경량 통합 뷰 (축 1)

> 2026-07-30 기획. 배경: 미국 종목은 컨콜(transcript)·인과 노드로 **월드모델엔 있지만**, 한 종목을
> 펼쳐볼 **앞면(도시에)이 없다** — `/analyze`는 DART 기반 한국 전용. 투자 렌즈(D-090)도 KR에 먼저
> 섰다. 이 스펙은 미국 티커에 **경량 통합 도시에**를 세우고, 그 데이터 위에 렌즈를 US로 확장한다.
> (배경 결정: DECISIONS.md D-091 예정 · 렌즈: D-090 · 컨콜: D-061 · 브레인스토밍 2026-07-30)

## 관통 원칙 (비타협)

1. **경량 통합 — 재무 5탭 복제 금지** — `/analyze`의 요약·재무·밸류·사업·공시 풀세트를 US로 옮기지 않는다. 한 페이지에 핵심만: 시세·기본밸류 + 컨콜 정리 + 걸린 내러티브/인과 + US 여론 + **가치/추세 렌즈**.
2. **인식론적 비대칭** — 미국 종목에 대한 **한국 여론은 US 담론의 시차·번역**이라 보조. **US-native 1차 소스(컨콜·유튜브/팟캐스트·인물·언론)를 직접** 따라가는 게 고신호. ([[D-036]] 말뭉치 최신편향 탈출과 동형)
3. **재사용 우선** — US 기업은 이미 `entities(type='company')`로 존재(transcript_follow가 ticker→entity_id 매핑). 컨콜·인과·내러티브·피드·프록시는 **엔티티 기준으로 이미 흐른다**. 새로 필요한 건 **시세·재무 데이터(yfinance)**와 그걸 먹는 **렌즈의 market 분기**뿐.
4. **yfinance 캐시 우선** — 모든 외부 조회는 `peer_metrics`(24h) 패턴. 시세는 EOD 일별, 재무·info는 24h.
5. **렌즈는 프레임 유지** — US도 KR과 동일 규율(hypothesis·근거 역추적, [[D-090]]).

---

## 엔티티·식별 모델

- US 종목 식별자 = **티커**(NVDA, CRWV…). `entities(type='company')`에 이름으로 존재(aliases=NULL), `transcript_follow(ticker, entity_id)`가 ticker↔entity 매핑의 정본.
- **해소 함수**: `resolve_us(ticker) → (entity_id, name)` — transcript_follow 우선, 없으면 entities 이름 매칭. 렌즈·도시에 공용.
- `lens_readings.market='us'`로 KR과 구분(이미 스키마에 있음). stock_code 컬럼엔 티커 저장.

## 데이터 레이어 (신규 — yfinance)

KR은 `stock_prices`·`financial_statements`·`consensus_estimates`가 있지만 US는 없다. 최소 2개 캐시 테이블 신설(도메인 원본 `stock_prices`에 US 티커를 섞지 않는다 — KR 6자리 가정 쿼리 오염 방지):

```sql
CREATE TABLE us_prices (            -- yfinance .history 일별 OHLCV (EOD 캐시)
  ticker TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
  fetched_at TEXT, PRIMARY KEY(ticker, trade_date)
);
CREATE TABLE us_fundamentals (      -- yfinance .info/.income_stmt/.cashflow 스냅샷 (24h 캐시)
  ticker TEXT PRIMARY KEY, data_json TEXT, fetched_at TEXT
);
```
- `pipeline/us_data.py`: `fetch_prices(ticker, period='2y')`(→us_prices 멱등)·`fetch_fundamentals(ticker)`(info: price·marketCap·forwardPE·trailingPE·forwardEps / income_stmt: revenue·netIncome / cashflow: OCF·CAPEX→FCF → us_fundamentals). 캐시 히트 시 조회 없음.
- **시세 갱신**: 팔로우된 US 티커(transcript_follow active)만 EOD cron(기존 `ingest_prices` 옆) 또는 도시에 진입 시 lazy. 전체 시장 안 긁음(관통 원칙).

## 페이지 구성 — `/us/:ticker`

```
┌ NVDA · Nvidia ──────────────────────────────────┐
│ [헤더] $현재가 (+x%) · 시총 · Fwd PER · trailing (yfinance)   │
│ [컨콜] 최근 콜 핵심 정리(digest) + 프록시 델타 (D-061 재사용)  │
│ [렌즈] 가치 · 추세 카드 + 4상한 (D-090, market='us')          │
│ [월드모델] 이 종목이 걸린 내러티브 · 인과 노드 (entity 기준)     │
│ [여론] 이 종목 언급 피드 (컨콜·유튜브·인물·언론 · 한국 보조)     │
└──────────────────────────────────────────────────┘
```
- **헤더**: `us_data.fetch_fundamentals` — 시세·시총·Fwd/trailing PER. 5-state의 데이터 정박점.
- **컨콜**: 기존 `transcript` 라우터 재사용(`/transcript/company/{ticker}`·digest·proxies). 링크로 `/follow/transcripts` 상세.
- **렌즈**: 기존 `LensPage`를 `market='us'`로 렌더(아래 §렌즈 확장).
- **월드모델**: entity_id로 `narrative`/`causal` — 이 종목 노드가 등장하는 내러티브·인과 서브그래프(이미 컨콜 doc_causal이 엣지 생성, D-089).
- **여론**: `feed?stock=` 대신 **entity 언급 피드**(entity_links) — source 필터(transcript·youtube·people·news). 한국 소스는 뒤로.

## 렌즈 US 확장 (D-090 market 분기)

`investor_lens`를 market-aware로:
- `compute_reading(code, lens_type, market='kr')` — market 인자 추가. `us`면 `resolve_us`로 entity 해소, `gather_material`이 **yfinance 재료** 사용.
- **추세 렌즈 = US에서 완전 작동** — `us_prices`로 `compute_technicals`·`volume_by_price` 계산(가격 소스만 파라미터화), `market_regime` **'us'**(F&G·VIX, 이미 `get_regime().us`) 게이트. RS는 KR 유니버스 기준이라 US엔 부적합 → **지수 대비 상대강도(vs SPY/QQQ)** 또는 절대 모멘텀·52주로 대체(설계 결정).
- **가치 렌즈 = US에서 partial** — 현금의 질(yfinance OCF·CAPEX→FCF)·미래 확신(인과엣지·컨콜 프록시)·밸류(forwardPE·forwardEps)는 되나, **KR의 consensus_estimates 시계열(Fwd PER 추이·EPS 개정 방향)이 없다** → "리레이팅/디레이팅 추이"는 판단 유보로 정직 표기(5-state Partial).

## US 여론 소스 큐레이션 (Phase 3)

기존 커넥터 재사용, **구독 대상만 US로**:
- **유튜브/팟캐스트**: youtube 커넥터에 US 채널 구독(All-In, BG2, CNBC 등) — 자막→opus 정리 경로 그대로.
- **주요 인물**: 인물 추적(person)에 US 애널리스트·CEO·유명 투자자 추가.
- **US 언론 RSS**: blog 커넥터 article 카테고리에 Bloomberg·WSJ·Reuters RSS.
- 이들이 raw_documents→enrich→entity_links(US 기업)→doc_causal로 흐르면, 도시에 여론·월드모델이 자동으로 채워진다(새 배관 없음).

## 백엔드

- `pipeline/us_data.py`(yfinance 캐시)·`routers/spine_us.py`(`GET /api/spine/us/{ticker}` — 헤더+컨콜+내러티브+여론 취합, 렌즈는 기존 `/lens` 재사용). `models/us.py`. `database.py` 2 테이블.
- `investor_lens`: `resolve_us`·`gather_material` market 분기·`compute_technicals`/`volume_by_price` 가격소스 파라미터화.

## 프론트엔드

- `components/us/UsDossierPage.tsx` — 헤더+섹션 조합, `PageContainer`. `LensPage`에 `market="us"` prop 전달(티커로 `/lens` 호출).
- `App.tsx` 라우트 `/us/:ticker`, 팔로우 컨콜/유니버스에서 US 기업 클릭 시 진입. (구 spine_company `/company?name=`은 비상장/기타 유지)
- 5-state: Empty(팔로우/데이터 전 — 컨콜 대기) · Loading(Skeleton) · **Partial(가치 렌즈 컨센서스 시계열 없음 명시)** · Error(yfinance 실패) · Ideal.

## 구현 순서 (phased)

1. **Phase 1 — 도시에 껍데기 + 기존 재료**: `/us/:ticker` + yfinance 헤더(fetch_fundamentals) + 컨콜(재사용) + 내러티브/인과(entity_id) + 여론 피드. **데이터 신규 최소**(us_fundamentals만). US 티커에 즉시 앞면.
2. **Phase 2 — US 데이터 + 렌즈**: `us_prices`(yfinance OHLCV) + technicals/매물대 가격소스 파라미터화 + `investor_lens` market 분기 → **추세 렌즈(완전)·가치 렌즈(partial)** US 작동 + 4상한.
3. **Phase 3 — US 여론 소스**: youtube US 채널·인물·언론 RSS 큐레이션(구독만).

## Out of Scope (이번 착수)

- 미국 재무제표 풀 파이프라인(DART 동형) — yfinance 스냅샷으로 충분, 분기 차감·정규화 안 함.
- US 컨센서스 추정치 시계열(Fwd PER 추이·EPS 개정) — 유료 소스 필요, 가치 렌즈 partial 수용.
- 비상장(OpenAI·SpaceX 등) — 컨콜 없음, canon·feed 추적 유지([[D-061]]).
- 실시간 시세 — EOD 배치로 충분.

## 참조
- 렌즈: docs/specs/investor-lens.md([[D-090]]) · 컨콜: docs/specs/transcript-follow.md([[D-061]])
- yfinance 패턴: backend/pipeline/peers.py(get_peer_metrics 24h 캐시)·market_regime.py(get_regime().us)
- 엔티티: transcript_follow(ticker↔entity_id) · spine_company(비상장/해외 프로필)
- 인식론: docs/PHILOSOPHY.md §3(말뭉치 최신편향 탈출) · SYSTEM.md §4·§5·§6
