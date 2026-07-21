# Explorer — 시스템 현황 명세

> 최종 갱신: 2026-07-10 (feat/etl-spine 브랜치 기준)
> 목적: 현재 시스템의 전체 구조·기능·데이터를 한눈에 파악하기 위한 현황 문서.
> 기획 배경·온톨로지는 docs/ontology.md, docs/specs/product-v2.md 참조. 의사결정 이력은 docs/DECISIONS.md.
> 유지 규칙: 구조(테이블·파이프라인·라우터·IA·의존성)가 바뀌는 커밋은 본 문서 갱신을 포함한다 (CLAUDE.md Context Discipline).
> (구 ARCHITECTURE.md·PLAN.md는 초기 대시보드 시절 문서 — docs/archive/로 이동, 본 문서가 현행)

## 1. 제품 한 줄 정의

**"매일 아침 여는 개인 리서치 터미널"** — 텔레그램·블로그·DART·주가를 자동 수집해
LLM으로 태깅·요약하고, 지식그래프 위에서 신호·브리핑·질의응답을 제공하는 투자 월드모델의 1단계.

### 비타협 설계 원칙
| 원칙 | 의미 |
|---|---|
| **사실/가설 분리 (epistemic)** | LLM 산출(태그·요약·해석·답변)은 전부 '가설' — confidence·모델명 표시, UI에서 주황(hypothesis) 스타일로 구분 |
| **신호는 근거와 함께** | 근거 문서 없는 신호 표시 금지, "왜?"가 항상 1클릭 |
| **층위: 홈=delta, 디테일=state** | 홈은 변화의 스트림만, 전체 맥락은 디테일 페이지 |
| **소유권 분할 (vault)** | 자동수집=DB 원본→vault로 투영 / 사람의 가설·메모=마크다운 원본→DB로 흡수. 대칭 sync 금지 |
| **URL = 상태의 단일 소스** | 모든 필터·탭이 URL 쿼리/경로 (새로고침·공유 보존) |
| **전 화면 5-state** | Empty/Loading/Partial/Error/Ideal + FreshnessStamp(수집 시각) |
| **시간 정박 (temporal)** | 발행일 ≠ 사건 발생일. enrich가 문서마다 time_orientation(past/current/forward/mixed)·reference_period 추출 → 내러티브·다이제스트·신호가 '전망을 방금 일어난 사건으로' 착각하지 않게 회고/현재/전망 구분 (D-021) |

## 2. 아키텍처 조감

```
[소스]  텔레그램(텍스트+이미지) · 블로그(네이버/티스토리/RSS) · vault/notes(내 가설)
        DART(전시장 공시) · FDR(전종목 주가) — (대기: 관세청 무역)
   │
   ▼  30분 cron 체인 (run_chain.sh — 겹침 방지 락, logs/ingest.log)
ingest(수집→enrich→그래프) → redigest_youtube(자막 raw 치유) → compute_signals → compute_narratives → extract_events(이미지 비전)
  → scan_actions(기업활동) → compute_digests(1D/7D) → vault_sync --export → build_search_index
   +  평일 16:10: ingest_prices --daily (전종목 OHLCV)
   │
   ▼
[SQLite 단일 DB (WAL, busy_timeout 30s)]
  척추: raw_documents · enrichments · entity_links · entities · entity_relations
        signals · entity_digests · corporate_actions · capital_raise_details
        media_analysis · entity_keywords · follows · doc_fts(BM25) · doc_vec(벡터)
  도메인 원본: stock_prices(71만행) · financial_statements · disclosures … (옛 세계)
   │
   ▼
[FastAPI :8000]  spine_* 라우터 10종 + 기존 라우터 + /media 정적
   │
   ▼
[React :5173]  홈 · 탐색(신호/AI질문/기업활동) · 피드 · 문서 · 종목 디테일 · 리서치노트
[Obsidian(선택)]  vault/ 폴더 — entities 도시에(자동) + notes 가설(사람)
```

## 3. LLM 계층 — Claude Code headless (`claude -p`)

API 키 없이 **구독 인증**으로 구동 (`.env: ENRICH_ENGINE=claude-code, CLAUDE_BIN=절대경로`).
`ANTHROPIC_API_KEY` 설정 시 자동으로 API 모드 전환 (코드 준비됨).

> **프롬프트 위생 (사용자 출력 규칙)**: 'K1/K2/K3'·'corroborated/contested/observed'·'(독립 N)'·pace layer 같은 **내부 코드·약어는 LLM 출력에 노출 금지**. 지식 주입 블록(knowledge_block)·worldview는 이를 자연어로만 표현하고 no-leak 지시를 포함한다. 출처를 어색하게 괄호로 붙이느니 아예 표기하지 않는다 (사용자 지침).

| 용도 | 모델 | 시점 | 캐시/멱등 |
|---|---|---|---|
| 문서 태깅(종목 정규화·산업·토픽·요약·감성) | haiku | 수집 시 문서당 1회 | content_hash + model 티어 (keyword→LLM 자동 백필) |
| 이미지 분류·증시일정 추출 | haiku (+Read 비전) | 이미지당 1회 | media_analysis |
| 공시 요약 / 유무증 구조화 추출 | haiku | 공시당 1회 | corporate_actions.summary / capital_raise_details |
| 1D/7D 다이제스트 + 새로운 시각 | haiku | 문서 집합 변경 시만 | doc_ids_hash |
| RAG 질의응답 + 갭 분석 | **sonnet** (RAG_MODEL) | 사용자 질문 시 | — |
| 임베딩 (검색) | 로컬 fastembed (다국어 MiniLM 384d) | 문서당 1회 | doc_vec |

## 4. 데이터 계층 (테이블 카탈로그)

### 4-1. 그래프 척추 (greenfield — 단일 진실원천, 현재 행수)

| 테이블 | 행수 | 역할 |
|---|---|---|
| `entities` | 4,135+ | 노드: company·sector·theme·person + **macro·policy·event**(인과 그래프 노드, D-023 활성화) |
| `entity_relations` | 2,760+ | 엣지: MEMBER_OF(기업→섹터, fact) + **CAUSES·BENEFITS_FROM**(인과, hypothesis — 내러티브 산출). epistemic_type·confidence·valid_from/to + mechanism·reference_period·time_orientation·narrative_id(D-023) + feedback_note(both_temporal 해소 근거 — non-null이면 상충 아닌 시점 다른 피드백 나선, contested 계산서 제외, D-029) + geo_scope(인과 주장의 장소 스코프 — 통제어휘 한국·미국·중국·유럽·일본·대만·글로벌·기타, reference_period와 대칭, backfill_geo_scope.py, D-034) |
| `narratives` | 버전별 | 내러티브 1급 객체 — topic별 version 보존(supersede, 드리프트 추적)·title·body(md)·category(도메인 렌즈)·doc_ids_hash. 인과 서브그래프는 entity_relations의 narrative_id로 연결 (D-023) |
| `raw_documents` | 264 | 모든 소스의 문서 원본+markdown+media_json. UNIQUE(source_type, source_id) |
| `enrichments` | 문서당 1 | 요약·감성·**time_orientation·reference_period**(시간 정박 D-021)·모델 (content_hash 캐시) |
| `entity_links` | 563 | 문서↔엔티티. confidence 계층: 위키링크 1.0 > LLM 0.9 > 사용자 키워드 0.7 > 정식명 substring 0.6 > 태그 0.5 |
| `signals` | 9 | mention_surge(7일 vs 직전 7일)·high_52w(52주 신고가). payload+interpretation 분리 |
| `entity_digests` | 30 | 종목별 1D/롤링7D 요약+새로운시각. (entity, period, KST날짜) 키로 영구 아카이브 |
| `corporate_actions` | 57 | 시총 5,000억+ 유·무상증자/합병/분할/공개매수/감자 (DART 전시장 스캔+haiku 요약) |
| `capital_raise_details` | 16 | 유무증 Pro: 발행가 1·2차·확정/구주·신주/기준일·권리락(파생)·청약·납입·상장/주관사 |
| `media_analysis` | 31 | 이미지 비전 분류 캐시 (calendar면 → catalysts 적재) |
| `entity_keywords` | 6 | 종목별 사용자 매칭 키워드 (등록 시 소급 링크) |
| `entity_merges` | 병합분 | 어휘 통합 audit+redirect (D-033) — 병합으로 사라진 (old_name, type) → survivor_id. 쓰기 시 재파편화 방지 리다이렉트 겸용 |
| `follows` | 0 | 엔티티 팔로우 (섹터·테마 → 홈 스트림) |
| `observations` / `models` | 0 | 시계열 투영·살아있는 모델 (스키마만 — 무역 커넥터·모델 단계에서 가동) |
| `doc_fts` / `doc_vec` | 264 | BM25(트리거 동기화) / 384d 벡터 |

### 4-2. 도메인 원본 (옛 세계 — 유지, 척추가 읽기 참조)

`companies`(3,975) · `stock_prices`(**711,478** — 전종목 380일 백필+일별) · `financial_statements` ·
`disclosures` · `fundamentals` · `watchlist` · `catalysts` · `consensus` · `telegram_channels` ·
`blog_sources`(+blog_name·author 닉네임) · `industry_groups/members` · `ir_notes` · `business_segments`
(휴면: telegram_messages, blog_posts, blog_post_tags — cutover로 미사용)

### 4-3. 파일 저장
- `media/telegram/` — 첨부 이미지 로컬 보관 (CDN 만료 대비, /media로 서빙)
- `vault/entities/` — 도시에 자동 투영(generated) / `vault/notes/` — 가설 마크다운 원본 (`[[위키링크]]`)
- 전부 gitignore (개인 데이터 보호)

## 5. 백엔드 (FastAPI)

### 5-1. 파이프라인 모듈 (`backend/pipeline/`)
| 모듈 | 역할 |
|---|---|
| `base` / `runner` / `registry` | SourceConnector 프로토콜(discover→fetch) / 실행 / 커넥터 등록(blog·telegram·note) |
| `connectors/telegram` | t.me/s 스크랩 + 이미지 다운로드 (이미지-only 메시지 포함) |
| `connectors/blog` | RSS + 네이버 iframe 본문 (기존 검증 로직 이식) |
| `connectors/notes` | vault/notes → 척추 흡수 |
| `connectors/youtube` | 채널 구독(RSS 신규 영상)·링크 단건 공용 fetch → 자막(ko>en) → **opus 정리본**(digest_transcript, 3회 재시도)을 본문으로 저장. 성공/실패는 `raw_documents.digest_status`(ok\|failed)로 관리(문자열 마커 대신 명시 컬럼). 실패 시 raw 저장되나 discover seen-skip으로 재수집 안 됨 → ① **redigest_youtube 배치**가 `digest_status != 'ok'`인 저장분 스캔해 사후 치유(회차당 5, cron ingest 직후) ② `GET /api/spine/doc/{id}` 열람 시에도 digest_status가 ok가 아니면 그 자리에서 1회 재시도(lazy) — 사용자 진입이 곧 재시도 트리거. 단건/채널 로직 동일 |
| `store` | 멱등 적재(content_hash)·재enrich 시 stale 링크 제거·4층 confidence 링크 |
| `beneficiary` | **수혜 종목 스크린(action_thesis Phase 1, D-035)** — 수혜 섹터/테마 → 종목 후보. MEMBER_OF(KSIC)가 아니라 **문서 공동언급**(entity_links industry/topic ↔ stock, 최근 N일, 문서당 종목수 상한)으로 연결(research_candidates 검증 패턴 재사용) + RS(`_rs_short`)·per·시총·pos_52w(250일 백분위) enrich, RS 내림차순. LLM 0. 후속 Phase에서 업사이드(모델링)·하방(펀더멘탈 지지선)·타이밍(추세)·action_thesis 카드로 확장 |
| `vocab` | **어휘 통합(D-033)** — theme·macro 노드 파편화 치유. 배치: fastembed 코사인 후보(≥0.90) → sonnet 쌍 판정(same/different, 방향·수준 다르면 different) → dry-run 계획(logs/vocab_merge_plan.json) 사람 검토 후 `scripts/consolidate_vocab.py --apply`. 병합: survivor(인과 엣지 多)로 FK 전수 재배선(PRAGMA 동적 발견, entity_relations는 UNIQUE 충돌 시 엣지 병합+evidence 이관) → loser 삭제 + `entity_merges` 기록. 쓰기 시: `_resolve_or_create_node`가 사라진 이름을 entity_merges redirect로 해소(재파편화 방지). cron 미편입(수동) |
| `enrich` | 엔진 선택(claude-code/api/keyword)·구조화 태깅 + **시간 정박**(time_orientation·reference_period, 같은 haiku 콜) — 발행일≠사건일. classify_temporal(백필용 경량 분류). 기존분: scripts/backfill_temporal.py |
| `search` | FTS5+sqlite-vec 하이브리드(RRF)·인덱스 빌드 |
| `signals` | mention_surge·high_52w(200일+ 히스토리 요구)·neglect·consensus_extreme(진자, 감성 90%+ 극단)·volume_spike(60일 평균 3배+ & 등락 3%+ — 급증일 언급 문서 결합)·quadrant_gap(주가×감성 괴리)·theme_surge(주목 주제 — 점유율 상승 화두, 문서유형 라벨 제외) |
| `falsifiers` | 반증 조건 감시(ACH 반증우선) — 지식 active/주입 시 **opus가 '틀렸다는 신호' 2~3개를 구조화**(condition·target_entity·metric·threshold·window)로 생성 → 일일 표적 검색·판정(TRIGGERED, 결정적 로직) → refute 증거 부착 → contested 기계 연동. 본문 150자 미만 문서 판정 제외 |
| `agent_proposals` | **에이전트 제안함(진화계획 3단계 v1, docs/specs/agent-proposals.md)** — 시스템이 그래프·지식 상태를 감시하다 먼저 "조사해볼까요?" 제안. 제안-전용(승인 전 무행동, D-020·D-022 계승). kind 4종: `neglect`(소외 신호→리서치 제안, LLM 0) · `contested_edge`(역방향 CAUSES 쌍, 시점 갈린 나선 제외, LLM 0 — 승인 시 opus 조정: a_wins/b_wins→열세 confidence×0.7, both_temporal→상충 아닌 시점 다른 피드백 나선으로 판정, 두 엣지 confidence 유지하되 feedback_note에 근거 물질화(D-029) → contested 계산서 제외·세계관 뷰 노출) · `devils_advocate`(watchlist thesis 반대 질문, haiku 주 1회) · `falsifier_watch`(corroborated 지식의 미발화 반증 리마인드, LLM 0). `agent_proposals` 테이블(dedup_key 멱등), 홈 ApprovalsCard 통합 노출, POST /agent-proposals/{id}/approve·dismiss. 주 1회 cron(일 07:20) |
| `lenses` | 분석 렌즈(멍거 격자) — docs/references 사고틀(주가 패턴 5축·산업 수요→병목→주가) + **세계관 렌즈**(D-030 렌즈 확장: 패권 전이·지리 제약·화폐 사이클·멱법칙·공유된 허구/반사성·복제자 관점·lollapalooza — 프레임은 관점이지 사실이 아니라는 규율 명시) 압축. 주입: RAG(lens_block)·브리프(LENS_PATTERN)·**내러티브·시나리오(LENS_WORLDVIEW)** |
| `consensus_history` | Fwd EPS·PER·목표주가 일일 스냅샷(네이버 모바일 API, 워치리스트) → consensus_estimates 이력. 축적 후: 분해 v2(revision vs 리레이팅)·quadrant_gap 펀더 축 교체·추정치 반전 신호 |
| `flows` | 수급 이력 — 외인·기관·개인 순매수 30일(네이버 trend API, pykrx는 KRX 로그인 벽) → investor_flows. 브리프 [수급] 재료 |
| `scenario` | 사건 시나리오 엔진 — 대화 "시나리오: <사건>" → 파급 체인(단계별 메커니즘·근거 인용/일반지식 구분·확률)+영향 지도+감시 조건+반대 시나리오(ACH). opus. **인과 물질화(D-028 제3 공급원)**: 같은 콜에 구조화 causal도 산출 → `_persist_causal`(narrative_id=NULL, confidence 상한 0.5 — 가정된 사건이므로 보수적)로 전역 그래프에 적재, 내러티브·문서 추출과 교차검증 |
| `narrative` | 주제 내러티브(theme_surge 고도화) — 질문형 제목·3줄요약·무엇이 다뤄지나·인과 구조·시나리오·종합 해석 (게으른 opus md). **인과 그래프 물질화(Phase 1, D-023)**: 생성 시 구조화 인과(nodes·edges)도 함께 산출 → `narratives` 테이블(버전 보존) + `entity_relations` CAUSES/BENEFITS_FROM 엣지(노드 정규화: 기존 노드 vocab 주입 + 재적재 시 confidence 강화, 뒤의 끝=섹터 종착, DAG+시간 스탬프). **사전 생성**: compute_narratives cron 상위 5. **인과 순회(Phase 2 §2-1)**: `pipeline/narrative_graph.py` — 내러티브 서브그래프 노드를 앵커로 전역 `entity_relations` 그래프를 상류(CAUSES만, 위상적 소스=근본 원인 정지)·하류(CAUSES∪BENEFITS_FROM, sector 노드=수혜 종착)로 BFS, confidence 곱 랭킹 top-3 경로 반환. 방문집합=엣지 id(D-027 반사성 — 시점 다른 두 엣지로 펴진 피드백 나선을 걸을 수 있게, 무한루프는 엣지 유한성+깊이 캡이 방지). **반사성·행위자(D-027)**: 생성 프롬프트가 피드백을 시점 다른 두 엣지로 펴게 지시(플라이휠 추출), 인과의 뿌리·중간에 person/company 행위자 노드 허용('사라지면 약해지는가' 기준, 수혜 종착은 여전히 sector). **메르식 서사(Phase 2 §2-2)**: 순회 top-1 경로(근본원인→수혜)를 opus에 입력으로 줘 하나의 흐르는 서사로 정박(경로 노드 시퀀스 hash로 재생성 가드, `narratives.mer_body`/`mer_path_hash`). **버전 드리프트(Phase 2 §2-3)**: 인과 서브그래프를 (from,to,rel) 노드-이름 정체성으로 직전 버전과 비교(재적재 시 narrative_id 태그가 최신으로 옮겨가므로 태그가 아닌 정체성 비교) — added/removed 노드·엣지(LLM 없음) + 변화가 있으면 게으른 haiku 한 줄 요약(캐시, `narratives.drift_summary`). **머지·교차검증(Phase 2 §2-4)**: `narrative_edge_evidence`(엣지↔내러티브 다대다, 재적재마다 누적)로 몇 개의 독립 내러티브가 한 엣지를 주장했는지 집계(`corroborated_by`, causal 서브그래프에 포함) + 반대 방향 CAUSES 공존 시 `contested` 플래그. 공유 노드 기반 관련 내러티브 랭킹(`related_narratives`, LLM 없음) — 같은 그래프의 다른 서브그래프임을 드러낸다(예: AI·HBM·파운드리가 "AI 데이터센터 투자" 노드로 연결). **내러티브↔지식 루프(Phase 2 §2-5, 핵심)**: `entity_relations.promoted_knowledge_id` — 한 엣지가 2+ 독립 내러티브에서 서로 다른 날 반복 확인되면(`promote_causal_edges`, consolidation.py) opus가 서술형 statement로 승격(승인 큐, review_status='proposed'). 승격된 지식은 기존 recall_for_query(Phase 1부터 이미 배선)로 다음 내러티브 생성에 검증된 전제로 자동 주입되어 루프가 닫힌다. `narrative_grounding`으로 "이 서사가 딛고 선 지식 + 미발화 반증 조건" 조회. 주간 cron(promote_knowledge.py)에 편입. API: /narrative(topic)·/compute·/list·/{id}/causal(서브그래프+교차검증)·/{id}/chain(순회 경로)·/{id}/diff(버전 드리프트)·/{id}/related(공유 내러티브)·/{id}/grounding(딛고 선 지식)·/mer(메르 서사)·/mer/compute·/versions. 프론트: "서사"/"인과 흐름(메르 모드)" 탭 + 드리프트 배지 + 인과 구조 뷰 corroborated_by/contested/승격 배지 + "딛고 선 지식"·"공유 내러티브" 섹션. Phase 2 §5 5단계 전부 구현 완료. **메가 내러티브(D-032)**: `pipeline/mega_narrative.py` — 공유노드 군집(연결요소 3+)마다 상위 세계관 서사(opus, 멤버 (topic,id) 해시 가드, narratives kind='mega' 재사용, cron 편승). GET /narrative/mega. 내러티브 랜딩 최상단 '세계관' 카드 |
| `research_candidates` | 리서치 후보(감지 LLM 0) — RS 상승(단기 RS≥70 & 1주 대비 +8pp↑) ∩ 시총 5000억+ ∩ 화두(theme_surge 테마와 초점 문서 공동언급, 시황글 제외). research_candidates 테이블 proposed 적재. **승인 시에만** stock_brief(opus) 실행→추정치 방향 콜 기록 (비싼 노동을 사람 판단 뒤로, D-020). 신호 탭 '리서치 제안' 섹션 |
| `technicals` | 기술적 위치(LLM 0) — RSI14·이평선 갭(20/60/120)·52주 고점 대비·1/3개월 수익률 + trailing PER 역사 밴드(연간 EPS×주가 범위, 평균회귀 준거). 브리프 재료 |
| `sector_rs` | 산업/섹터 맵(LLM 0) — 대분류 18(sector_map: KSIC 165→LLM 시드)별 장기(11M)·단기(1M) RS 백분위(최신 시총가중 — 과거 행 mcap 부재), 5일 흐름, 1~3주 궤적. /map 4사분면. value_chains(opus 시드 단계·테마)로 밸류체인 뷰 |
| `feature_days` | 종목 특징일(LLM 0 감지) — |등락|3.5%+ 또는 거래량 4배+, 상위 24일. 마커 클릭 시 게으른 haiku 1콜로 그날 원인 조사(±1일 문서, feature_day_notes 캐시) |
| `contradiction` | K2 모순 감지 — 새 문서×active 지식 haiku 대조(일 배치, 예산 40) → refute 축적 → 독립 반박 2+ contested(7일 쿨다운) → 홈 알림 |
| `knowledge` (K3) | 사용자 주입("기억해:" 또는 /knowledge 주입 콘솔, +rationale·source) → knowledge 행(hypothesis·model='user') + 검색 시딩 + 반증 조건 생성(반증우선) → 독립 지지 2+ corroborated / 반례 축적 contested → 홈 '가설 확인' 알림. 내 주입 지식은 삭제 가능(시스템 승격분은 superseded만) |
| `knowledge_state` | salience×conviction (LLM 0) — 시장 주목(주체 엔티티 최근 언급량) × 근거 강도(독립 관측·소스 다양성·느린 층·반박)로 4상태 위치: 주목받지 않은 확신(기회)·주목받는 확신(선반영)·확신 대비 과한 주목(진자 경고)·단순 노이즈. /knowledge 카드 배지 (설계 §G 갭 계량의 축) |
| 기업 프로필(spine_company) | 해외/비상장 기업(종목코드 없음) — 인물 프로필 동형: 언급·공출현·게으른 프로필(source_digests kind='company_profile')·팔로우. /company?name=. 표기 병합(merge_entity_aliases)·enrich 기업 vocab으로 파편화 방지 |
| `vision` | 이미지 분류→증시일정 이벤트→catalysts |
| `actions` / `rights` | 기업활동 스캔·요약 / 유무증 구조화 추출(종속회사 제외) |
| `digests` | 1D/7D 롤링(계층 요약)·새로운 시각(이전 요약 대비) |
| `rag` | 검색 top-16→sonnet 종합·출처 인용 강제·갭 분석·승격 지식 블록(K1) — 모델 티어: 태깅/판정=haiku, 대화 RAG=sonnet(지연 민감), 심층 종합(브리프·세계관·시나리오)=opus |
| `consolidation` | K0 공고화 — 주간 승격 배치(4중 검증·릴레이 접기·반박 탐색·statement 병합) → 승인 큐. **인과 엣지 승격(Phase 2 §2-5)**: `promote_causal_edges` — 문서 대신 인과 그래프 재적재(narrative_edge_evidence)가 입력이라는 점만 다르고 동일 규율(독립 관측 2+·시간 분산·병합·반박 탐색) 재사용 |
| `knowledge_recall` | K1 지식 소환 — activation×epistemic 랭킹, 브리프용 1-hop 그래프 확산, RAG용 의미 유사 |
| `dates` / `normalize` | ISO 정규화(KST 버킷) / markitdown(PDF)·HTML 텍스트화 |

### 5-2. API (spine 라우터 11종)
| 엔드포인트 | 기능 |
|---|---|
| `GET /api/spine/home` | 캘린더(내 종목 우선)+왓치리스트·팔로우 delta 스트림+시장 하이라이트 |
| `GET /api/spine/feed` | 통합 피드 — q(하이브리드 검색)·source(telegram·blog·news·article·people·canon·youtube)·stock·industry·topic 필터, published_at DESC. source 세분류: blog=개인블로그(platform≠rss)·news=언론사RSS·article=간행물RSS(pipeline/urls.blog_category)·people=팔로우 인물 언급 문서 |
| `GET /api/spine/doc/{id}` | 문서 디테일 (raw content·이미지·태그·요약). youtube 소스면 digest_status가 ok가 아닐 때 opus 정리본을 그 자리에서 1회 재시도 후 반환(lazy retry) |
| `GET /api/spine/signals` | 신호 (type·days) |
| `POST /api/spine/ask` | RAG 질의응답 (인용+갭 분석) |
| `GET /api/spine/actions` (+`/rights`) | 기업활동 목록+요약 / 유무증 Pro (차액·증자비율 계산 포함) |
| `GET /api/spine/digests` | 종목 1D/7D 요약 아카이브 |
| `GET /api/spine/narrative` (+`/compute`·`/list`·`/{id}/causal`·`/{id}/chain`·`/{id}/diff`·`/{id}/related`·`/{id}/grounding`·`/mer`·`/mer/compute`·`/versions`) | 주제 내러티브 캐시+stale(category·version) / opus 생성(멱등) / 모음 / 인과 서브그래프(교차검증 포함) / 순회 경로(근본원인→수혜, LLM 없음) / 직전 버전 대비 드리프트(결정적 diff+게으른 haiku 요약) / 공유 노드 기반 관련 내러티브(LLM 없음) / 딛고 선 승격 지식+반증 조건(LLM 없음) / 메르식 서사 캐시+stale / 메르 서사 opus 생성(멱등) / 버전 목록 |
| `POST·GET·DELETE /api/spine/knowledge` (+`/items`·`/overview`·`/items/{id}/evidence·approve·reject`·`/worldview`) | 지식 주입(+rationale·source, 반증조건 생성) / 지식 목록(salience·conviction·quadrant·근거해부·반증조건) / 현황 카운트 / 근거사슬 / 승격 승인·거부 / 내 주입 삭제(user 한정) / 세계관 브리핑 |
| `GET /api/spine/research/candidates` (+`/{id}/approve`·`/dismiss`) | 리서치 제안 목록(LLM 0) / 승인→stock_brief(opus)·추정치 방향 콜 / 기각 |
| `GET /api/spine/beneficiary/screen?sector=` | 수혜 섹터/테마 → 종목 후보(문서 공동언급+RS·밸류·52주위치, LLM 0, D-035). 세계관 뷰 sector/theme 노드 상세 패널에 "수혜 후보 종목" |
| `GET /api/spine/causal/worldview` (+`/node/{id}/narratives`) | 세계관 뷰 — narrative_id 스코프 없는 전역 인과 그래프(노드·엣지+연결요소 cluster_id, union-find) + **플라이휠 감지**(CAUSES 방향 그래프의 크기 2+ SCC = 자기강화 루프, in_flywheel/flywheel 플래그 — D-027 반사성) + **노드 중력**(pace_layer — event~regime, 프론트에서 layer별 크기·강조, D-030), category 필터(도메인 렌즈) / 노드가 등장하는 내러티브. 전부 LLM 없음(docs/specs/causal-worldview.md). 순회 루트 정지도 layer 기반 정밀화 — regime/structure 도달 시 근본 원인으로 정지 |
| `GET·POST·DELETE /api/spine/follows` | 엔티티 팔로우 |
| `GET·POST·DELETE /api/spine/keywords` | 매칭 키워드 (등록 시 소급 링크) |
| `POST /api/spine/sources/telegram·blog·youtube` | 소스 등록 (실검증→저장→백그라운드 첫 수집). youtube=영상 링크 단건 또는 채널 @handle/URL 구독 |

기존 라우터(companies·financials·disclosures·stock_prices·watchlist·screener 등 17종)는 종목 디테일·리서치노트·스크리너가 계속 사용.

### 5-3. 스크립트 (`scripts/`)
시딩: `seed_companies`(DART) · `seed_entities`(그래프) · `seed_sectors`(FDR KSIC)
운영: **`run_chain.sh`**(30분 cron 체인 래퍼 — mkdir+PID 락으로 겹침 방지, 이전 실행 진행 중이면 skip, D-024)가 순서대로 실행: `ingest` · `redigest_youtube`(자막 raw로 굳은 유튜브 문서 opus 재요약 치유, 회차당 5) · `compute_signals` · `compute_narratives`(트리거 2종: theme_surge 상위 5 + **커버리지** — 30일 문서 30건+ & 내러티브 부재/7일+ 오래됨, 사이클당 +2 순환, 문서유형 라벨 제외, D-028) · `extract_events` · `scan_actions` · `compute_digests` · `vault_sync` · `build_search_index`. 별도 cron: `ingest_prices`(평일 16:10) · `promote_knowledge`(주 1회 일 07:00) · `scan_contradictions`(매일 06:45 — compute_signals 끝에도 편승하나 ran_today 가드로 일 1회 보장)
1회성: `backfill_enrich` · **`backfill_enrich_batch`**(keyword 폴백 배치 재태깅 — 문서 10건/콜 sonnet, D-028 레버 1 · 2026-07-19 완료: 1,514건 전량) · `backfill_temporal` · `backfill_pace_layer`(기존 인과 노드 layer 분류 — 40개/콜 haiku, D-030 · 2026-07-19 완료: 838노드) · `migrate_narratives`(source_digests→narratives 이관, D-023)
수동 배치: **`extract_doc_causal`**(문서 레벨 인과 추출 — LLM 태깅 완료+본문 1,200자+ 문서에서 sonnet이 명시 인과만 추출, source_doc_id·narrative_id=NULL·confidence 상한 0.5, 내러티브와 독립된 제2 인과 공급원 = 교차검증 부트스트랩. cron 편입은 체인 런타임 최적화 후 재논의 — D-028 레버 3, docs/specs/doc-causal-extraction.md) · **`ingest_canon`**(역사(canon) 지식층, D-030 — UI 라벨 '역사', source_type=canon 유지 — `vault/canon/*.md`(사람+Claude 작성 통사 노트, 원저 통째 수집 금지) → source_type='canon' 흡수 → opus가 역사 인과 추출: epistemic_type='observed'(신규 중간 티어 — 널리 수용된 역사 해석), confidence 상한 0.85, 역사적 reference_period(2001~). 그래프의 시간 지평을 과거로 확장 — 파일럿: 미중 패권 25년사 54엣지, '세계질서 재편' 뿌리 접합 검증)

## 6. 프론트엔드 (React 19 + shadcn + TanStack Query)

### IA (내비게이션)
```
홈(/home)          내 종목·팔로우 delta 스트림 + 이번주 캘린더 + 시장 하이라이트 (빈화면 방지 승격)
탐색               신호(/explore 착륙: 언급 모멘텀·주목 주제(theme_surge)·**내러티브 티저**(상위 3개, 전체는 월드모델)·백테스트, 그 외 소외·52주신고가·컨센서스극단 목록) ·
                   인물(/people: 디렉토리 — 언급량·최근발언·파급종목 → /person 도시에) ·
                   기업활동(/actions: 목록+요약 | 유무증 Pro 토글+방식 필터) · 산업군 · 스크리너 · 대안데이터
월드모델           내러티브(빠른 층)·세계관(인과 그래프)·지식(느린 층)을 한 모드로 묶음 — "같은 인과 그래프의 두 속도"(D-023), 신호(델타 감지)와 성격이 달라 분리(D-031). 서브탭:
                   내러티브(/narrative: topic 없이 진입=목록 랜딩, /narrative?topic=X=상세 서사·인과 구조·메르 모드) ·
                   **세계관**(/narrative/worldview: narrative_id 스코프 없는 전역 인과 그래프 노드-링크 시각화 — React Flow+dagre 좌→우 배치, 도메인 렌즈 필터, 노드/엣지 클릭 시 Sheet 디테일. docs/specs/causal-worldview.md) ·
                   지식(/knowledge: 3섹션 — 구조 지도(학습)·현황 대시보드(카운트·승격대기 큐·세계관·지식 리스트 salience×conviction 배지·근거사슬·반증조건)·지식 주입 콘솔(주입+근거/출처+삭제))
피드(/feed)        통합 피드 — 탭: 전체·텔레그램·블로그·유튜브·뉴스·아티클·인물·역사(source_type=canon) (최신순), 의미 검색창, 칩 클릭=필터, 전문 보기, 이미지, 채널명 표시
                   + 사이드바: 구독 채널/블로그 목록·닉네임·활성 토글·인라인 등록 폼
문서(/doc/:id)     수집 원문·이미지 내부 열람 (외부 원문은 보조 버튼)
분석(/analyze/:code) 요약·재무·밸류·사업·공시 (기존) + 언급 탭(1D/7D 다이제스트 2열·
                   새로운시각·매칭 키워드 관리·신호 이력·언급 문서)
VS 비교 · 리서치노트(워치리스트/투자메모/카탈리스트)
```

### 공통 시스템
- **디자인 시스템: docs/DESIGN_SYSTEM.md** — 레이아웃 컨트랙트(셸 `--layout-shell` 1440px + 전 페이지 `shared/PageContainer`), 토큰 카탈로그, 패턴별 지정 구현(ToggleGroup/Collapsible/Command…), grandfathered 예외 목록
- 디자인 토큰: Apple HIG light/dark (next-themes 토글), 도메인 토큰 `--color-up/down`(상승빨강/하락파랑)·`--color-fact/hypothesis`, 레이아웃 `--layout-shell`·`--shell-offset`
- shared 컴포넌트: PageContainer(페이지 컨테이너)·SignalCard(확장형 카드 시스템)·DocumentCard·EntityChip(저신뢰 흐림)·SourceBadge·EpistemicBadge류·FreshnessStamp·ThemeToggle·SegmentTabs/PeriodToggle/YearToggle/FilterChips(전부 Radix ToggleGroup 기반)
- Query 정책: queryKey factory(spineKeys)·staleTime 1~5분·keepPreviousData·URL=queryKey
- `npm run build`(tsc -b + vite) 완전 통과 유지

## 7. 실행·운영

```bash
# 서버
cd backend && ../.venv/bin/uvicorn main:app --reload --port 8000
cd frontend && npm run dev            # http://localhost:5173

# 자동화 (등록됨 — 별도 조작 불필요)
crontab -l                            # 30분 체인 + 평일 16:10 주가
tail -f logs/ingest.log               # 수집 관찰
```
`.env`: `DART_API_KEY` · `ENRICH_ENGINE=claude-code` · `CLAUDE_BIN` (+선택: VAULT_PATH, MEDIA_PATH, RAG_MODEL, ANTHROPIC_API_KEY)

## 8. 알려진 한계 / 대기 / 다음 단계

| 항목 | 상태 |
|---|---|
| 무역(관세청) 커넥터 — 수출입→observations→수출변화 신호 | **관세청 API 키 대기** |
| WR·유증매수가 (유무증 Pro) | 신주인수권증서 시세 소스 필요 (v2) |
| 권리락 공휴일 보정 / 권리락은 파생값(기준일-1거래일) | 근사 (공휴일 캘린더 미반영) |
| 텔레그램: 공개 채널만, 최근 ~20개 창 | Telethon(로그인) 도입 시 비공개·과거분 가능 |
| 동명 기업 32건(구법인) 병합 / KSIC vs 키워드 sector 어휘 이중화 | 정리 대상 |
| observations·models 미가동 | 무역 커넥터·살아있는 모델 단계에서 |
| AWS 배포 (24/7 — 맥 꺼지면 수집 중단) | 설계 논의됨 (EC2+SQLite 리프트&시프트) |
| Phase 3 자율 리서치 에이전트 | 가설만 (설계 보류 중) |
