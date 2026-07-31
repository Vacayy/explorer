# US 거래대금 상위 — 홈 리스트업

전일 미국시장 **거래대금(=종가×거래량, USD dollar volume)** 상위 20 종목을 홈에 리스트업. "주목 주제/종목"과 같은 신호 카드 결.

## 데이터 소스 (무키)
- **TradingView 스크리너** `POST https://scanner.tradingview.com/america/scan` — API 키 불필요.
  - body: `columns=[name,description,close,volume,Value.Traded,exchange,type]`, `sort=Value.Traded desc`, `range=[0,60]`.
  - **전 미국 거래소 통합**(NYSE·Nasdaq·AMEX·CBOE…) — 거래소 필터 없음.
  - **ADR 포함**: `type='dr'`(SKHY·TSM 등)를 남긴다. **ETF 제외**: `type='fund'`(SPY·QQQ·SOXX…) 필터링 후 상위 20.
- 비공식 엔드포인트 → 스키마가 바뀔 수 있음. `pipeline/us_movers.py`가 응답 구조(컬럼 수·타입)를 검증하고 어긋나면 `MoversSchemaError`.

## 백엔드
- 테이블 `us_movers`(rank PK 1..N, ticker·name·close·volume·dollar_volume·exchange·is_adr·fetched_at) — 매 갱신 전량 교체.
- 캐시 게이트 `cache_meta('us_movers_dollar_vol')`, TTL 1h(EOD 후 정착, 장중이면 최신 세션 누적).
- `pipeline/us_movers.get_leaders(force)` → `{status, items, source, fetched_at, error}`.
- `GET /api/spine/us/movers` (라우터에서 `/{ticker}`보다 **먼저** 선언 — catch-all 회피).

## 프론트 (홈 신호 대시보드 스택, `UsMoversSection`)
카드: rank · ticker(→`/us/:ticker`) · 회사명 · ADR 배지 · 거래대금(`formatUsd` → `$62.5B`). 헤더에 `FreshnessStamp` + `/us` 링크.

## 상태 계약 (5-state)
| status | 의미 | FE 렌더 |
|---|---|---|
| `ok` | 신선/막 갱신 | Ideal — 리스트 |
| `stale` | **갱신 실패**(스키마 변경·네트워크) → 마지막 성공 스냅샷 | Partial — 리스트 + **경고 배너**(`chart-warning`, error 사유 표기) |
| `error` | 데이터 없음(첫 fetch 실패) | Error — `ErrorState` + 재시도 |
| items=0 & ok | (이론상) 빈 결과 | Empty — `EmptyState` |
| 로딩 | 쿼리 진행 | Loading — `Skeleton` |

→ 소스 스키마가 깨져도 화면은 마지막 정상 데이터를 유지하면서 사용자에게 경고를 노출(조용한 실패 금지).
