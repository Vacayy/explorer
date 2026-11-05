# 수출입(무역) 팔로우 — 품목별 추이 + 관련 종목

> 2026-07-24 기획. BACKLOG "게이트 대기: 무역 커넥터 ← 관세청 API 키" 해제 착수.
> transcript 팔로우(D-061)와 같은 골격: **팔로우 탭 + 전용 페이지**. 특수 케이스(문서가 아니라 통계 시계열)라
> 자체 페이지에서 **각 품목의 수출입 추이 + 관련 종목(파급 논리)**을 본다.
> 결정(2026-07-24): 관심 품목 팔로우(시드+추가) · 관련 종목=LLM 논리 지목 · 국가 차원은 후속(품목 총계만 MVP).

## 관통 원칙
1. **관심 품목 팔로우** — 전체 HS를 긁지 않고 사용자가 핵심 품목을 구독(transcript式). 시드 세트 제공.
2. **품목 → 관련 종목은 파급 논리(LLM)** — 문서 공동언급이 아니라 "이 품목 수출↑/↓ → 수혜/피해 종목"을
   인과 논리로 지목(D-036 말뭉치 최신편향 탈출 계승). resolve_and_enrich로 종목코드·RS·밸류·유니버스 태그.
3. **캐시 우선** — 관세청 호출은 `cache_service`. 통계는 월 1회 갱신이라 월 단위 캐시. 관련 종목도 캐시(비쌈).
4. **국가 차원 후속** — MVP는 품목 총계(수출/수입/무역수지). 대중·대미 등 국가별 분해는 다음 단계.
5. **기계는 제안·사람은 승인** — 관련 종목이 유니버스 밖 신규 후보면 편입 고리(③→①)로 승격 가능(D-037).

---

## 데이터 소스 — 관세청 품목별 수출입실적 (공공데이터포털)
- **API**: data.go.kr [관세청_품목별 수출입실적(GW)](https://www.data.go.kr/data/15101609/openapi.do) — REST·XML·무료, 개발계정 **일 10,000 호출**, 월 갱신.
- **인증키**: 사용자가 data.go.kr에서 활용신청 → 서비스키 발급 → `.env` `DATA_GO_KR_KEY`.
- **요청 파라미터**(참고문서·Swagger에서 구현 시 확정): `serviceKey` · `strtYymm`(시작 YYYYMM) · `endYymm`(종료) · `hsSgn`(HS부호).
- **응답 필드**(예상): `hsCd`·`year`(또는 기간) · `expDlr`(수출금액$) · `impDlr`(수입금액$) · `expWgt`·`impWgt`(중량kg) · `balPayments`(무역수지).
  ※ 정확한 엔드포인트/필드명은 구현 착수 시 `관세청조회코드_v1.2.xlsx`·Swagger로 확정.

---

## 데이터 모델

```sql
-- 팔로우 품목 (구독)
CREATE TABLE trade_follow (
  hs_code       TEXT PRIMARY KEY,     -- HS 부호 (2·4단위 혼용, 예 '8542'=반도체)
  item_name     TEXT NOT NULL,        -- '반도체(집적회로)'
  group_label   TEXT,                 -- IT·자동차·소재·에너지 ... (선택 그룹핑)
  active        INTEGER DEFAULT 1,
  added_at      TEXT DEFAULT (datetime('now'))
);

-- 품목별 월별 수출입 통계 (추이) — 시계열
CREATE TABLE trade_stats (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  hs_code       TEXT NOT NULL,
  period        TEXT NOT NULL,        -- 'YYYY-MM'
  export_usd    REAL,                 -- 수출금액 ($)
  import_usd    REAL,                 -- 수입금액 ($)
  export_wt     REAL,                 -- 수출 중량 (kg)
  import_wt     REAL,
  balance_usd   REAL,                 -- 무역수지 (수출-수입)
  fetched_at    TEXT DEFAULT (datetime('now')),
  UNIQUE(hs_code, period)
);

-- 품목 관련 종목 (LLM 논리 지목, 캐시) — scenario/beneficiary와 동일 철학
CREATE TABLE trade_beneficiaries (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  hs_code       TEXT NOT NULL,
  stock_code    TEXT,                 -- resolve된 종목코드 (없으면 미해결 이름)
  name          TEXT,
  rel           TEXT,                 -- '수혜' | '피해'
  reason        TEXT,                 -- 이 품목 추이가 왜 이 종목에 수혜/피해인지 (한 문장)
  rs            REAL, per REAL, mktcap REAL, pos_52w REAL,   -- enrich (beneficiary 재사용)
  in_universe   INTEGER, universe_groups TEXT,               -- 크로스체크 태그
  computed_at   TEXT DEFAULT (datetime('now')),
  UNIQUE(hs_code, name)
);
```

> `observations`(범용 시계열)에 넣지 않고 전용 `trade_stats`를 쓰는 이유: 수출/수입/중량/무역수지가 한 행에
> 묶이는 구조가 명확하고, HS품목이 entity가 아니라 별도 축이라 entity_id 강제가 부자연스럽다. (필요 시 후속에서
> observations로 미러링 가능.)

**기본 팔로우 시드** (핵심 품목, HS부호는 구현 시 관세청 코드표로 확정):
- 반도체(집적회로 8542) · 자동차(승용 8703) · 자동차부품(8708) · 2차전지/축전지(8507) ·
  석유제품(2710) · 합성수지(39) · 철강(72) · 선박(89) · 무선통신기기/휴대폰(8517) · 컴퓨터(8471) ·
  디스플레이(평판 8524) · 정밀화학원료 등 — IT/자동차/소재/에너지 그룹.

---

## 백엔드
- `pipeline/trade.py`: 관세청 커넥터(월별 fetch·캐시) + `collect_followed`(팔로우 품목 최신월 수집) +
  `seed_default_follows` + `compute_beneficiaries(hs_code)`(LLM 논리 지목 → resolve_and_enrich → 캐시).
- `routers/spine_trade.py`: GET `/trade/follow`(그룹별 팔로우+최신월) · `/trade/{hs}`(시계열+관련종목) ·
  POST `/trade/follow`(구독 토글) · POST `/trade/seed` · POST `/trade/{hs}/beneficiaries`(멱등 재계산).
- `scripts/collect_trade.py`: `ops.run_job('collect_trade', ...)` — 월 1회 cron(관리자 게이트).
- `database.py init_db()`에 3테이블 + `.env` `DATA_GO_KR_KEY`(config.py).

## 화면 — 산업 › 수출입 (2026-11-05 화면 구조 개편 4b, 아래 옛 2분할을 대체)
`/follow/trade`, `follow/TradePage` · `lib/trade`. 원천 `/highlights?limit=100&period=`(요약·급등 표·산업별) + `/follow`(격자 품목) + `/{hs}`(칸 추이·수혜 종목, 상세 시트).
1. 요약 줄: 수출 총액(통계월, 새 달 통계 전이면 'n월 기준' 칩) · 평소보다 크게 늘어난 품목 수 · 크게 줄어든 품목 수 · 기여 1위(증가분의 몫).
2. 주요 품목 한눈에: 상위 품목(`nested_in` 없음) 수출액 상위 12 격자. 칸 = 이름·급등 배지·분류 · 최신 수출액·전년 대비 · 36개월 막대 + 12개월 평균 선(칸마다 세로축이 다름) · 수혜 종목 2. 정렬 `trade_sort` = `value`(기본)·`surge`(급등 먼저)·`mine`(관심 종목의 `/by-stock` 역링크가 걸린 품목 먼저, 없으면 한 줄로 알리고 수출액 순).
3. 평소보다 크게 늘어난 품목(수출액·전년 대비·전월 대비·3개월 전년 대비·증가분 기여, 상위 12) + 월 선택 ‹ YYYY년 M월 ›(`month`) | 산업별 수출(수출액·비중·품목 수·급등·급감).
   - 급등·급감 목록과 수(요약 줄·산업별 급등·급감 열)에서 세목(`nested_in`, 팔로우한 다른 HS의 하위 부호)은 뺀다(D-301) — 관세청은 상위 부호에 하위 세목을 합산해 돌려주므로 상위가 급등이면 세목도 함께 급등으로 잡혀 같은 움직임을 두세 번 센다. 상위가 팔로우되지 않은 10자리 품목(예: SSD·PCB·비행기)은 그 자체가 최상위라 남긴다. 판정은 서버(`trade_metrics.highlights`·`table` 분류 집계)에서 한다. 분류별 급등 수에 신규(`new`)는 세지 않는다(D-303 — 기준값이 없어 '평소보다'를 말할 수 없다; 급등 목록에는 신규 배지로 남는다). 2026-09 실측 22 → 13(D램·HBM·낸드 등 세목 9개 제외). 세목의 판정 배지는 `/follow` 행에 그대로.
4. 품목(칸·표 줄)을 누르면 `hs` 시트에 옛 상세(수출입 추이 + 관련 종목·다시 지목). 모바일은 아래 시트, 표는 전월·3개월 열을 줄인다.
5. 5-state: 팔로우 0 → 기본 세트 버튼 · 로딩 = 요약 칸·격자 스켈레톤 · 블록 단위 오류(요약·격자·표가 따로) · 급등 0이면 '이번 달에는 … 없습니다' · 칸 추이 실패는 그 칸만.
- 서버 추가형: `HighlightRow.yoy3m`(3개월 합 전년 대비, 비율).

## 옛 화면 (transcript와 같은 골격, 2026-11-05까지)
### 1. 전용 페이지 (`/follow/trade` — 팔로우 모드 '수출입' 탭) — 2분할 or 목록+상세
- **좌**: 팔로우 품목 리스트(그룹별). 각 품목 옆 최신월 수출액·전월/전년 대비 방향(▲▼). "+품목 추가".
- **우 (선택 품목)**:
  - **수출입 추이 차트** — 월별 수출·수입 라인(+무역수지) lightweight-charts. YoY 표기.
  - **관련 종목** — LLM 논리 지목(수혜/피해 + 이유), RS·밸류, 유니버스 태그. 유니버스 밖이면 '신규 후보' → 편입 버튼(③→①).
  - 상단 "관련 종목 다시 지목"(멱등 compute).
### 2. 피드 탭 — 없음 (무역은 문서가 아니라 통계 — feed 성격 아님).

### 5-state
- **Empty**: 팔로우 0 → "핵심 수출입 품목을 팔로우하세요" + 기본 세트 원클릭 시드.
- **Loading**: Skeleton(좌 리스트+우 차트).
- **Partial**: 팔로우는 있으나 통계 미수집 → "수집 대기"(관리자 '수출입 수집' 잡).
- **Error**: 관세청 호출 실패 → ErrorState+재시도(키·한도 상태).
- **Ideal**: 좌 품목 리스트 + 우 추이 차트 + 관련 종목.

---

## 구현 순서
1. **키 수령 후** DB 3테이블 + `pipeline/trade.py` 커넥터 → 시드 품목 1개(반도체) 수집 검증(월별 trade_stats 채워지나).
2. **전용 페이지** 좌 리스트 + 우 추이 차트(5-state) + 기본 세트 시드 버튼. 팔로우 탭 '수출입' 추가.
3. **관련 종목**(LLM 논리 지목) — compute_beneficiaries + resolve_and_enrich 재사용 → 우 패널 + 편입 고리.
4. **cron 편입**(월 1회, ops.run_job 게이트 + 관리자 페이지 노출).

## Out of Scope (MVP)
- 국가별(교역국) 분해 — 후속(품목 × 주요국).
- 시도별·성질별 통계 — 후속.
- 실시간(월 갱신으로 충분).

## 참조
- 관세청 품목별 수출입실적: data.go.kr/data/15101609 · 품목별 국가별: /15100475
- 파급 논리 수혜 종목: docs/private/DECISIONS.md D-036 · pipeline/beneficiary.resolve_and_enrich · scenario.py
- 편입 고리(③→①): D-037 · 같은 골격: docs/specs/transcript-follow.md · 시계열 스키마 배경: D-004(observations)


---

## 2026-09-08 · data-watcher 이식 (D-140)

별도 프로젝트 `~/dev/data-watcher`(관세청 수출입 워처)에서 검증된 것을 explorer로 옮겼다. API 키는 두 프로젝트가 같은 키(`DATA_GO_KR_KEY`).

**커넥터(`pipeline/trade.py`)**: 최소 호출 간격 0.35초(`CUSTOMS_MIN_INTERVAL`) + 429/5xx 지수백오프(지터) · `errMsg`(인증)와 `resultCode`(조회) 둘 다 검사 · `totalCount` 페이징 · `item_name(hs)`(관세청 품목명으로 HS 오기 대조) · `latest_available_period(hs)`(1콜 신선도).

**수집(`collect_followed`)**: 최신 window부터 역순, 루프 바깥은 기간(첫 패스에 전 품목 최근치가 찬다) · 품목 단위 실패는 삼키되 `collect_status()`가 ok/partial/error/noop 판정 · DB 커넥션은 쓰기 순간에만 · 시작월 `TRADE_COLLECT_START_YYYYMM`(기본 202101 — YoY z에 24개월↑).

**워치리스트**: `scripts/trade_watchlist.local.csv`(gitignore, 168품목·15분류 — 종목 힌트가 든 로컬 큐레이션, universe.local.json과 같은 취급) → `seed_watchlist()` 멱등 시드. CSV에 없는 기존 팔로우는 유지(기본 11품목·UI 추가와 공존). 선행 0 유실 보정.

**파생지표(`pipeline/trade_metrics.py`, 저장 안 함)**: mom·yoy·qoq(직전 3개월 합 vs 그 앞 3개월)·yoy3m · 지표별 로버스트 z(median/MAD, 관측 8↑) · 판정 surge/plunge/new/none(규모 게이트 $10M, zscore |z|≥2 / fixed 임계) · '이력 부족'과 '신규' 구분 · 기여도 |Δ|/Σ|Δ|.

**API**: `GET /follow`에 mom·qoq·yoy3m·z·flag·reason·contribution 추가 · **`GET /highlights`**(급등·급감 랭킹, 기본 기여도 순) · **`GET /{hs}/metrics`**(월별 파생지표 시계열). FE TradePage는 기존 필드만 쓰므로 무변경(후속: 판정 격자·하이라이트 뷰).

**스케줄**: launchd `dev.explorer.trade` 매일 09:20 `collect_trade.py --if-fresh` — 원천 최신월 1콜 확인 후 전진했을 때만 최근 24개월 수집. (전엔 `collect_trade` 잡이 ops 레지스트리에만 있고 **launchd에 등록돼 있지 않았다**.)

**초기 적재**: data-watcher `trade.db`의 9,718행(2021-09~2026-07)을 ATTACH로 이식 — 재수집 없이 5년치 확보.

**대화 도구 `get_trade`**: 품목 지정=월별 수출·YoY·z·지표별 판정·수혜종목, 미지정=최신월 급등·급감 하이라이트+분류별 합계.

**남은 것**: 국가별 축(별도 API 활용신청 필요, watcher D-014) · 다중 HS 합산 품목 15건(list-review.md) · FE 판정 격자.

---

## 2026-10-16 · 판정 노출과 데이터 위생 (P6b)

화면·위젯 계약은 [explore-data](explore-data.md) §1·§5.

- FE 레일이 서버 판정(`flag`·`reason`·`contribution`)을 배지·툴팁으로 보이고, 기본 정렬은 이번 달 기여도다.
- `normalize_labels`(시드 직후마다 멱등)가 HS 오기('총수출' → 'D램'), 'OLDE' 오타, 번호 접미 중복명을 정리한다.
- `trade_metrics.nesting`이 하위 세목(`nested_in`)을 수출 합계·기여도 분모·같은 분류 합계에서 뺀다.
- `GET /by-stock/{code}`: 종목 → 품목 역링크.
- 남은 것: 새 통계월 적재 때 급등 품목의 관련 종목을 일괄 지목하는 일(이벤트 구동, 비용 결정 필요)과 피드 카드 제목에 급등 품목을 넣는 일.
