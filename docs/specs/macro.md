# 매크로·유동성 트래킹

홈의 배경 조건 트래킹 카드. 시장 국면(D-076, "오늘 얼마나 실을까" 포스처)과 **역할 분리** — 이건 "판이 어떻게 깔렸나"(금리·달러·유동성·신용·원자재).

## 데이터 (하이브리드)
- **매크로 (키 없음, yfinance)**: 미 10Y 금리(^TNX)·달러 DXY(DX-Y.NYB)·유가 WTI(CL=F)·금(GC=F)·신용 HYG·비트코인(BTC-USD).
- **유동성 (FRED 무료키 `FRED_API_KEY`)**: Fed 대차대조표(WALCL)·TGA(WTREGEN)·역레포(RRPONTSYD)·M2(M2SL).
  - **순유동성 = WALCL − TGA − RRP** (읽을 때 계산, 혼합 주기 forward-fill 정렬). = **MacroMicro US Liquidity Index**의 공식(유료 사이트 스크래핑 대신 동일 공식을 무료 FRED 원데이터로 재현). 위험자산과 가장 잘 붙는 유동성 지표.
  - 단위 정규화: WALCL·WTREGEN 백만$→십억$, 표시는 조($T).
- FRED 키 없으면 유동성 축만 `degraded`(매크로는 정상 동작). `fred_enabled` 플래그로 FE가 안내.

## 저장 (인프라 재사용)
`market_indicators` 테이블(시장 국면과 공용, D-076)에 **`macro_*` 프리픽스**로 적재(네임스페이스 분리, 스키마 추가 0). 원지표만 저장, 파생(순유동성·변화율)은 읽을 때 계산.

## 백엔드 (`pipeline/macro.py`)
- `snapshot_macro()`: yfinance + FRED(있으면) fetch → 멱등 적재. 각 소스 실패 개별 흡수(degraded).
- `get_macro()`: `macro_*` 순수 읽기 → 그룹별 지표(값·변화율·스파크라인 40) + 순유동성 파생. LLM 0·네트워크 0.
- `_interpret()`: **해석 코멘트(결정적 frame · LLM 0 · 정답 아님, 지표=fact/해석=frame 계승 D-076)** — 순유동성 방향(위험자산 최밀착) + 금리·달러(완화/긴축) + 신용(HYG) 점수 합 → 위험자산 배경 **우호/혼조/역풍** + 근거 한 줄. 예: "순유동성 위축(−1.5%)·금리·달러 동반 하락(완화적) → 배경 혼조".

## API (`/api/spine/macro`)
- `GET` — 지표 그룹 + 스파크라인. 첫 진입 시 lazy 스냅샷 1회(시장 국면 패턴).
- `POST /snapshot` — 재수집 적재(수동 버튼·선택 크론).

## 프론트 (`MacroLiquidity`, 홈 시장 국면 아래)
상단 **해석 코멘트**(배경 우호/혼조/역풍 배지 + 근거) + 4그룹 타일(금리·달러 / 유동성 / 신용·위험선호 / 원자재), 각 지표: 라벨·미니 라인 스파크(min/max 기준)·값·변화율. **버튼 주도 갱신**(D-100 계승, `RefreshButton` → `POST /snapshot`). 유동성 그룹이 비고 FRED 미설정이면 키 안내.

## 설정 (사용자)
유동성 지표는 **FRED 무료 키** 필요: https://fred.stlouisfed.org/docs/api/api_key.html 발급 → `.env`에 `FRED_API_KEY=...` → 버튼으로 스냅샷. 없어도 매크로 6종은 정상.

## 5-state
Loading(skeleton) / Error(ErrorState+재시도) / Partial(일부 지표 degraded — 유동성 키 안내) / Empty(전 지표 없음) / Ideal(4그룹 타일).
