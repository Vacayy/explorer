# Stock Explorer - 설계 및 구현 현황

## 기술 스택

| 레이어 | 기술 | 버전 |
|--------|------|------|
| Backend | Python, FastAPI | 3.12, 0.136 |
| Database | SQLite (WAL mode) | built-in |
| DART API | OpenDartReader | 0.2.2 |
| KRX 데이터 | pykrx | 1.2.8 |
| Frontend | React, TypeScript, Vite | 19.x, 5.x, 8.x |
| 차트 | Recharts | 2.x |
| 서버 상태 | TanStack Query | 5.x |
| HTTP | Axios | 1.x |

---

## 디렉토리 구조

```
stock-explorer/
├── .env                          # DART_API_KEY (gitignored)
├── .gitignore
├── PLAN.md                       # 기획서
├── ARCHITECTURE.md               # 본 문서
│
├── backend/
│   ├── main.py                   # FastAPI 앱, CORS, 라우터 등록
│   ├── config.py                 # 환경변수, DB 경로, 캐시 TTL 상수
│   ├── database.py               # SQLite 연결, 8개 테이블 DDL
│   │
│   ├── models/                   # Pydantic 스키마 (요청/응답)
│   │   ├── company.py            # CompanyResponse
│   │   ├── financial.py          # FinancialRow, FinancialResponse
│   │   ├── disclosure.py         # DisclosureItem, DisclosureResponse
│   │   ├── ir_note.py            # IRNoteCreate/Update/Response
│   │   └── stock_price.py        # StockPriceItem, ValuationItem/Response
│   │
│   ├── routers/                  # API 엔드포인트
│   │   ├── companies.py          # 기업 검색/조회
│   │   ├── financials.py         # 재무제표 조회
│   │   ├── disclosures.py        # 공시 목록 조회
│   │   ├── ir_notes.py           # IR 메모 CRUD
│   │   ├── stock_prices.py       # 주가/시총/밸류에이션
│   │   └── business.py           # 사업부문 CRUD
│   │
│   ├── services/                 # 비즈니스 로직
│   │   ├── dart_service.py       # DART API 래핑 + 캐싱 + 분기 계산
│   │   ├── krx_service.py        # pykrx 래핑 + 캐싱 + PBR밴드 계산
│   │   └── cache_service.py      # cache_meta 테이블 CRUD
│   │
│   └── db/
│       └── stock_explorer.db     # SQLite 파일 (gitignored)
│
├── frontend/
│   └── src/
│       ├── main.tsx              # React 엔트리
│       ├── App.tsx               # QueryClient, 라우팅, 탭 전환
│       ├── index.css             # 글로벌 스타일 (Light mode)
│       │
│       ├── api/
│       │   └── client.ts         # Axios 인스턴스
│       │
│       ├── types/
│       │   └── index.ts          # TypeScript 인터페이스 전체 정의
│       │
│       ├── utils/
│       │   └── format.ts         # formatKrw, formatDartAmount, formatPercent
│       │
│       ├── hooks/                # TanStack Query 커스텀 훅
│       │   ├── useCompanySearch.ts
│       │   ├── useFinancials.ts
│       │   ├── useStockPrices.ts   # useStockPrices + useValuation
│       │   ├── useDisclosures.ts
│       │   ├── useIRNotes.ts       # CRUD mutations 포함
│       │   └── useBusiness.ts      # CRUD mutations 포함
│       │
│       └── components/
│           ├── layout/
│           │   ├── Header.tsx          # 기업 검색 autocomplete
│           │   └── TabNavigation.tsx   # 7개 탭 네비게이션
│           │
│           ├── common/
│           │   ├── ChartCard.tsx       # 차트 래핑 카드
│           │   └── PeriodToggle.tsx    # 분기/연도/4Q누적 토글
│           │
│           ├── summary/
│           │   └── SummaryPage.tsx     # 실적 테이블+차트, 시총 미니차트, 최근 공시
│           │
│           ├── financials/
│           │   └── FinancialsPage.tsx  # IS/BS/CF 서브탭, 기간토글, 테이블↔차트
│           │
│           ├── business/
│           │   └── BusinessPage.tsx    # 사업부문/지역 CRUD, PieChart + StackedBar
│           │
│           ├── disclosures/
│           │   └── DisclosurePage.tsx  # 공시 테이블 + IR 메모 CRUD
│           │
│           ├── metrics/
│           │   └── MetricsPage.tsx     # 매출&영업이익&마진, 이익률, 성장률 차트
│           │
│           ├── marketcap/
│           │   └── MarketCapChart.tsx  # 시가총액 + 주가 AreaChart
│           │
│           └── valuation/
│               └── ValuationPage.tsx   # PBR밴드, PER, EPS 차트
│
└── scripts/
    └── seed_companies.py         # DART corp_code → companies 테이블 시딩
```

총 소스 코드: **약 3,130줄** (Python + TypeScript)

---

## 데이터베이스 스키마 (SQLite)

8개 테이블로 구성:

### companies
기업 기본 정보. `seed_companies.py`로 최초 1회 적재.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| corp_code (PK) | TEXT | DART 고유번호 |
| corp_name | TEXT | 회사명 |
| stock_code | TEXT | 종목코드 (6자리) |
| market | TEXT | KOSPI / KOSDAQ |
| sector | TEXT | 업종 |

### financial_statements
DART 재무제표 원본 데이터. 계정과목 1행 = 1레코드.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| corp_code | TEXT | DART 고유번호 |
| bsns_year | INTEGER | 사업연도 |
| reprt_code | TEXT | 11011(연간), 11013(Q1), 11012(H1), 11014(Q3) |
| fs_div | TEXT | CFS(연결) / OFS(별도) |
| sj_div | TEXT | IS(손익) / BS(재무상태) / CF(현금흐름) |
| account_nm | TEXT | 계정명 (매출액, 영업이익 등) |
| thstrm_amount | TEXT | 당기 금액 (원) |

### disclosures
DART 공시 목록. `rcp_no`(접수번호) 기준 캐싱.

### business_segments
사업부문/지역별 매출. 사용자 직접 입력(CRUD).

### ir_notes
컨퍼런스콜/IR 메모. 사용자 직접 입력(CRUD).

### stock_prices
KRX OHLCV + 시가총액. pykrx로 수집.

### fundamentals
KRX PER/PBR/EPS/BPS/DPS. pykrx로 수집.

### cache_meta
캐시 키별 만료 시간 관리.

| 데이터 | 캐시 TTL |
|--------|----------|
| 재무제표 | 7일 |
| 공시 목록 | 1일 |
| 주가/시총 | 1일 |
| 사업부문 | 30일 |

---

## API 엔드포인트

### 기업
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/companies/search?q=삼성` | 기업 검색 (이름/코드) |
| GET | `/api/companies/{stock_code}` | 기업 상세 |

### 재무정보
| Method | Path | 파라미터 |
|--------|------|----------|
| GET | `/api/financials/{stock_code}` | `sj_div` (IS/BS/CF), `period` (annual/quarterly/trailing), `years` (5/10), `fs_div` (CFS/OFS) |

### 공시
| Method | Path | 파라미터 |
|--------|------|----------|
| GET | `/api/disclosures/{stock_code}` | `kind` (A~E), `start`, `end`, `page`, `size` |

### IR 메모
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/ir-notes/{stock_code}` | 목록 조회 |
| POST | `/api/ir-notes/{stock_code}` | 생성 |
| PUT | `/api/ir-notes/{note_id}` | 수정 |
| DELETE | `/api/ir-notes/{note_id}` | 삭제 |

### 주가 / 밸류에이션
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/stock-prices/{stock_code}` | OHLCV + 시가총액 |
| GET | `/api/valuation/{stock_code}` | PER/PBR/EPS + PBR 밴드 |

### 사업부문
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/business/{stock_code}/segments` | 부문/지역 매출 조회 |
| POST | `/api/business/{stock_code}/segments` | 추가 |
| PUT | `/api/business/segments/{id}` | 수정 |
| DELETE | `/api/business/segments/{id}` | 삭제 |

---

## 프론트엔드 컴포넌트 구조

```
App (QueryClientProvider)
└── Dashboard
    ├── Header ─── CompanySearch (autocomplete)
    ├── TabNavigation (7 tabs)
    └── [Active Tab Page]
         ├── SummaryPage ─── 실적테이블, 실적차트, 시총차트, 최근공시
         ├── FinancialsPage ─── SJ 서브탭, PeriodToggle, DataTable ↔ ComposedChart
         ├── BusinessPage ─── 부문/지역 토글, PieChart, StackedBar, CRUD 폼
         ├── DisclosurePage ─── 공시테이블 + IR메모 CRUD
         ├── MetricsPage ─── 매출&영업이익, 이익률, 성장률 차트 3열
         ├── MarketCapChart ─── 시총 AreaChart + 주가 AreaChart
         └── ValuationPage ─── PBR밴드, PER, EPS 차트 3열
```

### 사용된 Recharts 컴포넌트

| 차트 유형 | Recharts 컴포넌트 | 사용 위치 |
|-----------|------------------|-----------|
| 바+라인 콤보 | ComposedChart + Bar + Line | 재무정보, 지표, 요약 |
| 영역 차트 | AreaChart + Area | 시가총액 |
| 파이 차트 | PieChart + Pie + Cell | 사업정보 |
| 스택 바 | BarChart + Bar (stackId) | 사업정보 |
| 라인 차트 | LineChart + Line | PBR밴드 |
| 바+라인 듀얼축 | ComposedChart + 2 YAxis | PER, EPS, 지표 |

---

## 데이터 흐름

```
[사용자: 기업 선택]
     │
     ▼
[Frontend: TanStack Query hook 실행]
     │
     ▼
[GET /api/financials/005930?sj_div=IS&period=annual&years=5]
     │
     ▼
[Backend: routers/financials.py]
     │
     ▼
[services/dart_service.py]
  ├── cache_meta 확인 → 캐시 유효? → SQLite에서 직접 응답
  └── 캐시 없음 → OpenDartReader.finstate_all() 호출
       → financial_statements 테이블에 INSERT
       → cache_meta에 키+만료시간 기록
       → SQLite 쿼리 → JSON 응답
     │
     ▼
[Frontend: Recharts로 차트 렌더링]
```

---

## 주요 설계 결정

### 1. DART 재무제표 분기 계산
DART는 누적 데이터를 반환한다. 개별 분기 수치는 아래처럼 계산:
- Q1 = 1분기보고서 (11013) 값 그대로
- Q2 = 반기보고서 (11012) - 1분기보고서 (11013)
- Q3 = 3분기보고서 (11014) - 반기보고서 (11012)
- Q4 = 사업보고서 (11011) - 3분기보고서 (11014)

현재 구현에서는 DART 원본 값(누적)을 그대로 저장하고, 프론트에서 표시한다.
→ 개별 분기 차감 로직은 추후 개선 대상.

### 2. Lazy DART 초기화
OpenDartReader는 생성 시 corp_code 목록을 다운로드한다. 서버 시작 시간 단축을 위해 첫 API 호출 시점에 lazy 초기화.

### 3. PBR 밴드 계산
과거 PBR 데이터에서 10/25/50/75/90 퍼센타일을 구하고, 각 시점의 BPS에 곱하여 밴드 가격을 산출.

### 4. 사업부문 데이터는 수동 입력
DART OpenAPI가 구조화된 세그먼트 매출 데이터를 제공하지 않으므로, 사용자가 직접 입력하는 CRUD 방식으로 구현.

### 5. 숫자 포맷
한국식 단위 (억, 조)로 자동 변환. `utils/format.ts`에 집약.

---

## 실행 방법

```bash
# 1. API 키 설정
echo "DART_API_KEY=실제키" > .env

# 2. 기업 목록 시딩 (최초 1회)
source .venv/bin/activate
python scripts/seed_companies.py

# 3. 백엔드 (터미널 1)
cd backend && uvicorn main:app --reload --port 8000

# 4. 프론트엔드 (터미널 2)
cd frontend && npm run dev

# 5. 브라우저
open http://localhost:5173
```

---

## 현재 미구현 / 개선 필요 사항

| 항목 | 상태 | 설명 |
|------|------|------|
| 개별 분기 차감 계산 | 미구현 | 누적→개별 분기 변환 로직 (Q2=H1-Q1 등) |
| 4분기 누적(trailing) 뷰 | 미구현 | 최근 4개 분기 합산 |
| 수주잔고 차트 | 미구현 | DART에서 별도 API 없음, 수동 입력 필요 |
| 주요 고객사 비중 차트 | 미구현 | 사업보고서 파싱 또는 수동 입력 필요 |
| 내부자거래 등 공시 세부 필터 | 부분 구현 | kind 파라미터로 대분류 필터만 가능 |
| 강제 새로고침 (refresh) 버튼 | 미구현 | 캐시 무효화 후 재조회 기능 |
| market 컬럼 (KOSPI/KOSDAQ) | 미적재 | seed_companies.py 확장 필요 |
| 에러 바운더리 / 로딩 스켈레톤 | 미구현 | 현재 단순 "로딩 중..." 텍스트 |
| git 초기화 | 미완료 | `git init` + 첫 커밋 필요 |
