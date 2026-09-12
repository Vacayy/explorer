# 매크로·유동성 트래킹

홈의 배경 조건 트래킹 카드. 시장 국면(D-076, "오늘 얼마나 실을까" 포스처)과 **역할 분리** — 이건 "판이 어떻게 깔렸나"(금리·달러·유동성·신용·원자재).

## 데이터 (하이브리드)
- **매크로 (키 없음, yfinance)**: 미 10Y 금리(^TNX)·달러원(KRW=X)·달러 DXY(DX-Y.NYB)·유가 WTI(CL=F)·금(GC=F)·신용 HYG·비트코인(BTC-USD).
- **미 2Y 금리 (키 없음)**: [FRED DGS2](https://fred.stlouisfed.org/series/DGS2)의 공개 CSV. 결측 관측은 건너뛰고 원래 % 단위와 관측일을 보존한다. 달러원은 [Yahoo Finance KRW=X](https://finance.yahoo.com/quote/KRW%3DX/)를 사용한다.
- **유동성 (FRED 무료키 `FRED_API_KEY`)**: Fed 대차대조표(WALCL)·TGA(WTREGEN)·역레포(RRPONTSYD)·M2(M2SL).
  - **순유동성 = WALCL − TGA − RRP** (읽을 때 계산, 혼합 주기 forward-fill 정렬). = **MacroMicro US Liquidity Index**의 공식(유료 사이트 스크래핑 대신 동일 공식을 무료 FRED 원데이터로 재현). 위험자산과 가장 잘 붙는 유동성 지표.
  - 단위 정규화: WALCL·WTREGEN 백만$→십억$, 표시는 조($T).
- FRED 키 없으면 유동성 축만 `degraded`(매크로는 정상 동작). `fred_enabled` 플래그로 FE가 안내.

## 저장 (인프라 재사용)
`market_indicators` 테이블(시장 국면과 공용, D-076)에 **`macro_*` 프리픽스**로 적재(네임스페이스 분리, 스키마 추가 0). 원지표만 저장, 파생(순유동성·변화율)은 읽을 때 계산.

## 백엔드 (`pipeline/macro.py`)
- `snapshot_macro()`: yfinance + 공개 FRED DGS2 + 인증 FRED(키가 있으면) fetch → 멱등 적재. 각 소스 실패 개별 흡수(degraded).
- `get_macro()`: `macro_*` 순수 읽기 → 그룹별 지표(값·변화율·스파크라인 40·개별 마지막 관측일 `as_of`·날짜/값 쌍 `dated_series`) + 순유동성 파생. LLM 0·네트워크 0.
- `_interpret()`: **결정적 프레임(LLM 0 · 폴백/LLM 입력)** — 순유동성 방향 + 금리·달러 + 신용 점수 합 → 우호/혼조/역풍 + 근거 한 줄.
- **신호등 산문 해설(D-102, sonnet · 스냅샷 때 생성·캐시)**: `_refresh_signal`이 지표 + 결정적 초안을 sonnet에 줘 **신호등**(`green` 실어도 되는 배경 / `yellow` 선별·경계 / `red` 방어) + headline + comment(①왜 이 신호 ②포지셔닝 함의 ③주시할 지표·트리거) 생성. `macro_signals` 테이블(as_of PK, signature 불변이면 재사용). 단순 서술이 아니라 **투자자에게 신호등 역할**. 엔진 미가용이면 결정적 프레임 폴백.

## API (`/api/spine/macro`)
- `GET` — 지표 그룹 + 스파크라인. 첫 진입 시 lazy 스냅샷 1회(시장 국면 패턴).
- `POST /snapshot` — 재수집 적재(수동 버튼·선택 크론).

## 프론트 (`MarketContext` → `MacroLiquidity`)

Home 시장 모드 상단의 비고정 요약 띠에서 VIX·공포탐욕과 주요 매크로 6종(미 2Y/10Y·달러원·WTI·금·비트코인)을 개별 관측일과 함께 표시한다. 기본 접힘, 상세 펼침 시 기존 두 카드를 표시하고 설정을 기억한다. 피드 모드에는 표시하지 않는다. 요약은 기존 GET 쿼리를 공유하며 실시간 시세로 표기하지 않는다. 기존 API의 최초 빈 저장소 lazy 스냅샷 정책은 유지한다.
상단 **신호등 해설**(green/yellow/red 점 + headline + 산문 comment, LLM 미가용이면 결정적 배경 배지로 폴백) + 4그룹 타일(금리·달러 / 유동성 / 신용·위험선호 / 원자재), 각 지표: 라벨·미니 라인 스파크(min/max 기준)·값·변화율. **버튼 주도 갱신**(D-100 계승, `RefreshButton` → `POST /snapshot`). 유동성 그룹이 비고 FRED 미설정이면 키 안내.

## 설정 (사용자)
유동성 지표는 **FRED 무료 키** 필요: https://fred.stlouisfed.org/docs/api/api_key.html 발급 → `.env`에 `FRED_API_KEY=...` → 버튼으로 스냅샷. 없어도 yfinance 7종과 공개 FRED 미 2Y는 키 없이 수집할 수 있다.

## 5-state
Loading(skeleton) / Error(ErrorState+재시도) / Partial(일부 지표 degraded — 유동성 키 안내) / Empty(전 지표 없음) / Ideal(4그룹 타일).
