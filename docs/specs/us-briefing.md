# 어젯밤 미국장 브리핑 — 분위기 파악 가속기

**목적**: 리서치를 *대신*하지 않고, 아침에 **분위기를 30초에 잡게** 한다. 전일 미국장에서 자금이 어디로 쏠렸나 → 어떤 내러티브인가 → 새 흐름인가 → **뭘 스터디하고 뭘 공유할지 조준**. (배경: 펀드매니저 피드백, DECISIONS D-095)

거래대금 상위(=주목의 raw 신호)를 두 층으로 읽는다: **쏠림(섹터/내러티브)** + **개별(idiosyncratic)**.

## 데이터
- 소스: TradingView 스크리너(무키, us-movers.md 계승) — 컬럼에 **`sector`·`industry`·전일 등락률(`change`)·시총** 추가. **같은 1콜**이라 클러스터링·개별탐지 전부 **LLM 0**.
- 히스토리: `us_movers`를 **일별 스냅샷**으로(PK `trade_date,rank`). 직전 스냅샷과 티커 비교 → **신규 진입** 판정. 최근 7일 보존.

## 결정적 코어 (LLM 0, `pipeline/us_briefing.py`)
1. **클러스터**: TradingView `sector` → KR 라벨 매핑으로 그룹. 클러스터별 {종목수, 합계 거래대금, **비중%**(상위20 합 대비), 대표 등락률(median), 신규 포함 여부}. 쏠림 = 최상위 클러스터 비중.
2. **개별 이슈 탐지**: 다음 중 하나면 flag — ①`|등락률| ≥ 8%`(거래대금+급등락 동반=실이벤트) ②클러스터 median과 **부호 역행**(그룹에 3+ 종목일 때) ③**신규 진입**. 사유 라벨(`급등 +18%`·`그룹 역행`·`신규 진입`).
3. **enrich(우리 커버리지)**: `resolve_us(ticker)`로 entity 해소 → 있으면 최근 3일 언급수 + 걸린 내러티브(worldmodel 패턴: `entity_relations.narrative_id`). 없으면 `coverage=uncovered` → **스터디 후보**. **ADR 크로스레퍼런스(D-098)**: `_ADR_HOME={"SKHY":"SK하이닉스"}` 이름맵으로 ADR은 본체(KR) 엔티티도 함께 union 조회 — 하드 병합 없이 국내 담론(SK하이닉스 1349건·레오폴드 내러티브)을 ADR 무버에 잇는다(SKHY: uncovered→covered·언급 0→304).

## 그날 시장 담론 주입 (D-096 — 시장 레벨 촉매를 잡는 열쇠)
개별 종목 경로(ticker→entity→narrative)로는 **시장구조 사건**(예: AI 디레버리징·"레오폴드 사태")을 못 잡는다 — 그 서사는 US 무버가 아니라 테마/한국 엔티티에 링크된 문서에 산다. 그래서 종합에 **그날 담론**을 함께 주입:
- **지배 테마 랭킹**: 그날 문서의 theme/sector 엔티티 상위(문서수) — "수급·매크로 상승 = 수급/디레버리징 국면" 같은 시장 무드.
- **시장구조 코멘터리 문서**: `{수급·매크로}` + 그날 주도섹터 링크 문서를 **최신순**으로(장 마감 무렵의 '정리/총평' 샤프 포스트가 상단). *hits(렌즈 링크 수) 정렬은 다중테마 대형문서[시황 랩·대형 실적]가 저브레드스 서사를 덮어 폐기.* 제목 중복 제거, 상위 8.
- 종합 프롬프트가 **거래대금 쏠림(무엇) × 담론(왜)을 교차** — 시장 레벨 사건을 먼저 짚고, 급증의 **성격**(신규 매수 랠리 vs 청산·디레버리징·반등)을 담론 근거로 판단. 담론이 사건을 지목하면 이름 명시, 근거 없으면 지어내지 않음.
- 응답에 `market_themes`·`market_docs` 반환 → 프론트가 거래대금 × 내러티브 교차의 **근거**로 노출(테마 칩→`/narrative`, 문서→`/doc/:id`).

## 개별 종목 '왜' — US 원천 헤드라인 (D-097)
시장 레벨 담론(D-096)이 "왜 전체가 움직였나"라면, 이 층은 "**왜 이 종목이**"를 채운다 — 담론과 상보.
- 소스: **yfinance `.news`**(무키) — 종목별 당일 US 원천 헤드라인(예: BE +26% ← "Mizuho Upgrades / Q2 Results", 메모리주 ← "Amazon·Apple 경영진 공급부족 언급"). `pipeline/us_news.py`, `us_ticker_news` 6h 캐시.
- 비용 바운드: **개별 이슈(flag) 종목만** 병렬 수집(ThreadPoolExecutor). 실패는 조용히 빈 리스트(브리핑 안 죽인다).
- 종합 주입: 개별 이슈 종목에 헤드라인이 있으면 그걸 그 종목의 '왜'로 삼음. **헤드라인이 촉매를 설명하면 스터디 후보가 아니라 공유 후보로**(승격), 헤드라인이 있어도 설명 못 하면 LLM이 스터디 후보로 정직하게 남김.
- 응답: `movers[].headlines`(FE가 개별 이슈 행 밑에 '왜' 줄로 노출, 원문 링크). signature에 헤드라인 url 포함(뉴스 바뀌면 재종합).

## LLM 종합 (하루 1회·캐시, sonnet 1콜)
구조화 팩트(클러스터·개별·커버리지) **+ 그날 담론(테마·문서) + 개별 헤드라인** 입력 → `{mood, study_candidates, share_candidates}`.
- `mood`: 3~5문장. 어젯밤 자금이 어디로·(아는 범위의)왜·새 흐름인가.
- `study_candidates`: 커버 안 됐거나 촉매 미상인 주목 종목 + 한 줄 이유.
- `share_candidates`: 이미 내러티브 있는 것 중 공유할 만한 것.
- **규율**: 미상 촉매를 지어내지 말 것 — 모르면 스터디 후보로.
- 캐시: `us_briefings(trade_date PK, signature, synthesis_json, model, created_at)`. signature=구조화 요약 해시. 안 바뀌면 재사용.

## 활용 연결 (기존 프리미티브)
- 클러스터/개별 → `narrative`(주제 내러티브)·`sector_narratives`(N:M) 딥링크.
- 커버 종목 → `/us/:ticker` 도시에(여론·월드모델·렌즈).
- 스터디 후보 → `question`(분할정복) 착수 훅.
- 배경 → `market_regime`(시장 국면).

## API
`GET /api/spine/us/briefing` (`/{ticker}`보다 먼저) → `UsBriefing{status, trade_date, fetched_at, error, clusters[], idiosyncratic[], movers[], synthesis?}`.
`/movers`(us-movers.md)는 raw 리스트로 유지.

## 프론트 (홈 상단 승격, `UsBriefingSection`)
아침 터미널의 첫 카드. mood 산문 + **섹터 쏠림 바** + 개별 이슈 리스트(사유 배지) + 신규 진입 + 스터디/공유 후보. 상위 20 전체는 Collapsible로 접어둠. 종목 → `/us/:ticker`, 클러스터/내러티브 → `/narrative`.

## 갱신 케이던스 — 하루 1회 + 수동 버튼 (D-099)
아침에 전날 미국장을 보는 용도라 **24시간 1회**로 고정: 무버 캐시 24h·뉴스 캐시 24h → 장중 자동 재조회 없음. 갱신 경로 둘: ①`scripts/compute_briefing.py`(run_job) 아침 8시 크론 `0 8 * * *`(마감 후 결산, sonnet 종합 pre-warm) ②홈 카드 **'지금 업데이트' 버튼**(`GET ?force=true` → TradingView·뉴스 재수집 + 재종합). lazy 생성(D-095)이 fallback. signature 캐시라 재료 불변이면 재종합 0.

## 5-state
| 상태 | 조건 | 렌더 |
|---|---|---|
| Loading | 쿼리 진행 | Skeleton |
| Error | status=error·쿼리실패 | ErrorState+재시도 |
| Partial | status=stale(갱신실패) **또는** synthesis=null(LLM 미가용) | 구조화 스켈레톤(클러스터·개별) + 경고/안내 배너 |
| Empty | movers=0 | EmptyState |
| Ideal | mood 산문 + 구조화 + 후보 | 풀 브리핑 |

→ LLM이 없어도 **결정적 스켈레톤(쏠림·개별·신규)** 은 항상 뜬다. 조용한 실패 금지.
