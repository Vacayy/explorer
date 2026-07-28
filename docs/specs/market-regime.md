# 시장 국면 — 홈 리스크 포스처 섹션

> 2026-07-28 기획 (D-076). 배경: 앱은 전부 bottom-up(엔티티·내러티브) 축이고, **포트폴리오 리스크 포스처(매크로 층)가 통째로 비어 있다**.
> "매일 아침 여는 터미널"인데 정작 "오늘 얼마나 실어도 되나"를 말해주는 게 없음.
> 착안: 태린이 아빠 유튜브의 리스크 레짐 규율 — 3중 필터(감성 오실레이터 × 추세 게이트 × 변동성)를 하나의 비중 포스처로 결합.
> 사용자 3문항 확인(2026-07-28): 배치=미니 추이 차트 품은 홈 섹션 / 범위=둘 다(미국=날씨·국장=본판) / 오피니언=결합 포스처+근거(지표=fact, 규율=frame).
> **정정(2026-07-28)**: "20 EMA"는 **오실레이터 자체의 20일 EMA**(가격 EMA 아님). 태린이 아빠 규율의 핵심 = 오실레이터가 바닥에서 반등해도 그 EMA가 우하향이면 대기. US=F&G+F&G의 EMA, KR=RSI14+RSI14의 EMA. S&P·KOSPI 가격 EMA는 게이트에서 배제(KOSPI는 RSI 계산 입력으로만).

## 관통 원칙

1. **지표 = fact, 포스처 = frame** — F&G·VIX·VKOSPI·EMA 값은 관측된 **사실**(hypothesis 주황 아님). "우하향이면 비중 보류"라는 결합 규율은 검증된 지식이 아니라 **하나의 프레임**(PHILOSOPHY §2 "사실은 그래프로, 프레임은 렌즈로"). 단, UI에 "태린이 아빠식" 같은 귀속 배지는 넣지 않는다(사용자 요청) — 규율은 포스처 서술 자체로 드러나되 "정답"으로 단언하지 않는다.
2. **LLM 0 (결정적)** — 포스처 결합·근거 한 줄은 전부 규칙 기반 템플릿. 신호 모듈(`signals.py`)·기술 위치(`technicals.py`)와 같은 "감지 LLM 0" 철학. 매일 돌아도 비용 0 (외부 지수 fetch만). cost-conscious-design 정합.
3. **홈=delta와의 타협 = delta-aware** — 홈은 원래 "변화의 스트림"(§6). 상시 게이지를 박는 건 규율 위반이라, **현재 상태를 압축해 보여주되 레짐 *전환*을 강조**한다(과매도 진입·EMA 롤오버·VIX 스파이크 = delta). 전체 히스토리 대시보드가 필요해지면 그때 디테일 페이지로 분리(현재 범위 아님).
4. **미국=날씨, 국장=본판** — 미국(F&G 오실레이터·VIX)은 글로벌 리스크 날씨, 국장(RSI14 오실레이터·VKOSPI/변동성)은 매매 결정 본판. 각 시장의 추세 게이트 = 그 오실레이터의 20 EMA 기울기. 커버리지가 국장이라 포스처의 무게중심은 국장.

## 데이터 소스 (feasibility 실측 완료 2026-07-28)

| 지표 | 소스 | 판정 |
|---|---|---|
| VIX | yfinance `^VIX` | ✅ 확인(18.9) |
| KOSPI (RSI14 입력) | yfinance `^KS11` | ✅ 확인 — 마지막 봉 NaN 가능 → `dropna()`. RSI14→그 20 EMA 계산 입력(지수 자체 EMA는 게이트 아님) |
| US Fear & Greed | CNN `production.dataviz.cnn.io/index/fearandgreed/graphdata` | ✅ 확인 — **브라우저 UA 헤더 필수**(무헤더=418 봇차단). score+rating+히스토리 배열 반환. 비공식 API라 실패 시 graceful degrade |
| VKOSPI | naver 차트 API (`api.stock.naver.com/chart/domestic/index/...`) | 🟡 엔드포인트 살아있음(200), 정확한 심볼은 구현 시 확정. **폴백=KOSPI 20일 실현변동성**(^KS11 로그수익률 std×√252, 항상 가능) |

- pykrx는 이 프로젝트에서 KRX 연결문제로 비활성(`industries.py` 주석) → VKOSPI를 pykrx에 의존하지 않는다.
- 모든 외부 호출은 캐시(§저장). CNN·yfinance 실패는 부분 표시(Partial state)로 흡수 — 전체 실패만 Error.

## 저장 구조 — 일별 스냅샷 (축적 = 해자)

새 테이블 `market_indicators` (database.py init_db):

| 컬럼 | 설명 |
|---|---|
| `snapshot_date` TEXT | KST 날짜 (YYYY-MM-DD) |
| `indicator` TEXT | `fear_greed`·`vix`·`kospi`·`vkospi`·`kospi_vol`. **원지표만 저장** — 파생(RSI14·오실레이터 20EMA·기울기)은 읽을 때 계산 |
| `value` REAL | 값 |
| `extra_json` TEXT | rating·slope·percentile 등 부수 (nullable) |
| PK | (snapshot_date, indicator) |

- **왜 테이블**: 스파크라인이 ~20–60일 히스토리를 요구 → 스냅샷을 쌓으면 추이 차트가 공짜. append-only 시계열(§5 축적). 첫 실행 시 F&G(CNN 히스토리)·VIX/KOSPI(yfinance history)로 백필.
- **갱신**: EOD 1회 배치(장 마감 후). 기존 `ingest_prices`(평일 16:10)에 편승하거나 별도 `snapshot_market` cron. 장중 실시간 아님(리스크 포스처는 일 단위 규율이라 EOD 충분).

## 포스처 결합 규칙 (LLM 0 · 초기 임계값은 튜닝 대상)

시장별로 3필터 → 포스처:

**① 감성 오실레이터**
- 미국: F&G score. extreme fear <25 · fear 25–45 · neutral 45–55 · greed 55–75 · extreme greed >75. **과매도 = F&G < 25**.
- 국장: 직접 F&G 없음 → KOSPI RSI14 or VKOSPI 백분위. **과매도 = RSI14 < 30** (또는 VKOSPI 상위 10%).

**② 추세 게이트** (핵심 — 태린이 아빠 규율) = **오실레이터의 20일 EMA 기울기** (가격 EMA 아님)
- US: F&G의 20 EMA · KR: RSI14의 20 EMA. 최근 5거래일 기울기 → `up` / `flat` / `down`.
- flat 판정: 0~100 스케일이라 절대 포인트 |Δ5일| < 1.0 (튜닝). 오실레이터가 바닥서 반등해도 EMA 우하향이면 `down` → 보류.

**③ 변동성** (사이징)
- VIX: calm <20 · elevated 20–30 · stress >30. 국장: VKOSPI(or 실현변동성) 유사 밴드.

**포스처 매트릭스** (시장별):

| 오실레이터 | 추세 | 포스처 | 근거 템플릿 |
|---|---|---|---|
| 과매도 | up/flat | 🟢 비중 확대 구간 | "공포 + 추세 지지 → 분할 매수 유효" |
| 과매도 | **down** | 🟡 보류 | "과매도지만 오실레이터 20EMA 우하향 → 반등은 속임수 경계, EMA 눕기 대기" |
| 중립 | — | ⚪ 중립 | "뚜렷한 엣지 없음" |
| 탐욕 | up | 🟡 과열 경계 | "추세는 살아있으나 탐욕권 → 신규 비중 자제" |
| 탐욕 | down | 🔴 축소 | "탐욕 + 추세 이탈 → 비중 축소" |

- **변동성 오버레이**: stress면 어느 포스처든 "사이징 축소" 경고 배지 추가.
- **BLUF 한 줄**: 국장 포스처를 헤드라인으로, 미국은 "날씨" 맥락으로 병기. 전부 결정적 문자열 조합.

## API

`GET /api/spine/market-regime` (spine 라우터) →
```
{ as_of,
  kr: { posture, posture_color, reason, oscillator:{metric,value,zone},
        trend:{ema20,slope,dir}, volatility:{value,band}, series:{kospi:[],ema20:[],vol:[]} },
  us: { posture, posture_color, reason, fear_greed:{score,rating}, vix:{value,band},
        series:{fear_greed:[],vix:[]} },
  degraded: [ ...실패한 지표 ] }
```
- 읽기는 `market_indicators`에서 latest + trailing N일(스파크라인). LLM 0. staleTime 짧게(EOD 갱신).

## IA / 화면 — 홈 섹션 (신규 페이지 없음)

`HomePage.tsx`에 `<MarketRegime />` 섹션 추가. 위치: 내러티브/리포트 델타 카드 위(리스크 포스처가 그날의 렌즈라 먼저) 또는 아래 — 구현 시 시각 균형 보고 결정.

```
┌─ 시장 국면 ───────────────────────────── as of 07/28 ─┐
│  🟡 과매도지만 오실레이터 20EMA 우하향 → 비중 확대 보류  │  ← BLUF(국장 포스처)
│     반등은 속임수 경계 · [사이징 축소: VIX 28]          │  ← 변동성 오버레이
│                                                          │
│  🌎 미국(날씨)              🇰🇷 국장(본판)              │
│  F&G 40 + 20EMA ╱‾╲_        RSI14 32 + 20EMA ╲__       │  ← 오실레이터+그 EMA 오버레이
│  VIX 28 경계  ▂▃▅▄▆         실현변동성 24  ▁▂▄▃▂       │  ← 변동성 스파크라인
└──────────────────────────────────────────────────────────┘
(오실레이터 실선 + 그 20EMA 파선 겹침 — EMA 기울기가 추세 게이트)
```
- 미니 차트: Recharts 스파크라인. 각 시장 primary = **오실레이터 실선 vs 그 20EMA 파선** 오버레이(기울기=게이트 시각화). hover 시 그 시점 값·날짜로 전환.
- 컴포넌트 계층: `components/home/MarketRegime.tsx` + `hooks/useMarketRegime.ts` + type in `types/index.ts`.
- 숫자 포맷: `utils/format.ts`. 색: `--color-up/down` 등 CSS 변수(하드코딩 금지). 포스처 색은 semantic 토큰.

## 5-state (docs/policies/ui-states.md)

| 상태 | 처리 |
|---|---|
| Empty | 첫 스냅샷 전 — "시장 데이터 수집 대기" 안내 |
| Loading | Skeleton (섹션 높이 고정) |
| **Partial** | 일부 지표 실패(F&G 차단·VKOSPI 미해결) → 얻은 것만 표시 + `degraded` 배지("일부 지표 미수집"). 핵심(KOSPI 추세)만 있어도 국장 포스처는 계산 |
| Error | 전체 fetch 실패 → ErrorState + retry |
| Ideal | 양 시장 포스처 + 미니 추이 + BLUF |

+ FreshnessStamp(스냅샷 시각).

## 경계 (안 하는 것)

- **장중 실시간 틱 금지** — EOD 일 단위. 리스크 포스처는 일 규율.
- **자동 매매·비중 숫자 지시 금지** — 포스처는 "구간" 서술(🟢/🟡/🔴)이지 "몇 % 사라"가 아니다. §3 거짓 정밀·오라클 회피. %는 안 쓴다.
- **포스처를 hypothesis 엣지/지식으로 승격 금지** — 그래프에 안 넣는다. 이건 매크로 상태 readout이지 인과 주장이 아님.
- **개별 종목 타이밍 신호 금지** — 시장 레벨만. 종목 기술 위치는 기존 `technicals.py`.
- **F&G 컴포넌트 자체 재계산 금지** — CNN 값 그대로(신뢰 소스). 차단 시 숨김(자체 근사 안 만듦 — 거짓 정밀).
```
