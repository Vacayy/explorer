# 포트폴리오 — 거래 원장과 비율 전용 화면

상태: P0 설계 확정(2026-10-08, D-212). 묶음 객체·일일 조건 평가는 [종목 묶음과 기술적 감시](portfolio-watch.md)(D-185)를 그대로 쓰고, 이 문서는 그 위의 **거래 원장·수익률·전용 메뉴** 계약만 다룬다.

## 목표

내 계좌의 현황(비중·종목별 수익률·계좌 수익률 추이)을 매일 확인하고, 보유 종목마다 기술적 분석·공시·뉴스를 한 화면에서 본다. 매수·매도·입금·출금은 금액으로 쉽게 입력한다.

## 프라이버시 계약 (최우선)

- 원화 금액(원금·매수/매도 금액·입출금·평가액·손익)은 **로컬 DB의 `portfolio_transactions.amount`에만** 저장한다. DB(`backend/db/`)는 git 제외.
- **어떤 GET 응답에도 원화 금액·수량을 싣지 않는다.** 응답은 비율(%)·가격(평단·종가)·날짜·종목만. 거래 내역 조회도 금액·수량 없이 날짜·유형·종목·체결가만.
- 화면은 금액을 표시하지 않는다. 입력 폼에서 사용자가 친 금액만 예외(전송 후 폼 초기화).
- 묶음 멤버(`stock_group_members`)에는 종목·편입일만 넣고 `quantity`·`avg_price`는 비워 둔다 — 기존 묶음 API가 `kind=portfolio`에서 원화 손익(`pnl`)을 계산하지 않게.
- AI(브리핑·CodeAct 스냅샷)는 이 원장을 읽지 않는다. 대화(웹·텔레그램)는 비율 전용 요약 도구 `chat_tools.get_portfolio`만 쓴다(D-228) — 비중·평단 대비 수익률·평단·현재가·현금 비중·실현/미실현(원금 대비 %)·청산 내역과 운용 원칙 원문. 원화 금액·수량은 없다.
- 저장소가 공개이므로 spec·코드·테스트·커밋에 실제 보유 금액을 쓰지 않는다(테스트는 가상 금액).

## 데이터

`stock_groups`에 `kind='portfolio'` 묶음 하나('내 포트폴리오')를 자동 생성해 쓴다.

```
portfolio_transactions(
  id INTEGER PK, group_id INTEGER → stock_groups,
  trade_date TEXT(YYYY-MM-DD), kind TEXT CHECK(kind IN ('buy','sell','deposit','withdraw')),
  stock_code TEXT NULL,        -- buy/sell만
  amount REAL > 0,             -- 원화. 매수·매도 금액 / 입출금액
  price REAL NULL,             -- buy/sell 체결가(미입력 시 그날 이전 마지막 종가)
  note TEXT, created_at TEXT)
```

원장 재생(날짜·id 순):
- 매수: 수량 += amount/price, 평단 = 이동평균, 현금 −= amount. 현금 부족 시 `fund_shortfall`(기본 켜짐)이면 부족분을 같은 날 입금 행으로 먼저 기록, 꺼져 있으면 거부.
- 매도: 수량 −= amount/price(보유 초과 거부), 평단 유지, 현금 += amount.
- 입금/출금: 현금 ±= amount(출금은 현금 초과 거부).

## 수익률

- 평가일: 첫 거래일 + 보유 종목들의 `stock_prices` 거래일(첫 거래일 이후). 각 날은 그날 이전 마지막 종가로 평가(16:10 일별 수집 전에는 직전 종가).
- 계좌 수익률은 **시간가중(TWR)**: 일간 r_t = V_t / (V_{t−1} + F_t) − 1, F_t = 그날 순입금. 누적 = Π(1+r_t) − 1. 입출금이 수익률을 왜곡하지 않는다.
- 종목 수익률 = 종가/평단 − 1. 비중 = 종목 평가액/총평가액(현금 포함).
- **장중 시세(2026-10-08, 2026-10-16 GET 분리)**: 조회 GET(`/api/portfolio`·`/history`와 summary를 쓰는 GET 전부)은 저장된 `portfolio_quotes`만 읽고 네트워크·쓰기를 하지 않는다. 갱신은 `POST /api/portfolio/quotes/refresh?force=false` — 평일 09:00–15:40 KST이고 보유 종목의 마지막 시세가 30분 넘었을 때만 네이버 실시간 시세(`pipeline/quotes.fetch_quotes`)로 `portfolio_quotes`(종목당 1행)를 갱신하고 `refreshed`로 실제 수집 여부를 알린다. 포트폴리오 화면이 진입 시·보이는 동안 30분마다 이 요청을 보내고, 받았을 때만 화면을 다시 계산한다(`useAutoRefreshPortfolioQuotes`). `pfintraday` 알림 작업도 따로 갱신한다. 시세 날짜가 저장 종가보다 새로울 때만 '오늘' 평가에 쓰고(전일비는 거래소 전일 종가 대비 등락률), 16:10 종가가 들어오면 종가가 이긴다. 화면은 장중 시세를 쓰는 동안 30분마다 다시 조회하며 종목별 시세 시각을 보인다(조회 실패 시 시각이 그대로 남아 오래된 시세임이 드러난다). 헤더 '시세 갱신' 버튼(`POST /api/portfolio/quotes/refresh`, 기본 force)은 30분 주기·장 시간과 무관하게 지금 다시 받는다(장 마감 뒤 16:35 일별 수집 전에도 오늘 KRX 종가를 바로 반영).

## 실현 손익 (2026-10-14, D-226)

매도는 평단을 유지하므로 매도 한 건의 실현 손익 = (매도가 − 그 시점 평단) × 매도 수량이다(`realized_trades`, 원장 재생 중 계산). 원화 합계는 내부 계산에만 쓰고 응답에는 비율만 싣는다.

- **요약**: `realized_pct` = 실현 손익 합 ÷ 원금(입금 − 출금) × 100, `unrealized_pct` = 보유 종목 (평가액 − 평단 × 수량) 합 ÷ 원금 × 100. 계좌 수익률(TWR)은 그대로 주 지표다 — 입출금이 중간에 있으면 두 값의 합과 TWR이 다를 수 있다(원금 대비 단순 비율이기 때문).
- **청산 내역**: 매도마다 종목·매수일(포지션 편입일)·매도일·보유 일수·평단·매도가·실현 수익률(매도가/평단 − 1)·전량/일부. 최근 매도부터.
- 화면: 요약 카드에 '실현 손익'·'미실현 손익' 두 칸, 보유 종목 아래 '청산 내역' 표(매도가 없으면 숨김).
- 수수료·거래세는 반영하지 않는다(범위 밖). 매도가는 사용자가 입력한 체결가.

## API (`routers/portfolio.py`, prefix `/api/portfolio`)

| | 응답(비율 전용) |
|---|---|
| `GET /` | as_of, total_return_pct(TWR), day_return_pct, cash_weight_pct, holdings[code·name·weight_pct·return_pct·day_change_pct·avg_price·last_close·entry_date], realized_pct·unrealized_pct(원금 대비), closed[code·name·entry_date·sell_date·holding_days·avg_price·sell_price·return_pct·full] |
| `GET /history` | points[date·cum_return_pct·day_return_pct] |
| `GET /transactions` | items[id·trade_date·kind·stock_code·name·price] (금액·수량 없음) |
| `POST /transactions` | body {trade_date, kind, stock_code?, amount?, price?, fund_shortfall?, sell_all?} → {ok, id}. `sell_all`(매도만)이면 금액 대신 그날까지의 보유 수량 × 체결가(비우면 그날 종가)를 서버가 계산 — 화면은 수량을 모른다(2026-10-15) |
| `DELETE /transactions/{id}` | 삭제 후 원장 재검증(음수 수량·현금이 되면 409로 거부) |

## 화면 (`/portfolio`, 도크 독립 메뉴 '포트폴리오')

1. 헤더: 제목, `거래 입력`(Dialog: 매수·매도·입금·출금, 종목 검색·날짜·금액·체결가 선택. 매수·매도는 '금액 / 수량 × 체결가' 입력 방식 선택 — 수량 방식은 체결가 필수, 계산 금액은 폼 안에서만 보임. 매도는 '전량' 체크 시 `sell_all`), `거래 내역`(Sheet: 금액 없는 목록, 삭제).
2. 요약: 계좌 수익률·오늘·현금 비중 → 비중 파이차트 + 보유 표(비중·평단·현재가·수익률·전일비) → 일별 누적 수익률 차트.
3. 종목 탭(URL `?stock=`): 가격 차트(평단 점선, 편입일 마커)에 기업 화면과 같은 기술적 분석(`TechnicalScan`: 신호 마커·구조선·핵심 관측·구조 그리기)을 기본으로 붙인다(`scan=0`이면 닫힘, `scan_within`·`scan_chart`는 기업 화면과 같은 URL 키) · 최근 공시 5 · 뉴스·관련 자료 5(누르면 `/doc/:id`, 뒤로가기 복귀).

5-state: Empty(거래 없음 → 입금/매수 안내) · Loading(Skeleton) · Partial(종가 미수집 종목은 '-'·평가 제외 표시) · Error(재시도) · Ideal.

## 알림 (D-214)

텔레그램 봇으로 먼저 보낸다(화면 불필요). 모두 비율·가격만.

| 알림 | 시점 | 조건 |
|---|---|---|
| 장중 급등락 | 평일 09:00–15:40, 30분(`pfintraday`) | 전일 대비 ±5%p 구간, 평단 대비 ±10%p 구간에 처음 들어설 때(같은 구간 재발송 없음) |
| 신규 공시 | 평일 09:00–18:00, 30분 | 보유 종목의 오늘 DART 공시(접수번호당 1회) |
| 주요 기술적 신호 | 평일 16:50(`pfclose`) | 오늘 새로 충족한 특이점(기업 화면 '주요 신호' 기준) |
| 일일 계좌 요약 | 평일 16:50 | 계좌·오늘 수익률, 종목별 전일비·평단 대비·비중 |

`--dry-run`은 보내지 않고 기록도 하지 않는다. 발송 실패는 다음 점검에서 재시도, 작업 실패는 `job_runs`.

## 범위 밖 (P1+)

배당·수수료·세금(실현 손익은 세전·수수료 전), 해외 주식, 벤치마크(코스피) 대비, 브리핑·텔레그램 한 줄, AI 비율 요약 도구.
