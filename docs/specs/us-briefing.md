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

## 어젯밤 매크로 이슈 — 지정 소스 (D-206)
구 ②문단은 매크로 지표를 읽고 태그로 고른 담론 발췌(180자)를 덧붙이는 구조라 "무슨 일이 있었나"가 비었다. 이제 **이슈가 문단의 주어이고, 지표는 그 이슈의 시장 반응 근거**다.
- **지정 텔레그램 채널**(`MACRO_CHANNELS`, 코드 상수): 카이에 de market · Macro Jungle · Macro Trader · YIELD & SPREAD · 삼성 매크로 정성태 · 허재환(유진 전략) · 한지영(키움 전략/시황). 트럼프 발언 채널은 제외(사용자 지정).
- **미국 주요 매체 RSS**(`pipeline/macro_news.py`, 무키): Bloomberg(Markets·Economics) · CNBC(Economy·Finance) · NYT(Business·Economy·Politics) · Politico(Politics) · MarketWatch(Top Stories) · Washington Post(Business) + 공식 Fed(보도자료·연설, 은행 인가·제재 항목 제외). 제목+요약만 쓴다(본문은 유료 벽). WSJ·Reuters·AP·BLS·재무부는 피드가 폐지·차단돼 제외(2026-09-29 실측).
- **시간창**: 직전 거래일 미국장 마감(UTC 20:00) ~ 기준일 다음날 UTC 00:00(KST 09:00). 날짜 문자열 일치가 아니라 시각 구간.
- **이슈 추출(sonnet 1콜, 프롬프트 해시 캐시 `us_macro_issues`)**: 창 안의 지정 채널 원문 + 뉴스 헤드라인 → 이슈 최대 5개 `{title, what, reaction, sources[{ref, quote}]}`. **인용 검증**: quote가 해당 원문(텔레그램 본문, 뉴스 제목+요약)에 공백 정규화 후 그대로 있어야 채택, 검증 인용이 0개인 이슈는 버린다(Weekly 하네스 D-173 인용 규율 차용).
- **실패 공개**: 피드별 수집 실패는 `macro_news.failed`로 반출 → 화면 안내(조용한 fallback 금지).

## LLM 종합 (하루 1회·캐시, sonnet 1콜) — 2문단 (D-206)
구성은 **매크로 브리핑 + 거래대금 기반 기업 이슈 브리핑** 두 문단. 지수 수치는 카드 상단 지수 타일이 이미 보여주므로 별도 문단을 두지 않는다. 구 ④ 섹터 비중 흐름 문단·비중 추이 차트는 폐지(사용자 판단: 쓸모 낮음).
- `drivers`(매크로): 4~6문장. 검증된 매크로 이슈 2~3개를 사건 중심으로, 각 문장 끝에 `[S n]` 출처 표식. 지표는 그 이슈의 반응 근거로만(금리 변화는 **bp**). 한 매체·한 채널만 말한 것은 누가 말했는지 귀속.
- `issues`(기업): 3~4문장. 기존 규율 그대로(쏠린 섹터 1~2개, 중요 개별 종목 2~3개를 사건으로).
- `sources`: 표식이 가리키는 출처 목록 `{n, kind(telegram|news|official), publisher, title, url, doc_id}` — 과거 브리핑도 자기충족적이게 종합과 함께 저장.
- `study_candidates`·`share_candidates`·`movers_why`는 유지. 구 행(`index_summary`·`flow`)은 읽기만 호환.
- **규율**: 재료에 없는 이벤트를 지어내지 않는다. 판정 어휘(방아쇠·배경 조건)를 본문에 노출하지 않는다.
- 캐시: `us_briefings(trade_date PK, signature, synthesis_json, model, created_at)`. signature=프롬프트 해시.

## 활용 연결 (기존 프리미티브)
- 클러스터/개별 → `narrative`(주제 내러티브)·`sector_narratives`(N:M) 딥링크.
- 커버 종목 → `/us/:ticker` 도시에(여론·월드모델·렌즈).
- 스터디 후보 → `question`(분할정복) 착수 훅.
- 배경 → `market_regime`(시장 국면).

## API
`GET /api/spine/us/briefing` (`/{ticker}`보다 먼저) → `UsBriefing{status, trade_date, fetched_at, error, clusters[], idiosyncratic[], movers[], synthesis?}`.
`/movers`(us-movers.md)는 raw 리스트로 유지.

## 프론트 (홈 상단 승격, `UsBriefingSection`)
아침 터미널의 첫 카드. 2문단 산문(매크로 문단에 출처 위첨자 링크) + **섹터 쏠림 바** + 개별 이슈 리스트(사유 배지) + 신규 진입 + 스터디/공유 후보. 상위 20 전체는 Collapsible로 접어둠. 종목 → `/us/:ticker`, 클러스터/내러티브 → `/narrative`.

## 소스 관리 — 브리핑 재료 목록 (D-206 후속)
카드 헤더의 **'소스 관리' 버튼 → Dialog**. 브리핑이 어떤 출처를 쓰는지와 각 출처의 최근 수집 상태를 보여준다. 읽기 전용(목록 편집은 범위 밖, 채널·피드는 코드 상수 `MACRO_CHANNELS`·`FEEDS`).
- `GET /api/spine/us/briefing/sources` (LLM·네트워크 0, DB 읽기만) → `groups[]{key, label, used_for, items[]{name, detail, url, last_seen, recent_count, status}}`.
  - `macro_telegram` 매크로 문단 · 텔레그램 채널 — 최근 글 시각, 24시간 글 수. 미등록·수집 꺼짐도 그대로 표시.
  - `macro_news` 매크로 문단 · 미국 매체·Fed RSS — 피드별 최근 기사 시각, 24시간 기사 수.
  - `company` 기업 문단 — TradingView 거래대금 상위 20, Yahoo Finance 종목 헤드라인, 수집 문서 언급.
  - `indicators` 시장 반응 근거 — 지수, 매크로 지표(Yahoo·FRED).
- `status`: `ok`(최근 2일 내 자료) · `quiet`(그보다 오래됨·자료 없음) · `off`(미등록·비활성).
- 5-state(Dialog 내부): Loading=Skeleton · Error=ErrorState+재시도 · Empty=그룹 0(발생 불가지만 EmptyState) · Partial=`quiet`/`off` 항목은 경고 배지로 · Ideal=그룹별 목록.

## 갱신 케이던스 — 버튼 주도 (D-099·D-100)
아침에 전날 미국장을 보는 용도라 **자동 갱신 없이 버튼으로만** 갱신한다.
- **일반 로드(`GET`)**: 최신 스냅샷을 **순수 읽기**(`read_leaders`) — 네트워크·뉴스조회·LLM 전부 없음. 저장된 종합을 그대로 보여준다(`_read_synthesis`). → 로드가 절대 느려지지 않고, 자동으로 값이 바뀌지 않음.
- **'지금 업데이트' 버튼(`GET ?force=true`)**: TradingView·뉴스 재수집 + 재종합(sonnet). signature 캐시라 재료 불변이면 즉답, 새 세션·뉴스면 ~2분(버튼 스핀으로 안내).
- **크론은 선택**: `scripts/compute_briefing.py`(=버튼과 동치 CLI)를 `0 8 * * *`로 걸면 아침에 미리 데워둘 수 있으나 필수 아님. 스냅샷이 아직 없으면 빈 상태 + 버튼 안내.

## 5-state
| 상태 | 조건 | 렌더 |
|---|---|---|
| Loading | 쿼리 진행 | Skeleton |
| Error | status=error·쿼리실패 | ErrorState+재시도 |
| Partial | status=stale(갱신실패) **또는** synthesis=null(LLM 미가용) | 구조화 스켈레톤(클러스터·개별) + 경고/안내 배너 |
| Empty | movers=0 | EmptyState |
| Ideal | mood 산문 + 구조화 + 후보 | 풀 브리핑 |

→ LLM이 없어도 **결정적 스켈레톤(쏠림·개별·신규)** 은 항상 뜬다. 조용한 실패 금지.
