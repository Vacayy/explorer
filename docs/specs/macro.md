# 매크로·유동성 트래킹

홈의 배경 조건 트래킹 카드. 시장 국면(D-076, "오늘 얼마나 실을까" 포스처)과 **역할 분리** — 이건 "판이 어떻게 깔렸나"(금리·달러·유동성·신용·원자재).

## 데이터 (하이브리드)
- **매크로 (키 없음, yfinance)**: 달러원(KRW=X)·엔원(JPYKRW=X, 100엔당 표시)·달러 DXY(DX-Y.NYB)·유가 WTI(CL=F)·금(GC=F)·신용 HYG·비트코인(BTC-USD).
- **미 2Y·10Y 금리 (키 없음)**: [FRED DGS2](https://fred.stlouisfed.org/series/DGS2)·[DGS10](https://fred.stlouisfed.org/series/DGS10)의 공개 CSV. 정본 계열 `risk_us2y`·`risk_us10y`(`pipeline/indicator_canon.py`)를 읽고 스냅샷은 Risk 수집기에 위임한다(2026-10-16, 이전의 ^TNX `macro_us10y`는 수집 중단). 결측 관측은 건너뛰고 원래 % 단위와 관측일을 보존한다. 달러원은 [Yahoo Finance KRW=X](https://finance.yahoo.com/quote/KRW%3DX/)를 사용한다.
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

## Risk 차트 분리 (D-205, 2026-09-28)

Home 기본 금리·신용·VIX·공포탐욕 표시는 [Risk 계약](home-feed.md#risk-모니터링-구현-계약-2026-09-28)을 따른다. 기존 MacroLiquidity 상세와 매크로 해설 입력은 유지한다. Risk·매크로·요약 띠 모두 10Y/2Y를 같은 FRED DGS10/DGS2 정본에서 읽는다(2026-10-16). 상단 MarketContext 요약 띠는 달러원·엔원·미국 2Y·10Y·WTI·금·BTC와 MoM을 표시한다(D-210).

Risk 금리·신용은 기본 10년이며 `risk_macro_range`에서 3개월~전체로 전환한다. FRED 장기 백필은 기존 market_indicators에 보존하고 최초 백필 이후 최근 400일만 갱신한다. HY/BBB/AAA OAS의 최근 3년 제공 제한과 Aaa/Baa−10Y의 정의 차이는 카드·설명 팝오버에서 안내한다.

## 공개 저장 수치 준비

공개 `/api/spine/macro/public`은 기존 numeric_macro 계산을 재사용하되 readonly snapshot의 고정 지표만 읽는다. 기존 GET의 빈자료 lazy snapshot과 별도이며 수집·쓰기·signal/era 체크/개인 pricing·provider를 호출하지 않는다. 관측 열은 market_indicators의 indicator/snapshot_date/value만 허용하며 meta/schema와 source_receipts는 출처 검증에만 읽는다. 응답에 key/label/value/단위/관측일/최대40개 시계열·5관측 전 비교일·원출처/계열 URL/원천 관측일을 담는다. 5관측은 5거래일을 뜻하지 않는다. NULL·비유한·비수치 저장값이 있는 계열은 invalid로 제외하고 결측/공개원천 검토중과 구분한다. 환경변수·API키 설정 상태 및 미승인 산문은 노출하지 않는다.

공개 자료는 기존 FRED 취득 DB를 재표기하지 않고 Board H.15/H.4.1/H.6 및 NYFed에서 직접 취득한다. 원자료의 공개 여부와 취득 서비스의 이용 조건을 구분한다. [FRED 조건](https://fred.stlouisfed.org/legal/terms/) 때문에 원출처의 Public Domain 태그만으로 기존 FRED API·CSV 저장본의 공개를 승인하지 않았다. [Board](https://www.federalreserve.gov/disclaimer.htm)·[NYFed](https://www.newyorkfed.org/privacy/termsofuse)의 직접 자료에 출처와 필요한 귀속을 붙이고, Yahoo 계열은 source_review_pending으로 제외한다. 순유동성의 누락 입력을0으로 대체하지 않는다.

공개 UI의 수치 연결 준비는 매크로 전체완료가 아니다. 국면/리스크/사용자 정성체크/승인해설과 모든 원천 연결이 남는다. 운영 수집기/기존 개인 모드는 유지하며 이번 구현으로 실제 공개·원자료 삭제·운영출처전환을 수행하지 않는다.

### 직접 원천 저장본

공개 reader는 `EXPLORER_PUBLIC_MACRO_DB`로 명시한 별도 SQLite만 읽으며 운영 DB를 fallback으로 읽지 않는다. schema marker `public_macro_direct_v1` 및 각 계열 source_receipts의 원천 URL·series_id·SHA256를 검증한다. 스냅샷이 미설정이면503이며 합성 테스트에서도 임시 별도 DB를 명시한다. 직접취득은 Board의 H15/H41/H6 ZIP XML에서 RIFLGFCY02_N.B/RIFLGFCY10_N.B, RESPPMA_N.WW/RESPPLLDT_XAW_N.WW, M2.M만 선택한다. NYFed reverse repo API에서 Overnight/Treasury 거래의 accepted USD금액을 날짜별 합산해십억USD로 정규화한다. 초기 운영 검증의 원자료 다운로드는 bounded size·타임아웃·고정URL로 수행했다. importer 자체는 네트워크를 호출하지 않으며 ZIP을 디스크에 풀지 않고 streaming XML로 필요한 관측만 추출한다. 최신400관측/계열의 작은 독립 저장본만 유지한다. 기존 원본을 덮어쓰거나 FRED저장행의 라벨을 바꾸지 않는다.

공개 순유동성은 기존WALCL−TGA−RRP 계산을 재사용한다. WALCL수요일잔액과TGA주평균·RRP일별은 혼합주기이며 날짜사이직전값유지를 명시한다. 원입력별마지막관측일/5관측비교일·기간을표시한다. 이 파생값은 Explorer 참고계산이며 원기관공식지표나보증이아니다. NYFed 원출처링크·저작권/조건귀속을화면에보존한다. 별도 정기갱신·운영배포연결은 아직 수행하지 않는다.


`pipeline.public_macro_import`는 고정 계열과 단위·주기 속성을 검증하고 기존 파일을 덮어쓰지 않는 원자적 새 파일 발행을 제공한다. fed_bs/tga는 백만USD 원단위를 보존하며 기존 계산기가 십억USD로 변환한다. RRP만 USD→십억USD를 import에서 적용한다. 실패 시 기존 정상 저장본은 그대로이며 reader는 한 요청의 단일 readonly 트랜잭션을 사용한다. 자동 다운로드·정기갱신·활성 경로 교체는 아직 연결되지 않았다.
