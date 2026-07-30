# 투자 렌즈 — 가치/추세 관점의 종목 판단 (원칙 원장 기반)

> 2026-07-30 기획. 배경: 수집·인과그래프·내러티브·리포트·프록시로 재료는 충분히 쌓였다. 그러나
> "그래서 이게 좋은 주식인가?"에 답하려면 **투자자의 관점**이 들어가야 한다. 기업/산업 분석을 넘어선
> 판단은 취향이 아니라 **원칙**이어야 하므로, 가장 대표적인 두 관점 — **가치투자(성장주도 펀더멘탈)**와
> **추세추종** — 을 먼저 세운다. (배경 결정: DECISIONS.md D-090 예정)

## 관통 원칙 (비타협)

1. **렌즈 = 프레임이지 판정이 아니다** — 출력은 "매수/매도" 오라클이 아니라 "이 관점이라면 무엇을 보고, 이 종목이 그 기준에서 어떻게 읽히는가". epistemic_type=hypothesis(주황), 근거는 그래프·펀더·프록시로 역추적. (PHILOSOPHY §2 "사실은 그래프로, 프레임은 렌즈로", D-030 계승)
2. **투자관 = 원칙 원장** — 두 관점의 정의는 코드 상수가 아니라 **사람이 소유·정교화하는 마크다운**(`vault/principles/value.md`·`trend.md`). 소유권 분할(vault) 규율: 사람이 원본, 계속 append·정교화. (PHILOSOPHY §5)
3. **원칙 전문을 압축 없이 주입** — 렌즈 프롬프트는 rubric 몇 줄이 아니라 원장 **전문**. 압축하면 본질이 흐려진다. 렌즈 품질 = 원칙의 밀도·정교함의 함수. (사용자 지침 2026-07-30)
4. **재사용 우선, 새 무거운 파이프라인 금지** — 종목 재료는 `compute_brief`·`build_upside_model`·`technicals`·`market_regime`·인과엣지·프록시에서 가져온다. 렌즈는 그 위에 얇은 종합 LLM 콜 1회. (CLAUDE.md 간결성)
5. **불일치가 신호** — 두 렌즈는 자주 갈린다. 억지로 합의시키지 않고 갈린 지점을 드러낸다.

---

## 원칙 원장 (source of truth)

- `vault/principles/value.md` — 가치 렌즈 원칙 전문 (세계관: 펀더멘탈의 미래를 확신한다)
- `vault/principles/trend.md` — 추세 렌즈 원칙 전문 (세계관: 시장을 받아들이고 대응한다)
- 렌즈 실행 시 해당 파일 전문을 읽어 프롬프트에 통째 주입. 파일 내용 해시(`principles_hash`)가 바뀌면 저장된 판독은 stale → 재생성 유도.
- **원칙은 살아있다** — 사용자가 원장을 깎을 때마다 렌즈가 정교해진다. 1차엔 UI 편집기 없이 파일 직접 편집(오버빌드 회피). 필요해지면 지식 주입처럼 콘솔·버전관리로 승격.

## 렌즈 정의 요약 (전문은 원장)

### 가치 렌즈 (성장주도 펀더멘탈)
무게중심은 **"이익·현금흐름이 극대화될 것이라는 확신의 설득력"** (현재 장부가 아니라 미래, 삼양식품형). 확신은 구조적 동인(수요 폭발·점유율·가격결정력·TAM·락인·신사업 체질 개선)에서 나오고, 현금의 질(FCF·accruals)로 검증하며, **밸류 상한은 거부권**(미래까지 이미 다 반영됐으면 탈락). 섹터 무관, 펀더 최우선. 상방보다 하방·비대칭 먼저.

### 추세 렌즈 (추세추종)
**시장은 틀리지 않는다** — 예측이 아니라 대응. 위치(초입·소외 vs 성숙·어깨)는 다우 국면·매물대·이평·볼밴으로 **맥락 제시하되 단정하지 않는다**. 추세 훼손 조건(=손절 라인)을 사전 정의, 안티-물타기, 국면 게이트. 진입 근거에 앵커링하지 않는다.

## 불일치 = 4상한 (knowledge_state 재사용)

축: **가치 확신(펀더 근거 강도)** × **추세 위치(시장이 이미 반영한 정도)**. 위치는 소프트(범주형).

| | 초입·소외 | 성숙·과열 |
|---|---|---|
| **가치 확신 ↑** | 진짜 기회 (펀더 좋고 시장 아직 안 붙음) | 좋은 회사, 늦은 진입 (매물대·되돌림 부담) |
| **가치 확신 ↓** | 회피/노이즈 | 모멘텀·투기 과열 (진자 경고) |

`knowledge_state`의 salience×conviction 4상한과 같은 인식론(주목받지 않은 확신=기회 / 주목받는 확신=선반영). 카드는 이 방위 + 각 렌즈의 서술을 함께 보여준다.

## 데이터 · 재사용 맵

| 렌즈 | 기준 | 재사용 소스 |
|---|---|---|
| 가치 | 미래 확신 동인 | 관련 내러티브·인과엣지(`entity_relations` CAUSES/BENEFITS_FROM, corroborated_by)·추적 프록시(`proxy_observations`) |
| 가치 | 현금의 질 | `financial_statements` `sj_div='CF'`(영업/투자/재무활동 현금흐름) — FCF=영업CF−CAPEX, 이익의 질=영업CF/순이익·accruals. account_nm 정규화(`_normalize_account_name`). US=yfinance cashflow |
| 가치 | 밸류 상한 | 12M Fwd PER 추이(`consensus_estimates`)·EPS 개정, `stock_brief`의 정량 |
| 가치 | 상방/하방 | `upside_model.build_upside_model`(보수/기본/낙관 범위·하방 지지선·무효화) |
| 가치 | 종합 재료 | `stock_brief.compute_brief`(컨센서스·수급·상승분해·기술 정합 종합) |
| 추세 | RS·추세 구조 | `technicals.compute_technicals`(RSI·이평갭 20/60/120·볼밴 %B), `sector_rs`, 다우이론(리포트 로직) |
| 추세 | **매물대** | **신규** — `stock_prices` 가격대별 거래량 히스토그램(고거래 노드=지지/저항, 현재가 위치). LLM 0 |
| 추세 | 국면 게이트 | `market_regime.get_regime`(오실레이터 20EMA×변동성) |
| 추세 | 모멘텀·특징일 | `feature_days`, `signals`(high_52w·volume_spike) |

## 데이터 모델

```sql
CREATE TABLE lens_readings (
  id             INTEGER PRIMARY KEY,
  stock_code     TEXT NOT NULL,     -- KR 종목코드 | US 티커
  market         TEXT NOT NULL,     -- 'kr' | 'us'
  lens_type      TEXT NOT NULL,     -- 'value' | 'trend'
  body           TEXT,              -- 판독 본문(md) — 원칙에 비춘 서술, 근거 인용
  stance         TEXT,              -- 범주형: value=확신(강|중|약) / trend=위치(초입|진행|성숙|훼손)
  signals_json   TEXT,              -- 근거 역추적(엣지 id·프록시·지표 스냅샷)
  principles_hash TEXT,             -- 원장 버전(바뀌면 stale)
  material_hash  TEXT,              -- 재료 스냅샷 해시(멱등·stale)
  created_at     TEXT,
  UNIQUE(stock_code, lens_type, principles_hash, material_hash)  -- append-only 히스토리(판단 변화 추적)
);
```
- append-only(리포트·브리프 철학, D-047) — 최신=created_at DESC. 원칙·재료 동일하면 저장분 반환(LLM 0).
- 4상한 위치는 두 렌즈 최신 `stance`에서 결정적으로 계산(별도 저장 불필요).

## 백엔드

- `pipeline/investor_lens.py`:
  - `load_principles(lens_type)` — vault/principles/*.md 전문 읽기 + hash
  - `gather_material(conn, stock_code, lens_type)` — 위 재사용 맵대로 재료 취합 (LLM 0)
  - `compute_reading(stock_code, lens_type, refresh=False)` — 원칙 전문 + 재료 → **sonnet** 종합(본문+stance+signals). 캐시 멱등(principles_hash·material_hash)
  - `volume_by_price(conn, stock_code, window)` — 매물대 계산 (technicals.py에 두어도 됨)
  - `quadrant(conn, stock_code)` — 두 stance → 4상한 위치 (LLM 0)
- `routers/spine_lens.py`:
  - `GET /api/spine/lens?stock=&market=` — 두 렌즈 최신 판독 + 4상한 위치 (저장분, LLM 0)
  - `POST /api/spine/lens/compute?stock=&type=&refresh=` — 생성(sonnet, 멱등)
  - `GET /api/spine/lens/history?stock=&type=` — append-only 판독 이력
- `models/lens.py` Pydantic · `main.py` 등록 · `database.py init_db()` 테이블 추가
- 모델 티어: 종합=sonnet(브리프·기술 재료가 이미 정제돼 있어 opus 불요). 재료·매물대·4상한=LLM 0.

## 프론트엔드

- `shared/LensCard.tsx` — 렌즈 1개 카드(제목·stance 배지·서술 본문·근거 칩[엣지·프록시·지표로 딥링크]). 가치/추세 2장 + 상단 **4상한 미니뷰**(불일치 배지).
- **위치**: 종목 디테일 `/analyze/:code`에 **'렌즈' 탭 신설** (또는 summary 하단 섹션). 요약·재무·밸류·사업·공시 옆.
- 근거 칩 → 인과엣지는 `/knowledge/ontology?focus=`, 프록시는 프록시 모달, 내러티브는 `/narrative?topic=` 딥링크(기존 패턴 재사용).
- 5-state (docs/policies/ui-states.md):
  - **Empty**: 판독 없음 → "가치·추세 렌즈로 이 종목을 읽어보세요" + '렌즈 생성' 버튼
  - **Loading**: Skeleton 2장
  - **Partial**: 한 렌즈만 있음(예: 재무 부족으로 가치 렌즈 partial) → 있는 것만 + 부족 사유
  - **Error**: ErrorState + 재시도
  - **Ideal**: 2장 + 4상한 + 근거 칩

## 구현 순서

1. **원칙 원장 로더 + `lens_readings` 테이블** — vault/principles 읽기·hash, DB
2. **가치 렌즈** (KR) — `gather_material`(brief·upside·CF 질·Fwd PER) → sonnet 판독 → 저장. `/analyze` 렌즈 탭에 카드 1장
3. **매물대 계산** + **추세 렌즈** (KR) — technicals·regime·매물대 → 판독. 카드 2장
4. **4상한 미니뷰 + 불일치 배지** — quadrant(), 근거 칩 딥링크
5. (별도 스펙) **`/us/:ticker` 도시에** 완성 후 렌즈를 US로 확장 — 추세는 yfinance 주가로 완전 작동, 가치는 US 재무 확보만큼 partial→full

## Out of Scope (이번 착수)

- **`/us/:ticker` 미국 종목 도시에** — 별도 스펙(docs/specs/us-dossier.md). 렌즈는 KR에 먼저 서고, US 데이터(yfinance 주가/밸류·US 여론 소스) 확보 후 확장.
- 원칙 원장 UI 편집기·버전관리 — 1차는 파일 직접 편집
- 렌즈 판독의 cron 자동 갱신 — 1차는 사용자 진입 시 lazy 생성(브리프·시나리오 패턴)
- 세 번째 이상의 렌즈(배당·매크로 등) — 두 대표 관점 먼저

## 참조
- 원칙 원장: `vault/principles/value.md`·`trend.md`
- 재사용: docs/specs/report-v2-agents.md(브리프·애널리스트 렌즈)·upside_model(D-035)·technicals·market_regime(D-076)
- 인식론 정박: docs/PHILOSOPHY.md §2·§3 · knowledge_state 4상한(D-079) · 렌즈=프레임(D-030)
