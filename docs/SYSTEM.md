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
ingest(수집→enrich→그래프) → redigest_youtube(자막 raw 치유) → extract_doc_causal(문서레벨 인과 엣지, 회당 10, D-088) → compute_signals → compute_narratives → extract_events(이미지 비전)
  → scan_actions(기업활동) → compute_digests(1D 오늘+1W 이번 주) → vault_sync --export → build_search_index
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
| 1D/1W/1M 다이제스트 + 새로운 시각 (캘린더 기준, D-085) | haiku | 문서 집합 변경 시만 | doc_ids_hash |
| RAG 질의응답 + 갭 분석 | **sonnet** (RAG_MODEL) | 사용자 질문 시 | — |
| 임베딩 (검색) | 로컬 fastembed (다국어 MiniLM 384d) | 문서당 1회 | doc_vec |

## 4. 데이터 계층 (테이블 카탈로그)

### 4-1. 그래프 척추 (greenfield — 단일 진실원천, 현재 행수)

| 테이블 | 행수 | 역할 |
|---|---|---|
| `entities` | 4,135+ | 노드: company·sector·theme·person + **macro·policy·event**(인과 그래프 노드, D-023 활성화) |
| `entity_relations` | 2,760+ | 엣지: MEMBER_OF(기업→섹터, fact) + **CAUSES·BENEFITS_FROM**(인과, hypothesis — 내러티브 산출). epistemic_type·confidence(이 인과가 참이라는 **확신**만, D-065)·**effect_strength**(효과 크기 범주형 3단계 weak/moderate/strong+unknown, D-066)·**effect_direction**(positive/negative/mixed — 확신과 분리된 별개 축, D-065)·valid_from/to + mechanism·reference_period·time_orientation·narrative_id(D-023) + feedback_note(both_temporal 해소 근거 — non-null이면 상충 아닌 시점 다른 피드백 나선, contested 계산서 제외, D-029) + geo_scope(인과 주장의 장소 스코프 — 통제어휘 한국·미국·중국·유럽·일본·대만·글로벌·기타, reference_period와 대칭, backfill_geo_scope.py, D-034) + **obs_confirmed_at·obs_confirmed_qid**(관측→엣지 환류 D-087 — 딛고 선 추적 질문이 confirm=leaning_yes+aligned 도달 시 '실데이터로 확인됨' 주석. **confidence와 별개 축**[축 분리 D-022/D-065], 성긴 매핑이라 blunt 수학 대신 가시 주석) |
| `narratives` | 버전별 | 내러티브 1급 객체 — topic별 version 보존(supersede, 드리프트 추적)·title·body(md)·category(도메인 렌즈)·doc_ids_hash. 인과 서브그래프는 entity_relations의 narrative_id로 연결 (D-023) |
| `raw_documents` | 264 | 모든 소스의 문서 원본+markdown+media_json. UNIQUE(source_type, source_id) |
| `enrichments` | 문서당 1 | 요약·감성·**time_orientation·reference_period**(시간 정박 D-021)·모델 (content_hash 캐시) |
| `entity_links` | 563 | 문서↔엔티티. confidence 계층: 위키링크 1.0 > LLM 0.9 > 사용자 키워드 0.7 > 정식명 substring 0.6 > 태그 0.5 |
| `signals` | 9 | mention_surge(7일 vs 직전 7일)·high_52w(52주 신고가). payload+interpretation 분리 |
| `entity_digests` | 30 | 종목별 **1D(오늘)·1W(월~일 주)·1M(월)** 요약+새로운시각 — 캘린더 기준(비롤링, D-085). (entity, period, period_start[1d=당일·1w=월요일·1m=1일]) 키로 영구 아카이브 |
| `corporate_actions` | 57 | 시총 5,000억+ 유·무상증자/합병/분할/공개매수/감자 (DART 전시장 스캔+haiku 요약) |
| `capital_raise_details` | 16 | 유무증 Pro: 발행가 1·2차·확정/구주·신주/기준일·권리락(파생)·청약·납입·상장/주관사 |
| `media_analysis` | 31 | 이미지 비전 분류 캐시 (calendar면 → catalysts 적재) |
| `entity_keywords` | 6 | 종목별 사용자 매칭 키워드 (등록 시 소급 링크) |
| `entity_merges` | 병합분 | 어휘 통합 audit+redirect (D-033) — 병합으로 사라진 (old_name, type) → survivor_id. 쓰기 시 재파편화 방지 리다이렉트 겸용 |
| `follows` | 0 | 엔티티 팔로우 (섹터·테마 → 홈 스트림) |
| `saved_items` | 북마크 | **저장됨(D-078, docs/specs/saved-items.md)** — 산출물 북마크. kind(company·doc·narrative·report)·ref(안정 식별자; 내러티브·리포트는 **버전 행 PK**=보던 버전 고정)·url·title/subtitle 스냅샷·note(한 줄). UNIQUE(kind, ref)로 토글 멱등. 팔로우(엔티티 흐름 구독)와 성격이 다른 아티팩트 다시-찾기 |
| `observations` / `models` | 활성/0 | 시계열 투영·살아있는 모델. **observations 가동(D-069)**: 질문 트래커의 numeric 프록시 관측이 `entity_id·metric·value`로 투영(source='proxy:transcript', transcript_follow.entity_id 경유). models는 여전히 스키마만 |
| `scenarios` | topic별 | 파급 시나리오 캐시(D-038) — topic PK·answer·beneficiaries(json)·citations(json)·narrative_version(변동 시 stale) + **`question_id`(D-070 질문=허브: Q5 시나리오를 질문에 묶음, NULL=내러티브발)**. 매 클릭 opus 재생성 방지, '다시 분석'(refresh)으로만 갱신 |
| `reports` | 버전별 | 통합 리포트 **append-only 히스토리**(D-047) — id PK·anchor_topic·title·body(Top-down md)·members_json·stocks_json·debate_json·members_hash·**top_pick**·created_at. 최신=id DESC, 매 생성이 새 버전(덮어쓰기 폐기, 과거 열람 가능) |
| `doc_fts` / `doc_vec` | 264 | BM25(트리거 동기화) / 384d 벡터 |
| `feature_flags` / `job_runs` | 운영 | cron 작업 on/off 플래그 / 실행 로그(상태·요약·소요) — 관리자 페이지(D-055) |
| `market_indicators` | 일별 | **시장 국면 스냅샷(D-076)** — F&G·VIX·KOSPI·VKOSPI(폴백 실현변동성) 원지표 시계열. (snapshot_date, indicator) PK. 파생(RSI14·**오실레이터의 20EMA**·vol·기울기)·포스처 결합은 읽을 때 결정적 계산(LLM 0). 지표=fact |
| `thesis_audits` | 감사별 | **논지 감사(D-078, docs/specs/thesis-audit.md)** — thesis를 인과그래프에 대질한 read-only 감사 결과 append-only 히스토리(thesis_text·result_json·created_at). **사용자 주장은 여기 저장될 뿐 인과그래프엔 안 써진다(격리)** — 등재는 별도·승인 |
| `lens_readings` | 판독별 | **투자 렌즈 판독(D-090, docs/specs/investor-lens.md)** — 원칙 원장(`vault/principles/{value,trend}.md`)에 비춘 종목 판단. lens_type(value\|trend)·body(md)·stance(가치=강\|중\|약)·signals(역추적 근거)·**principles_hash·material_hash**(원칙 수정·재료 변경 시 게으른 재생성 가드)·append-only 히스토리. 프레임(hypothesis)이지 판정 아님. **가치·추세 렌즈 KR 구현** — 4상한(가치확신×추세위치)은 두 stance로 결정적 계산(별도 저장 안 함) |
| `transcript_follow` / `transcripts` / `proxy_registry` / `proxy_observations` | transcript(D-061) | 미국 기업 컨콜 팔로우(**35종 시드**, D-075 확대: AI 반도체 공급망 MU·TSM·ASML·semicap + AI DC 물리인프라 VRT·ETN·GEV + SW)+얇은 인덱스(raw_doc_id FK·**digest**=LLM 핵심 정리) / 프록시 레지스트리(사람 세팅 + **질문 트래커가 자동 생성**, D-067)·관측치(값·방향 시계열). proxy_registry에 `sub_question_id`(어느 서브질문의 프록시)·`modality`(numeric\|sentiment\|stance, pace layer)·`yes_direction`(판정 극성) 추가, proxy_observations에 범용 `source_ref`(source_type·source_id, transcript 전용 FK 탈피) 추가. 전문은 raw_documents(source_type='transcript'), 인과·임베딩은 기존 파이프라인 경유. **수집 효율**: `transcript_probe`(빈응답 네거티브 캐시 — 커버리지 공백·미보고를 쿨다운 45일 재요청 안 함, D-081)·`transcript_calendar`(yfinance 발표일 캐시, 무료·AV 예산 무관 — **UI 표시·발표일 참고용**, D-084: 게이트 폐지). ASML·TSM은 AV 미커버라 active=0 |
| `questions` / `sub_questions` | 질문 트래커(D-067·D-068) | **핵심질문 = 지식의 미결층** (+`last_viewed_at`: 관측 비용 활성 게이트, D-072)(판정되면 knowledge 승격). 분할정복: 질문→서브질문(반증조건 보유)→프록시→관측→판정. questions: narrative_id(도출 출처)·source_doc_id(Q5 단일소스)·created_by(system\|user\|**thesis**[논지 승격 D-080]\|**digest**[다이제스트 언섬 D-086])·**lead_verdict/confirm_verdict/divergence**(pace layer 2층 판정 — 선행 fast·확정 slow·괴리, D-068)·verdict_summary(게으른 LLM 한 줄)·conviction·salience. 생성자: ①자동도출(내러티브, 제안 큐) ②사용자주입(자동분해+편집) ③논지 승격(D-080) ④다이제스트 insight(D-086, 제안 큐) |
| `question_reports` | 질문 종합(D-093) | **현재 결산 리포트** append-only — 서브질문·2층 판정·프록시 관측·narrative_grounding을 sonnet으로 종합한 "지금 답할 수 있는 것". inputs_hash(판정·관측 스냅샷)로 게으른 재생성 가드 → 재료 바뀔 때만 리포트→시나리오 체인 재실행. 시나리오는 기존 `scenarios`(question_id)에 체인 저장 |
| `trade_follow` / `trade_stats` / `trade_beneficiaries` | 무역(D-064) | 수출입 팔로우 품목(11종 시드, HS 6단위 위주)+월별 수출/수입/무역수지 시계열(관세청)+관련 종목(LLM 파급 논리 지목 캐시, resolve_and_enrich·유니버스 태그) |

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
| `transcript` | **미국 기업 실적 컨콜(D-061, docs/specs/transcript-follow.md)** — provider-추상 어댑터(Alpha Vantage EARNINGS_CALL_TRANSCRIPT 무료 25/day 채택, FMP는 유료라 402·폴백). 화자별 세그먼트를 라벨 보존 마크다운으로 → `raw_documents(source_type='transcript')` 적재 → 기존 enrich→doc_causal(온톨로지)→digests→doc_vec가 자동 인수(사일로 아님, 컨콜=경영진 1차 발언 고신호 인과원). dates 엔드포인트 없어 **AV가 회계분기로 라벨링**(6월 결산 MSFT의 회계 Q4=`2026Q4`)하므로 list_available/`_recent_quarters`는 **차년 Q1부터 넓게** 후보 생성(회계연도-선행·회계 Q4 커버, D-084). **핵심 정리(digest_one, sonnet)**: 원문은 두고 별도 구조화 정리(실적·가이던스·코멘트·리스크)를 transcripts.digest에 저장(수집 후 digest_pending + 상세 열람 시 POST compute). **Q&A는 상세 정리**(`### Q&A 핵심` — 애널리스트 질문·경영진 답변 문답별, D-084). **call_date=실제 발표일**(AV 미제공 → yfinance 결산월+분기말+실적일로 회계분기↔날짜 매핑 `backfill_call_dates`, published_at도 동기화; 기존 분기근사 `YYYY-분기*3-01` 교정, D-084). 수집은 **분기-랭크 라운드로빈**(collect_roundrobin — AV 25/day·5/min 대응 요청예산+슬립, 저장분 스킵으로 재실행 시 backlog 이어짐). **수집 즉시 온톨로지 편입(D-089)**: `_store_call`이 store_document(enrich 인라인) 직후 그 건에 `doc_causal.extract_for_doc`를 바로 실행 — cron 대기 없이 컨콜(고신호 인과원)이 즉시 인과 엣지로. 실패는 무시(cron 배치가 후속 치유). scripts/collect_transcripts.py=관리자 잡 `collect_transcripts`(`--dry-run`=예산 없이 요청 계획만). **수집 낭비 차단**: 빈응답 네거티브 캐시(transcript_probe, cooldown 45일, D-081) + AV 미커버(ASML·TSM) active=0. (D-084: D-081의 캘린더 게이트는 AV=회계분기 라벨과 어긋나 회계연도 다른 종목을 false-skip → 폐지, 캘린더는 UI용). **프록시(stage 4)**: proxy_registry(사람 세팅, 기본 시드=하이퍼스케일러 CAPEX·AI DC 수요) × 관련 티커 transcript → haiku 추출(extract_proxies, 멱등)로 값·방향을 proxy_observations 시계열 적재. **stage 1~4 구현** — 리포트 핵심질문(D-049)의 관찰 프록시를 실데이터로 |
| `trade` | **수출입 무역통계(D-064, docs/specs/trade-follow.md)** — 관세청 품목별 수출입실적(공공데이터포털, End Point `/1220000/Itemtrade/getItemtradeList`, XML, `.env` DATA_GO_KR_KEY). 조회기간 1년 제한→연 단위 분할, hsSgn 2·4·6단위 조회 시 10단위 세부행을 기간별 합산. **관련 종목**=compute_beneficiaries(sonnet 파급 논리 지목→resolve_and_enrich, D-036, trade_beneficiaries 캐시). scripts/collect_trade.py=관리자 잡 `collect_trade`(월 1회). stage 1~3 구현 |
| `beneficiary` | **수혜 종목 스크린(action_thesis Phase 1·1.5, D-035)** — 수혜 섹터/테마 → 종목 후보. MEMBER_OF(KSIC)가 아니라 **문서 공동언급**(entity_links industry/topic ↔ stock)으로 연결 + RS·per·시총·pos_52w enrich, RS순. **정밀도(1.5)**: 공동언급 2+ & **관련도(co/전체언급) ≥ 0.3** — 편재 대형주(모든 시황 등장) 배제, 테마 집중 종목만. + `graph_activity`(entity_relations.created_at 델타 = 최근 새 엣지 붙은 인과 노드, 섹터/테마면 수혜 top3). + `resolve_and_enrich`(scenario가 논리로 지목한 종목명 → 종목코드 resolve[company 엔티티/companies] + RS·밸류 enrich + `universe_membership` 크로스체크 태그[in_universe·universe_groups], 통합 체인 D-036·유니버스 큐레이션). LLM 0. **산업 맵 유니버스**(D-037): `industries` 라우터에 그룹 생성(`POST /api/industries/`)·기계 후보 제안(`GET /{id}/propose` = screen_beneficiaries 재사용, 기존 멤버 제외)·멤버 승인 적재(기존 `POST /{id}/members`) — 기계 제안·사람 필터로 산업 맵(industry_groups/members, 밸류체인 category)을 담당 유니버스로 큐레이션. 크로스체크는 태그일 뿐 하드 필터 아님(D-036 유지). + `upside_model`(업사이드 모델 Phase 2): 앵커(재무·EPS·PER·주가) 결정적 수집 → opus 4단계(매출 P×Q·Capa·TAM→이익률→EPS→적정주가, 불확실 시 멀티플 리레이팅)로 시나리오 보수/기본/낙관 **범위+조건부**·하방(펀더멘탈 지지선)·무효화 → `models` 테이블 적재(감사·재현). 후속: 타이밍(추세)·action_thesis 카드 |
| `questions` | **핵심질문 트래커(D-067·D-068·D-069, docs/specs/question-proxy.md)** — `decompose_question`(질문→서브질문·프록시 분해, sonnet)·`rollup`(프록시 관측을 pace layer 2층으로 **결정적** 롤업 — 선행 lead[sentiment·stance]/확정 confirm[numeric]/divergence, 판정 변할 때만 haiku 한 줄 `verdict_summary`; **confirm=leaning_yes+aligned 진입 시 딛고 선 내러티브 엣지에 관측 확증 주석 `_confirm_edges`, D-087 환류, 멱등 가드 edge_confirmed**)·`get_tree`·`list_questions`. 프록시의 `yes_direction`으로 관측 방향→'예/아니오' 극성 매핑. **생성자 2개**: ②`decompose_question`(사용자 주입, 즉시 분해) · ①`propose_from_narratives`(지배 내러티브[인과엣지 多]의 질문형 제목을 제안 큐로, 분해는 `approve_question` 승인 뒤 — 비싼 노동 뒤로 D-020) · ④**`propose_from_digests`(다이제스트 언섬 D-086 — 워치리스트 기업 1W/1M 다이제스트 '새로운 시각'을 haiku로 질문형 변환→제안 큐, insight_proposed 플래그 dedup·budget 상한, refresh_questions cron 편승)**. **관측 추출(event-driven, 고정 폴러 없음)**: numeric=`transcript.extract_proxies`(컨콜, 회당 40 상한) · sentiment=`extract_sentiment_proxies`(코퍼스 하이브리드 검색→haiku, 하루 1회 멱등, D-069). **비용 가드(D-072)**: sentiment cron 경로는 ①활성 질문만(최근 14일 내 조회/생성 — `last_viewed_at`, dormant 일시정지) ②회당 예산 상한(기본 20)·가장 오래 안 본 프록시 우선(라운드로빈) → 일일 비용이 질문 수와 무관하게 천장 고정. stance는 Phase 3(person 감성 시계열 선결) |
| `question_report` | **질문 종합(D-093)** — 분할정복 근거로 '현재 결산 리포트'를 뽑고 그걸 출발 조건으로 파급 시나리오를 체인. `_gather`(판정·서브질문 verdict·프록시 최신 관측·narrative_grounding, LLM 0)·`compute_synthesis`(리포트 sonnet → `run_scenario_for_event(report_context=)` opus 체인, inputs_hash 캐시 가드)·`synthesis_status`(캐시+stale). 리포트=근거 정박 현재 결산(미판정 정직), 시나리오=그 위 가정형 전방 — 에피스테믹 분리. 통합 리포트(D-041 opus 애널리스트팀)와 다른 경량 결산 |
| `sector` | **섹터 집약(D-074 Phase 1, docs/specs/sector-aggregation.md)** — `sector_narratives(group_id)`: 유니버스 그룹(=섹터 커버리지 단위)을 '건드리는' 내러티브 집약(LLM 0). 섹터=소유 아니라 **집약 뷰(N:M)** — 한 내러티브가 여러 섹터에 등장. 매핑: 그룹 멤버 종목이 언급된 문서 ∩ 내러티브 topic 엔티티 공동언급(co_docs)·문서유형 라벨(THEME_STOPWORDS) 제외·내러티브 id 중복제거. API `GET /api/industries/{id}/narratives`. FE: 유니버스 페이지 '이 섹터의 내러티브' 섹션. 실측: 반도체=반도체·AI·CAPEX·HBM·소부장·파운드리 모임. **N:M 매핑 = 지배 섹터 랭크(D-077 — 구 관련도 co/전체≥0.3 폐기)**: 관련도 임계는 광역 내러티브(AI)를 죽여 1:N을 강제 → **공동언급 co 지배 랭크**(지배도 co_g/최대섹터 co≥0.15 & 상위 top_k=4섹터, co 절대값이라 광역 페널티 없음)로 교체 = AI→반도체·자동차·인터넷 N:M 복원. 유지 필터: ①카테고리(산업/기술 렌즈 없으면 배제 — 금융·지정학·매크로) ②섹터명 홈(바이오·반도체·방산 내러티브는 자기 뷰로, 이름 매칭 — 편재 대형주 상호오염 차단). Phase 2=섹터 리포트(report.build_group_report) |
| `vocab` | **어휘 통합(D-033)** — theme·macro·sector·event 노드 파편화 치유(sector·event 편입 D-062·D-063: `메모리 반도체`=`메모리 반도체 섹터`, `SK하이닉스 나스닥 ADR 상장`=`SK하이닉스 ADR 상장`류. 사건은 판정 프롬프트에 '같은 발생=same/다른 시점·주체·방향=different' 규율 별도). 배치: fastembed 코사인 후보(≥0.90) → sonnet 쌍 판정(same/different, 방향·수준 다르면 different) → dry-run 계획(logs/vocab_merge_plan.json) 사람 검토 후 `scripts/consolidate_vocab.py --apply`. 병합: survivor(인과 엣지 多)로 FK 전수 재배선(PRAGMA 동적 발견, entity_relations는 UNIQUE 충돌 시 엣지 병합+evidence 이관) → loser 삭제 + `entity_merges` 기록. 쓰기 시: `_resolve_or_create_node`가 사라진 이름을 entity_merges redirect로 해소(재파편화 방지). **주간 cron 편입(D-050)**: agent_proposals `vocab_merge` kind — 후보(**타입별** 상위 30, D-062: theme 고코사인 벽이 sector 예산 독식 방지)→sonnet same 판정→홈 승인 큐, 승인 시 `merge_entities` 실행(자동 적용 아님, 사람 승인). 실패(fastembed·엔진 미가용)는 job_runs에 error로 노출(D-062, 예전 silent-0 삼킴 수정) |
| `enrich` | 엔진 선택(claude-code/api/keyword)·구조화 태깅 + **시간 정박**(time_orientation·reference_period, 같은 haiku 콜) — 발행일≠사건일. classify_temporal(백필용 경량 분류). 기존분: scripts/backfill_temporal.py |
| `search` | FTS5+sqlite-vec 하이브리드(RRF)·인덱스 빌드 |
| `signals` | mention_surge·high_52w(200일+ 히스토리 요구)·neglect·consensus_extreme(진자, 감성 90%+ 극단)·volume_spike(60일 평균 3배+ & 등락 3%+ — 급증일 언급 문서 결합)·quadrant_gap(주가×감성 괴리)·theme_surge(주목 주제 — 점유율 상승 화두, 문서유형 라벨 제외) |
| `falsifiers` | 반증 조건 감시(ACH 반증우선) — 지식 active/주입 시 **opus가 '틀렸다는 신호' 2~3개를 구조화**(condition·target_entity·metric·threshold·window)로 생성 → 일일 표적 검색·판정(TRIGGERED, 결정적 로직) → refute 증거 부착 → contested 기계 연동. 본문 150자 미만 문서 판정 제외 |
| `agent_proposals` | **에이전트 제안함(진화계획 3단계 v1, docs/specs/agent-proposals.md)** — 시스템이 그래프·지식 상태를 감시하다 먼저 "조사해볼까요?" 제안. 제안-전용(승인 전 무행동, D-020·D-022 계승). kind 4종: `neglect`(소외 신호→리서치 제안, LLM 0) · `contested_edge`(역방향 CAUSES 쌍, 시점 갈린 나선 제외, LLM 0 — 승인 시 opus 조정: a_wins/b_wins→열세 confidence×0.7, both_temporal→상충 아닌 시점 다른 피드백 나선으로 판정, 두 엣지 confidence 유지하되 feedback_note에 근거 물질화(D-029) → contested 계산서 제외·세계관 뷰 노출) · `devils_advocate`(watchlist thesis 반대 질문, haiku 주 1회) · `falsifier_watch`(corroborated 지식의 미발화 반증 리마인드, LLM 0). `agent_proposals` 테이블(dedup_key 멱등), 홈 ApprovalsCard 통합 노출, POST /agent-proposals/{id}/approve·dismiss. 주 1회 cron(일 07:20) |
| `lenses` | 분석 렌즈(멍거 격자) — docs/references 사고틀(주가 패턴 5축·산업 수요→병목→주가) + **세계관 렌즈**(D-030 렌즈 확장: 패권 전이·지리 제약·화폐 사이클·멱법칙·공유된 허구/반사성·복제자 관점·lollapalooza — 프레임은 관점이지 사실이 아니라는 규율 명시) 압축. 주입: RAG(lens_block)·브리프(LENS_PATTERN)·**내러티브·시나리오(LENS_WORLDVIEW)** |
| `consensus_history` | Fwd EPS·PER·목표주가 일일 스냅샷(네이버 모바일 API, 워치리스트) → consensus_estimates 이력. 축적 후: 분해 v2(revision vs 리레이팅)·quadrant_gap 펀더 축 교체·추정치 반전 신호 |
| `flows` | 수급 이력 — 외인·기관·개인 순매수 30일(네이버 trend API, pykrx는 KRX 로그인 벽) → investor_flows. 브리프 [수급] 재료 |
| `scenario` | 사건 시나리오 엔진 — 대화 "시나리오: <사건>" → 파급 체인(단계별 메커니즘·근거 인용/일반지식 구분·확률)+영향 지도+감시 조건+반대 시나리오(ACH). opus. **인과 물질화(D-028 제3 공급원)**: 같은 콜에 구조화 causal도 산출 → `_persist_causal`(narrative_id=NULL, confidence 상한 0.5 — 가정된 사건이므로 보수적)로 전역 그래프에 적재, 내러티브·문서 추출과 교차검증. **통합 체인(D-036)**: 같은 콜에 `beneficiaries`(파급 **논리**로 지목한 수혜/피해 종목 +이유)도 산출 → `beneficiary.resolve_and_enrich`로 종목코드 resolve+RS·밸류 enrich. 공동언급 스크린과 달리 '아직 회자 안 된 논리상 수혜'를 잡는다(말뭉치 최신편향 탈출). **③→① 편입 고리**: 수혜 종목이 유니버스 밖 '신규 후보'면 프론트에서 바로 유니버스 그룹×밸류체인 단계로 편입(POST industries/members) — 이슈 파급이 안 보던 종목을 담당 커버리지로 승격(D-037 원목적 완성). **캐시(D-038)**: 결과를 `scenarios` 테이블(topic PK + 기반 narrative_version)에 저장 — `GET /scenario`(저장분 즉시, LLM 0)·`POST /scenario/compute`(내러티브 버전 동일하면 저장분 반환, `refresh=1`일 때만 opus 재생성). 내러티브 갱신 시 stale 플래그. upside 캐시와 같은 철학 |
| `report` | **통합 리포트 v2 — 다중 에이전트**(report-v2-agents, D-043; TradingAgents 착안) — 앵커+`related_narratives` 이웃 취합 → 종목 다각도 집계(±scenario 보강 `AUGMENT_CAP`=2) → **애널리스트 팀**(sonnet ×3: 펀더·기술[RS·이동평균20/60/120·볼린저%B → **국면 판정**, 맥락 해석]·수급) → **리서처 debate**(sonnet ×2: Bull vs Bear, Bear가 Bull 반박) → **리드 애널리스트**(opus ×1: debate 판정 → 종목별 **레이팅**[맥락 종합, 기계적 임계 폐기] + **리포트 유형** top_down/bottom_up 선택) → **섹션 작성**(sonnet ×4, **고정 목차 템플릿**·두괄식: top_down=산업/기업/투자포인트/투자전략, bottom_up=기업/시장/투자포인트/투자전략) → 조립(A4 2~3p). 리드 실패해도 기본 top_down 진행(견고). 레이팅 어휘: ≥50 Strong Buy·≥15 Buy·이하 Hold·위험 Sell(단 리드가 맥락 판단, 건강한 조정≠Sell). 산출물(analyst·bull·bear·ratings)은 `reports.debate_json`에 보존(열람). 캐시 members_hash 멱등. 없는 사실 창작 금지. **브리프 재사용(D-045)**: 종목마다 `compute_brief`(게으른 캐시)로 심층 콜을 태워 그 정합적 종합+정량(컨센서스·수급·상승분해·기술)을 컨텍스트에 주입 — 리포트가 종목 분석을 재발명하지 않고 브리프 위에 선다. **렌즈**: `lenses.py`를 애널리스트별로 주입(펀더=산업·기술=패턴·수급=사이클/진자[하워드 막스]). **밸류는 12M Fwd PER + 그 추이(리레이팅/디레이팅)·추정EPS 개정으로만 — trailing PER 배제**(D-046). **Top-pick 집중(D-047)**: 리드가 최고 수혜 종목 1개 선정 → 기업분석·투자포인트·투자전략을 그 종목 중심으로 심화, 피어는 비교. **다우 이론**(고저 구조 HH/HL·거래량·3국면) 기술분석 + **시점 규율**(현재 분기 기준 2H/차년/차차년 수급 경로 구체화, 못 하면 '멀티플로 당겨온 기대'로 판정). 섹션 분량 제한 없이 `###` 소제목 전개. **레이팅 %=상승여력(상방)·비중 아님**, 종목 콜은 **하방 대비 상방(비대칭)**·`downside_pct` 병기(D-048). **핵심 질문+관찰 프록시**(하이퍼스케일러 CAPEX·ARR·자금조달·DC 착공 등)로 논리 출발, 투자 전략 감시 조건에 반영. **핵심 질문=지배 내러티브에서 도출**(`_narrative_power`: 인과엣지·공유노드 신호, D-049) · 최상단 **결론 BLUF**(Top-pick·상방/하방 먼저, 근거는 뒤). **섹터 리포트(D-074 Phase 2)**: `build_group_report(group_id)` — 앵커=유니버스 그룹명, gather를 `sector_narratives`(집약 뷰 top8)+커버리지 종목 시드로 대체하고 compute 코어(`_compute_report`, topic·group 공용)는 공유. topic 1:1 리포트 파편화를 섹터 1개로 봉합 |
| `narrative` | 주제 내러티브(theme_surge 고도화) — 질문형 제목·3줄요약·무엇이 다뤄지나·인과 구조·시나리오·종합 해석 (게으른 opus md). **인과 그래프 물질화(Phase 1, D-023)**: 생성 시 구조화 인과(nodes·edges)도 함께 산출 → `narratives` 테이블(버전 보존) + `entity_relations` CAUSES/BENEFITS_FROM 엣지(노드 정규화: 기존 노드 vocab 주입 + 재적재 시 confidence 강화, 뒤의 끝=섹터 종착, DAG+시간 스탬프). **사전 생성**: compute_narratives cron 상위 5. **인과 순회(Phase 2 §2-1)**: `pipeline/narrative_graph.py` — 내러티브 서브그래프 노드를 앵커로 전역 `entity_relations` 그래프를 상류(CAUSES만, 위상적 소스=근본 원인 정지)·하류(CAUSES∪BENEFITS_FROM, sector 노드=수혜 종착)로 BFS, confidence 곱 랭킹 top-3 경로 반환. 방문집합=엣지 id(D-027 반사성 — 시점 다른 두 엣지로 펴진 피드백 나선을 걸을 수 있게, 무한루프는 엣지 유한성+깊이 캡이 방지). **반사성·행위자(D-027)**: 생성 프롬프트가 피드백을 시점 다른 두 엣지로 펴게 지시(플라이휠 추출), 인과의 뿌리·중간에 person/company 행위자 노드 허용('사라지면 약해지는가' 기준, 수혜 종착은 여전히 sector). **메르식 서사(Phase 2 §2-2)**: 순회 top-1 경로(근본원인→수혜)를 opus에 입력으로 줘 하나의 흐르는 서사로 정박(경로 노드 시퀀스 hash로 재생성 가드, `narratives.mer_body`/`mer_path_hash`). **버전 드리프트(Phase 2 §2-3)**: 인과 서브그래프를 (from,to,rel) 노드-이름 정체성으로 직전 버전과 비교(재적재 시 narrative_id 태그가 최신으로 옮겨가므로 태그가 아닌 정체성 비교) — added/removed 노드·엣지(LLM 없음) + 변화가 있으면 게으른 haiku 한 줄 요약(캐시, `narratives.drift_summary`). **머지·교차검증(Phase 2 §2-4)**: `narrative_edge_evidence`(엣지↔내러티브 다대다, 재적재마다 누적)로 몇 개의 독립 내러티브가 한 엣지를 주장했는지 집계(`corroborated_by`, causal 서브그래프에 포함) + 반대 방향 CAUSES 공존 시 `contested` 플래그. 공유 노드 기반 관련 내러티브 랭킹(`related_narratives`, LLM 없음) — 같은 그래프의 다른 서브그래프임을 드러낸다(예: AI·HBM·파운드리가 "AI 데이터센터 투자" 노드로 연결). **내러티브↔지식 루프(Phase 2 §2-5, 핵심)**: `entity_relations.promoted_knowledge_id` — 한 엣지가 2+ 독립 내러티브에서 서로 다른 날 반복 확인되면(`promote_causal_edges`, consolidation.py) opus가 서술형 statement로 승격(승인 큐, review_status='proposed'). 승격된 지식은 기존 recall_for_query(Phase 1부터 이미 배선)로 다음 내러티브 생성에 검증된 전제로 자동 주입되어 루프가 닫힌다. `narrative_grounding`으로 "이 서사가 딛고 선 지식 + 미발화 반증 조건" 조회. 주간 cron(promote_knowledge.py)에 편입. API: /narrative(topic)·/compute·/list·/{id}/causal(서브그래프+교차검증)·/{id}/chain(순회 경로)·/{id}/diff(버전 드리프트)·/{id}/related(공유 내러티브)·/{id}/grounding(딛고 선 지식)·/mer(메르 서사)·/mer/compute·/versions. 프론트: "서사"/"인과 흐름(메르 모드)" 탭 + 드리프트 배지 + 인과 구조 뷰 corroborated_by/contested/승격/**관측 확증(D-087)** 배지 + **노드 클릭→온톨로지 딥링크**(`/knowledge/ontology?focus=<id>`, causal 서브그래프 엣지가 from_id/to_id 반출) + "딛고 선 지식"·"공유 내러티브" 섹션. Phase 2 §5 5단계 전부 구현 완료. **메가 내러티브(D-032)**: `pipeline/mega_narrative.py` — 공유노드 군집(연결요소 3+)마다 상위 세계관 서사(opus, 멤버 (topic,id) 해시 가드, narratives kind='mega' 재사용, cron 편승). GET /narrative/mega. 내러티브 랜딩 최상단 '세계관' 카드 |
| `research_candidates` | 리서치 후보(감지 LLM 0) — RS 상승(단기 RS≥70 & 1주 대비 +8pp↑) ∩ 시총 5000억+ ∩ 화두(theme_surge 테마와 초점 문서 공동언급, 시황글 제외). research_candidates 테이블 proposed 적재. **승인 시에만** stock_brief(opus) 실행→추정치 방향 콜 기록 (비싼 노동을 사람 판단 뒤로, D-020). 신호 탭 '리서치 제안' 섹션 |
| `technicals` | 기술적 위치(LLM 0) — RSI14·이평선 갭(20/60/120)·52주 고점 대비·1/3개월 수익률 + trailing PER 역사 밴드(연간 EPS×주가 범위, 평균회귀 준거) + **매물대(`volume_by_price` — 가격대별 거래량 히스토그램 → POC·현재가 위 저항/아래 지지 비중, 추세 렌즈 재료 D-090)**. 브리프·렌즈 재료 |
| `market_regime` | **시장 국면(D-076, docs/specs/market-regime.md)** — 매크로 리스크 포스처. 3중 필터(감성 오실레이터 × **그 오실레이터의 20 EMA** 추세 게이트 × 변동성)를 **결정적 결합(LLM 0)**해 비중 포스처(favorable/caution/risk/neutral)+근거 한 줄 산출. **20EMA는 가격이 아니라 오실레이터 자체의 이평**(오실레이터가 바닥서 반등해도 EMA 우하향이면 보류 — 태린이 아빠 규율). `snapshot_market`(yfinance ^VIX·^KS11 + CNN F&G[브라우저 UA 필수] + naver VKOSPI/폴백 실현변동성 → market_indicators 멱등 적재) · `get_regime`(저장분서 RSI·오실레이터 EMA·포스처 계산). 미국=날씨(F&G+F&G의 EMA×VIX)·국장=본판(RSI14+RSI14의 EMA×VKOSPI/vol). 지표=fact, 포스처=frame(귀속 배지 없음). fetch 실패는 degraded로 부분 흡수 |
| `thesis` | **논지 감사(D-078, docs/specs/thesis-audit.md)** — 내 thesis를 축적된 인과그래프에 **대질**(read-only 감사, 등재 아님). moat는 추론이 아니라 정박 — 모든 판정이 코퍼스 근거(엣지·독립 소스·시점) 인용. 5단계 중 Phase 1·2·3 구현: `decompose_thesis`(자유서술→원자 주장+역할+그래프 vocab 앵커, sonnet stage 1) · `ground_claim`(앵커 해소→인과엣지[corroborated_by 독립 내러티브 수·effect_direction·created_at]·내러티브·시간급증 후보검색, LLM 0) · `filter_edges`(후보 엣지 중 주장 관련성+입장 support/contradict/context, haiku stage 2) · `pendulum_for_claim`(**진자 stage 3, LLM 0** — salience×conviction으로 선반영/소외 기회 4상한 판정, `knowledge_state` 재사용: verdict[그래프 일치]와 직교 축, D-079) · `audit_thesis`(주장별 델타 aligned/contested/challenged/novel + pendulum). **승격(stage 4 절반, D-080)**: 감사된 주장을 `POST /questions`로 추적 질문 승격(`decompose_question` 재사용 → 서브질문·반증조건·프록시 스폰, created_by='user' 격리 태그) — 일회성 감사를 살아있는 추적으로. **격리 불변식**: 사용자 주장은 감사만·그래프 무변경(질문도 독립 테이블). 후속: 종합(opus stage 5)·thesis 전용 반증조건 자동생성. 프롬프트는 enrich 패턴(명령형·JSON만) — roleplay 시 에이전트로 샘 |
| `investor_lens` | **투자 렌즈(D-090, docs/specs/investor-lens.md)** — "그래서 좋은 주식인가"에 투자자 관점으로 답. 투자관 = **원칙 원장**(`vault/principles/{value,trend}.md`, 사람 소유·정교화), 렌즈는 그 **원칙 전문을 압축 없이 통째 주입** + 종목 재료(`stock_brief.gather_inputs`·`upside_model`·현금의 질[financial_statements CF]·인과엣지) → sonnet 종합. `load_principles`·`gather_material`·`compute_reading`(게으른 캐시 principles_hash+material_hash·in-flight 락·append-only). **판정 오라클 아님**(hypothesis, 근거 역추적). 가치 렌즈 v3 무게중심=미래 이익·현금흐름 극대화 확신의 설득력(과거 장부는 현금의 질 검증 준거). **추세 렌즈**: 재료=technicals·**매물대(technicals.volume_by_price 신규)**·RS(research_candidates 재사용)·market_regime, 프롬프트는 "시장은 틀리지 않는다·위치 비단정·손절 라인·안티물타기" 원칙 주입. 재료 지문은 원자 가격이 아니라 **질적 추세상태**(부호·존·버킷)라 상태 전환 시에만 재생성(비용 게이트). **4상한 `compute_quadrant`**(가치확신 강·중/약 × 추세위치 초입·진행/성숙·훼손 → 기회/늦은진입/과열경고/회피, LLM 0). 가치·추세 KR 구현 + **US 확장(market 분기, D-091)** — `compute_reading/peek(code, lens_type, market)`, US는 yfinance 재료(`_gather_value_us`=밸류·EPS 개정·현금의 질·컨콜정리 / 추세는 us_prices·`_us_rel_strength`[SPY 대비]·`get_regime().us`), technicals `table` 파라미터로 us_prices 재사용. US 기업은 이미 entity(transcript_follow)라 인과·컨콜 그대로 흐름 |
| `us_data` | **미국 종목 데이터(D-091, docs/specs/us-dossier.md)** — yfinance 캐시. `fetch_prices`(→us_prices EOD OHLCV)·`get_fundamentals`(info·income·cashflow·**애널리스트 추정치**[eps_revisions·eps_trend·earnings_estimate·price_targets] → us_fundamentals 24h)·`resolve_us`(ticker↔entity_id). 팔로우 티커만. yfinance 무료 추정치가 KR consensus_estimates 시계열을 대체 → US 가치 렌즈 완전체(partial 아님) |
| `sector_rs` | 산업/섹터 맵(LLM 0) — 대분류 18(sector_map: KSIC 165→LLM 시드)별 장기(11M)·단기(1M) RS 백분위(최신 시총가중 — 과거 행 mcap 부재), 5일 흐름, 1~3주 궤적. /map 4사분면. value_chains(opus 시드 단계·테마)로 밸류체인 뷰 |
| `feature_days` | 종목 특징일(LLM 0 감지) — |등락|3.5%+ 또는 거래량 4배+, 상위 24일. 마커 클릭 시 게으른 haiku 1콜로 그날 원인 조사(±1일 문서, feature_day_notes 캐시) |
| `contradiction` | K2 모순 감지 — 새 문서×active 지식 haiku 대조(일 배치, 예산 40) → refute 축적 → 독립 반박 2+ contested(7일 쿨다운) → 홈 알림 |
| `knowledge` (K3) | 사용자 주입("기억해:" 또는 /knowledge 주입 콘솔, +rationale·source) → knowledge 행(hypothesis·model='user') + 검색 시딩 + 반증 조건 생성(반증우선) → 독립 지지 2+ corroborated / 반례 축적 contested → 홈 '가설 확인' 알림. 내 주입 지식은 삭제 가능(시스템 승격분은 superseded만) |
| `knowledge_state` | salience×conviction (LLM 0) — 시장 주목(주체 엔티티 최근 언급량) × 근거 강도(독립 관측·소스 다양성·느린 층·반박)로 4상태 위치: 주목받지 않은 확신(기회)·주목받는 확신(선반영)·확신 대비 과한 주목(진자 경고)·단순 노이즈. /knowledge 카드 배지 (설계 §G 갭 계량의 축) |
| 기업 프로필(spine_company) | 해외/비상장 기업(종목코드 없음) — 인물 프로필 동형: 언급·공출현·게으른 프로필(source_digests kind='company_profile')·팔로우. /company?name=. 표기 병합(merge_entity_aliases)·enrich 기업 vocab으로 파편화 방지 |
| `vision` | 이미지 분류→증시일정 이벤트→catalysts |
| `actions` / `rights` | 기업활동 스캔·요약 / 유무증 구조화 추출(종속회사 제외) |
| `digests` | **1D(오늘)·1W(월~일)·1M(월) 캘린더 다이제스트**(D-085) — 각 주기가 자기 캘린더 구간 raw 문서 직접 요약(비롤링). `_compute_bucket` 공용. **`catch_up(stock)`**: 진입 시 소급 — 과거 완결 월 1M·이번 달 주 1W·오늘 1D 멱등 생성(상한 CATCHUP_MONTHS=3). 새로운 시각(이전 같은 주기 요약 대비). cron은 최신(1D+이번 주 1W)만, 과거 월은 진입 catch_up |
| `rag` | 검색 top-16→sonnet 종합·출처 인용 강제·갭 분석·승격 지식 블록(K1) — 모델 티어: 태깅/판정=haiku, 대화 RAG=sonnet(지연 민감), 심층 종합(브리프·세계관·시나리오)=opus |
| `consolidation` | K0 공고화 — 주간 승격 배치(4중 검증·릴레이 접기·반박 탐색·statement 병합) → 승인 큐. **인과 엣지 승격(Phase 2 §2-5)**: `promote_causal_edges` — 문서 대신 인과 그래프 재적재(narrative_edge_evidence)가 입력이라는 점만 다르고 동일 규율(독립 관측 2+·시간 분산·병합·반박 탐색) 재사용 |
| `knowledge_recall` | K1 지식 소환 — activation×epistemic 랭킹, 브리프용 1-hop 그래프 확산, RAG용 의미 유사 |
| `dates` / `normalize` | ISO 정규화(KST 버킷) / markitdown(PDF)·HTML 텍스트화 |

### 5-2. API (spine 라우터 13종)
| 엔드포인트 | 기능 |
|---|---|
| `GET /api/spine/home` · `/home/ai-activity?days=` | 캘린더(내 종목 우선)+왓치리스트·팔로우 delta 스트림+시장 하이라이트 / **AI 자동생성 피드**(D-053, 지난 N일 내러티브·리포트·파급·다이제스트 최신순 통합, LLM 0) — 홈 최상단 AiActivityFeed(구 승인 배너 대체) |
| `GET /api/spine/feed` | 통합 피드 — q(하이브리드 검색)·source(telegram·blog·news·article·people·canon·youtube·transcript)·stock·industry·topic 필터, published_at DESC. source 세분류: blog=개인블로그(platform≠rss)·news=언론사RSS·article=간행물RSS(pipeline/urls.blog_category)·people=팔로우 인물 언급 문서·transcript=미국 컨콜(D-061) |
| `GET /api/spine/trade/*` | **수출입 팔로우(D-064)** — `/follow`(그룹별 품목+최신월·YoY) · `/{hs}`(월별 시계열+관련종목) · POST `/follow`(구독) · POST `/seed`(11품목) · POST `/{hs}/beneficiaries`(관련종목 LLM 지목, ~수 분). FE: /follow/trade 2분할(추이 차트+관련종목) |
| `GET·POST·DELETE /api/spine/questions` (+`/propose`·`/from-doc`·`/scenario`·`/{id}`·`/{id}/rollup`·`/{id}/approve`·`/proxy/{id}`) | **핵심질문 트래커(D-067·D-068·D-069)** — GET `/proxy/{id}`(프록시 디테일 — 메타[무엇을 측정·'예' 방향·하위질문]+전체 관측 시계열+출처 문서, LLM 0; 질문 트리서 프록시 클릭 시 모달, D-083) · POST(질문 주입→자동분해→numeric+sentiment 추출→트리, ~수 분; `created_by` user|thesis[논지 감사 승격, D-082] 화이트리스트) · GET(미결 목록, `narrative_id`·`status` 필터, LLM 0 — conviction·created_by·source_doc_id 포함해 원장 렌즈 서빙) · `/{id}`(트리+2층 판정, LLM 0) · POST `/propose`(지배 내러티브서 질문 후보, 생성자 ①) · POST `/{id}/approve`(제안 승인→분해) · **POST `/from-doc`(Q5 — 단일 소스 문서서 딥다이브 핵심질문 후보 도출, sonnet)** · **POST `/{id}/scenario`(질문=허브 D-070 — 질문에 묶어 파급 시나리오 생성, opus)** · POST `/{id}/rollup` · DELETE(dismiss) · **GET `/{id}/synthesis`(질문 종합 결산 캐시+stale, LLM 0)** · **POST `/{id}/synthesis/compute`(D-093 — 결산 리포트 sonnet → 그걸 출발 조건으로 파급 시나리오 opus 체인, ~수 분)**. `/{id}` 트리는 **묶인 시나리오·소스 문서 포함**(허브) |
| `GET /api/spine/transcript/*` | **Transcript 팔로우(D-061)** — `/follow`(그룹별 팔로우+최신 콜) · `/company/{ticker}`(분기 목록) · `/detail/{id}`(원문+메타+저장 정리+**온톨로지 연결**[언급 노드·이 콜서 추출된 인과 엣지, 노드 클릭→`/knowledge/ontology?focus=id` 딥링크, D-089], 빠름) · POST `/detail/{id}/digest`(멱등 정리 생성 sonnet, ~수 분) · POST `/follow`(구독 토글) · POST `/seed`(기본 35종, D-075) · **`/proxies`**(레지스트리+관측 시계열) · POST `/proxies`(세팅) · POST `/proxies/extract`(추출 트리거 haiku) · **POST `/calendar/refresh`**(yfinance 실적 발표일 갱신, 무료·AV 예산 무관, D-081). `/follow` 응답에 `last/next_report_date` 포함. FE: /follow/transcripts 2분할 브라우저 + 프록시 탭 + **'곧 발표' 실적 캘린더**(발표일 D-day 순 + 팔로우 행 임박 배지, D-081) |
| `GET /api/spine/doc/{id}` | 문서 디테일 (raw content·이미지·태그·요약). youtube 소스면 digest_status가 ok가 아닐 때 opus 정리본을 그 자리에서 1회 재시도 후 반환(lazy retry) |
| `GET /api/spine/signals` | 신호 (type·days) |
| `POST /api/spine/ask` | RAG 질의응답 (인용+갭 분석) |
| `GET·POST·PATCH·DELETE /api/spine/saved` | **저장됨(D-078)** — 산출물 북마크. GET(목록, `?kind=`; 배지·토글·리스트 공용) · POST(`INSERT OR IGNORE` 멱등 토글) · PATCH `/{id}`(메모) · DELETE `/{id}`. FE: 각 페이지 북마크 토글 + 헤더 상시 아이콘(Sheet) + 팔로우 '저장됨' 서브탭(`/follow/saved`) |
| `GET /api/spine/market-regime` · `POST /snapshot` | **시장 국면(D-076)** — 양 시장 리스크 포스처+근거+스파크라인 series(LLM 0, 첫 진입 시 lazy 스냅샷). / EOD 일별 스냅샷 적재(scripts/snapshot_market.py=수동·cron) |
| `POST /api/spine/thesis/audit` · `GET /audits` · `GET /{id}` | **논지 감사(D-078)** — thesis 주입→인과그래프 대질 감사(read-only·연쇄 LLM ~수 분, 저장) / 히스토리 / 저장분 재조회(LLM 0). 격리: 그래프 무변경 |
| `GET /api/spine/stock/{code}/lens?market=` · POST `/lens/compute?type=&market=&refresh=` | **투자 렌즈(D-090·D-091)** — 캐시 판독 번들(value/trend)+**4상한(quadrant)**+stale(LLM 0) / 원칙·재료 변경 시만 생성(sonnet, `type=value\|trend`, `market=kr\|us`, 멱등). 재료·원칙 없는 렌즈는 응답에서 생략 |
| `GET /api/spine/us` · `/briefing` · `/movers` · `/{ticker}` · `/{ticker}/mentions` · `/{ticker}/worldmodel` | **미국 종목(D-091·D-092·D-094·D-095)** — 디렉토리(transcript_follow 그룹별 + 캐시 렌즈 stance·4상한, LLM 0) / **어젯밤 미국장 브리핑(D-095·D-096 — 분위기 파악 가속기, docs/specs/us-briefing.md)**: 거래대금 상위 20을 **섹터 클러스터·쏠림 비중·개별 이슈(급등락·그룹역행·신규진입) — 전부 LLM 0** 으로 읽고, 커버 종목은 내러티브/언급 enrich·미상은 스터디 후보. **그날 시장 담론 주입(D-096)**: 지배 테마 랭킹 + 시장구조 코멘터리 문서(`{수급·매크로}`+주도섹터 링크, 최신순)를 종합에 함께 넣어 **거래대금(무엇)×담론(왜) 교차** — 개별 종목 경로로 못 잡는 시장구조 사건(AI 디레버리징 등)·움직임의 성격(랠리 vs 청산·반등)까지 포착(`market_themes`·`market_docs` 반출, FE 테마칩→/narrative·문서→/doc/:id). **synthesis만 sonnet 1콜·캐시(us_briefings)** = 분위기 산문+스터디/공유 후보(촉매 미상 지어내지 않음), 엔진 미가용이면 null(스켈레톤만). `us_briefing.py`(build_briefing·_gather_discourse). / **거래대금 상위 20(D-094)** — 원천 리스트, TradingView 무키 스크리너 `us_movers.py`, 전 거래소·ADR 포함·ETF 제외, **일별 스냅샷 `us_movers`(sector·industry·change_pct·is_new, 최근 7일 — 신규진입 판정)** + 캐시 1h, status=ok/stale/error로 스키마 붕괴 프론트 노출, `/{ticker}`보다 먼저 선언 / 도시에 헤더(yfinance 시세·밸류 + entity_id + 최근 컨콜 메타) / 여론(entity_links 경유 언급 문서) / **월드모델(이 노드의 인과 엣지 양방향 + 걸린 내러티브, LLM 0 — 온톨로지 딥링크 `/knowledge/ontology?focus=id`)**. 렌즈는 `/lens?market=us` |
| `GET /api/spine/actions` (+`/rights`) | 기업활동 목록+요약 / 유무증 Pro (차액·증자비율 계산 포함) |
| `GET /api/spine/digests?stock=&period=(1d\|1w\|1m)` · `POST /api/spine/digests/catchup?stock=` | 종목 1D/1W/1M 요약 아카이브 조회 / **진입 시 소급 catch-up**(D-085 — 과거 월 1M·이번 달 주 1W·오늘 1D 멱등 생성). 프론트: 종목 진입 시 자동 호출(백그라운드, 세션당 1회) + '지금 업데이트' 버튼. 구 `/compute?period` 폐지 |
| `GET /api/spine/narrative` (+`/compute`·`/list`·`/{id}/causal`·`/{id}/chain`·`/{id}/diff`·`/{id}/related`·`/{id}/grounding`·`/mer`·`/mer/compute`·`/versions`·`/version?id=`) | 주제 내러티브 캐시+stale(category·version) / opus 생성(멱등) / 모음 / 인과 서브그래프(교차검증 포함) / 순회 경로(근본원인→수혜, LLM 없음) / 직전 버전 대비 드리프트(결정적 diff+게으른 haiku 요약) / 공유 노드 기반 관련 내러티브(LLM 없음) / 딛고 선 승격 지식+반증 조건(LLM 없음) / 메르식 서사 캐시+stale / 메르 서사 opus 생성(멱등) / 버전 목록 / **특정 버전 본문 by id**(히스토리 도트 클릭, D-060) |
| `POST·GET·DELETE /api/spine/knowledge` (+`/items`·`/overview`·`/items/{id}/evidence·approve·reject`·`/worldview`) | 지식 주입(+rationale·source, 반증조건 생성) / 지식 목록(salience·conviction·quadrant·근거해부·반증조건) / 현황 카운트 / 근거사슬 / 승격 승인·거부 / 내 주입 삭제(user 한정) / 세계관 브리핑 |
| `GET /api/spine/research/candidates` (+`/{id}/approve`·`/dismiss`) | 리서치 제안 목록(LLM 0) / 승인→stock_brief(opus)·추정치 방향 콜 / 기각 |
| `GET /api/spine/beneficiary/screen?sector=` · `GET /api/spine/causal/activity` · `POST /api/spine/beneficiary/upside?stock=&event=` | 수혜 종목 스크린(공동언급+RS·밸류·관련도 필터, LLM 0) / 인과 그래프 델타(신규·갱신 노드+수혜 top3) / **업사이드 모델**(opus 4단계: 매출→이익→EPS→적정주가 또는 멀티플 리레이팅, 시나리오 보수/기본/낙관 범위+조건부·하방·무효화, `models` **캐시**(저장분 즉시 반환, refresh=1일 때만 opus 재생성), D-035). 세계관 노드 패널·**내러티브(수혜 종목 섹션)**에 노출 — 신호 탭 활동 카드는 내러티브로 연결(이슈=내러티브로 통합) |
| `GET /api/spine/report?topic=`(최신) · `/history?topic=`(버전 목록) · `/version?id=`(과거 버전) · `POST /report/compute?topic=&refresh=` · **`POST /report/compute-group?group_id=`(섹터 리포트, D-074 Phase 2 — 앵커=그룹명, /report?topic=그룹명 열람)** | **통합 리포트**(integrated-report) 조회/히스토리(append-only, D-047) / 생성(연쇄 LLM: 공유 이웃 취합→종목 다각도 재분석 sonnet×M→Top-down opus). 내러티브 인라인 + 리포트 탭(ReportView)에 노출, 과거 버전 열람·Top-pick 강조. **차트(ReportCharts)**: 상방/하방 비대칭 bar(전 종목) + Top-pick 주가·이동평균(MultiLine) + Top-pick 12M Fwd PER 추이(consensus history) |
| `GET /api/consensus/{code}` · `/{code}/history` | 컨센서스 최신 / **fwd_per 시계열**(consensus_estimates 일별 스냅샷, 날짜별 가장 가까운 forward 회계연도 — 리포트 Fwd PER 차트, D-046) |
| `GET /api/spine/causal/worldview` (+`/node/{id}/narratives`) | 세계관 뷰 — narrative_id 스코프 없는 전역 인과 그래프(노드·엣지+연결요소 cluster_id, union-find) + **플라이휠 감지**(CAUSES 방향 그래프의 크기 2+ SCC = 자기강화 루프, in_flywheel/flywheel 플래그 — D-027 반사성) + **노드 중력**(pace_layer — event~regime, 프론트에서 layer별 크기·강조, D-030), category 필터(도메인 렌즈) + **엣지 렌즈 토글**(흐름 뷰: 인식 상태[반박·플라이휠·교차검증 색/굵기] ↔ 효과 흐름[effect_direction 색 정+빨강·부−파랑, effect_strength 굵기], URL `?edges=effect`, D-065·D-066) / 노드가 등장하는 내러티브. 전부 LLM 없음(docs/specs/causal-worldview.md). 순회 루트 정지도 layer 기반 정밀화 — regime/structure 도달 시 근본 원인으로 정지 |
| `GET·POST·DELETE /api/spine/follows` | 엔티티 팔로우 |
| `GET·POST·DELETE /api/spine/keywords` | 매칭 키워드 (등록 시 소급 링크) |
| `POST /api/spine/sources/telegram·blog·youtube` | 소스 등록 (실검증→저장→백그라운드 첫 수집). youtube=영상 링크 단건 또는 채널 @handle/URL 구독 |

기존 라우터(companies·financials·disclosures·stock_prices·watchlist·screener 등 17종)는 종목 디테일·리서치노트·스크리너가 계속 사용.

### 5-3. 스크립트 (`scripts/`)
시딩: `seed_companies`(DART) · `seed_entities`(그래프) · `seed_sectors`(FDR KSIC) · **`seed_universe`**(유니버스 정본 — 11섹터/119종 industry_groups·members, 멱등·비파괴, D-075: 그간 DB에만 있던 유니버스를 git으로 고정)
운영: **`run_chain.sh`**(30분 cron 체인 래퍼 — mkdir+PID 락으로 겹침 방지, 이전 실행 진행 중이면 skip, D-024)가 순서대로 실행: `ingest` · `redigest_youtube`(자막 raw로 굳은 유튜브 문서 opus 재요약 치유, 회차당 5) · `compute_signals` · `compute_narratives`(트리거 2종: theme_surge 상위 5 + **커버리지** — 30일 문서 30건+ & 내러티브 부재/7일+ 오래됨, 사이클당 +2 순환, 문서유형 라벨 제외, D-028) · `extract_events` · `scan_actions` · `compute_digests` · `vault_sync` · `build_search_index`. 별도 cron: `ingest_prices`(평일 16:10) · `promote_knowledge`(주 1회 일 07:00) · `scan_contradictions`(매일 06:45 — compute_signals 끝에도 편승하나 ran_today 가드로 일 1회 보장) · **`refresh_questions`(매일 07:40, D-069)** — 질문 트래커 갱신(자동도출 + numeric/sentiment 관측 갱신 + 재판정, 재료 없으면 멱등 no-op, 관리자 플래그 게이트) · **`snapshot_market`(권장 평일 16:20, D-076)** — 시장 국면 지표 일별 스냅샷(F&G·VIX·KOSPI·VKOSPI, 멱등)
1회성: `backfill_enrich` · **`backfill_enrich_batch`**(keyword 폴백 배치 재태깅 — 문서 10건/콜 sonnet, D-028 레버 1 · 2026-07-19 완료: 1,514건 전량) · `backfill_temporal` · `backfill_pace_layer`(기존 인과 노드 layer 분류 — 40개/콜 haiku, D-030 · 2026-07-19 완료: 838노드) · **`backfill_effect_strength`**(기존 인과 엣지에 effect_strength/direction 소급 — sonnet 배치, dry-run→`--apply`, confidence 불변[교차검증 이력 보존], D-065) · `migrate_narratives`(source_digests→narratives 이관, D-023)
**`extract_doc_causal`**(문서 레벨 인과 추출 — LLM 태깅 완료+본문 1,200자+ 문서[모든 소스: feed·컨콜]에서 sonnet이 명시 인과만 추출, source_doc_id·narrative_id=NULL·confidence 상한 0.5, 내러티브와 독립된 제2 인과 공급원 = 교차검증 부트스트랩. **cron 체인 편입됨(D-088, 회당 10·멱등 causal_extracted_at·run_job 게이트)** — 구 수동 보류[D-028] 번복. docs/specs/doc-causal-extraction.md) · 수동 배치: **`ingest_canon`**(역사(canon) 지식층, D-030 — UI 라벨 '역사', source_type=canon 유지 — `vault/canon/*.md`(사람+Claude 작성 통사 노트, 원저 통째 수집 금지) → source_type='canon' 흡수 → opus가 역사 인과 추출: epistemic_type='observed'(신규 중간 티어 — 널리 수용된 역사 해석), confidence 상한 0.85, 역사적 reference_period(2001~). 그래프의 시간 지평을 과거로 확장 — 파일럿: 미중 패권 25년사 54엣지, '세계질서 재편' 뿌리 접합 검증) **`ingest_canon`**(역사(canon) 지식층, D-030 — UI 라벨 '역사', source_type=canon 유지 — `vault/canon/*.md`(사람+Claude 작성 통사 노트, 원저 통째 수집 금지) → source_type='canon' 흡수 → opus가 역사 인과 추출: epistemic_type='observed'(신규 중간 티어 — 널리 수용된 역사 해석), confidence 상한 0.85, 역사적 reference_period(2001~). 그래프의 시간 지평을 과거로 확장 — 파일럿: 미중 패권 25년사 54엣지, '세계질서 재편' 뿌리 접합 검증)

## 6. 프론트엔드 (React 19 + shadcn + TanStack Query)

### IA (내비게이션)
L1은 파이프라인 흐름을 좌→우로 드러낸다 (D-056·D-057): `Home ┃ 팔로우 → 피드 → 월드모델 ┃ 대화`. 가운데 3개(입력→원천→종합)가 흐름, Home은 아침 요약+신호 대시보드(진입)·대화는 횡단 도구라 구분선으로 격리, 월드모델은 매일 여는 종착점이라 약한 강조. **탐색 모드는 해체(D-057)** — 신호 요약은 Home으로, 산업맵·인물·기업활동은 팔로우로, 신호 상세는 `/explore?list=`(pill 없는 도시에), 백테스트는 보관함. **승인 대기는 헤더 상시 배지**(어느 화면에서든, 클릭 시 인박스 Sheet — ApprovalsCard 재활용, 리서치 후보 포함). **저장됨도 헤더 상시 아이콘**(북마크 → Sheet 빠른 열람, D-078).
```
Home(/home)        아침 브리핑 + 신호 대시보드 — **어젯밤 미국장 브리핑**(D-095, 상단 승격 — 전일 거래대금 상위 20 섹터 쏠림·개별 이슈·스터디/공유 후보, 분위기 파악 가속기) + 기계의 3줄(소스경고·지식충돌·가설확인·인사이트) + **시장 국면**(매크로 리스크 포스처 — 미국 날씨×국장 본판, F&G·VIX·RSI·20EMA 미니 추이 + 결합 포스처, delta 위, D-076) + **월드모델 델타**(변한/급증 내러티브 + 최근 리포트, 매일 여는 것을 진입 요약으로) + **신호**(언급 모멘텀·주목 주제·인과 그래프 활동 — 탐색 해체로 이관, D-057). (미국 거래대금은 D-095에서 '어젯밤 미국장 브리핑'으로 상단 승격. 구 캘린더·업데이트 스트림·핵심신호 카드는 제거)
팔로우             서브탭: 팔로우(/follow: 내가 따라가는 종목·채널·블로그·태그 허브) ·
                   **유니버스**(/follow/universe: 담당 섹터 커버리지 — 산업 맵 그룹×밸류체인 단계를 기계 제안(후보)→사람 승인으로 큐레이션, UniversePage, D-037·D-039. + **'이 섹터의 내러티브' 집약 뷰 + 섹터 리포트**(D-074: 그룹을 건드리는 내러티브가 섹터 단위로 모임, 월드모델로 링크 + '섹터 리포트 생성'(compute-group)·'리포트 보기' — 섹터=팔로우×월드모델 cross-cutting 앵커)) ·
                   **컨콜**(/follow/transcripts: 미국 기업 실적 컨콜 2분할 브라우저 — 좌 그룹 팔로우, 우 핵심 정리+원문, D-061. + 상단 '곧 발표' 실적 캘린더·팔로우 행 D-day 배지·발표일 갱신, D-081) ·
                   **수출입**(/follow/trade: 관세청 품목별 무역통계 2분할 — 좌 품목 팔로우, 우 수출입 추이 차트+관련 종목(파급 논리), D-064) ·
                   **저장됨**(/follow/saved: 산출물 북마크 목록 — kind 필터 + 인라인 메모·삭제, SavedPage, D-078) ·
                   **산업 맵**(/map: 산업/섹터 4사분면 RS) · **인물**(/people: 디렉토리 → /person 도시에) · **기업활동**(/actions: 목록+요약 | 유무증 Pro) — 탐색에서 이관(D-057, 전부 '내가 커버하는 대상'). ※구 산업 페이지(/discover/industry)는 폐기
월드모델           **인식론적 시간축으로 L2 구성 (D-073)**: 내러티브(현재·서사) · 전망(미래·확률) · 지식(과거·검증). "같은 인과 그래프의 여러 속도"(D-023)에 시간대를 겹친 것. 신호(델타 감지)와 성격 달라 분리(D-031). 시간축은 무게중심이지 칸막이 아님(내러티브는 현재+미래 겸함, 리포트는 과거+현재+미래 종합) — 탭은 중심으로, 교차는 링크로.
                   **내러티브(현재)**(/narrative: topic 없이 진입=목록 랜딩, /narrative?topic=X=상세 서사·인과 구조·메르 모드·**재생성 이력 타임라인**(본문 아래·파급 시나리오 위 인라인, 도트 클릭→히스토리 페이지, D-059)·파급 시나리오·통합 리포트·**이 서사의 핵심질문**(미러링, D-067). 자동 재생성 24h 1회 제한 + 새로고침 버튼, D-059. 히스토리=/narrative/history?topic=X&v=id 재생성 이력 상세, D-060) ·
                   **전망(상위 탭, D-073)** — 미래-확률 집약, 내부 서브탭 [**논지 감사**·질문·리포트] (OutlookSubNav 토글, 지식↔온톨로지와 동형; 랜딩=논지 감사, D-083):
                   · **논지 감사**(/thesis: 내 thesis 붙여넣기 콘솔 → 인과그래프 대질 read-only 감사, 주장별 델타(일치/충돌/반박/신규)+**진자[선반영/소외, D-079]**+근거 엣지·독립 소스·시간 급증+**추적 승격[→질문, D-080]**+감사 히스토리, ThesisAuditPage, D-078. **전망의 기본 랜딩**, D-083) ·
                   · **질문**(/questions: 미결 질문 목록·콘솔·제안 큐 — QuestionsSection. **컨빅션 원장 렌즈**(D-082): 정렬 토글 최근↔중요도순(괴리[divergence]·확신[conviction] 우선) + 요약 스트립(괴리·고확신·논지발) + 논지발(created_by='thesis') 배지. **프록시 클릭 시 디테일 모달**(측정 대상·'예' 방향·전체 관측 시계열·출처, D-083). 상세는 **/question/:id 허브**(2층 판정+분할정복 트리+**질문 종합(현재 결산 리포트, D-093)**+파급 시나리오(결산을 출발 조건으로 체인)+소스, D-070)) ·
                   · **리포트**(/report: 발간 목록, /report?topic=X=디테일 — Top-down 리포트 + 최하단 구성 내러티브 링크, integrated-report/D-041) ·
                   **지식(과거, 상위 탭)**(/knowledge: **지식↔온톨로지 토글**, D-052) — 지식=구조 지도·현황 대시보드·주입 콘솔(검증 승격 핵심) / **온톨로지**(/knowledge/ontology: 구 '세계관 뷰' 리네임 — 전역 인과 그래프 노드-링크 시각화, React Flow+dagre, 렌즈 필터, in-graph 패널. /narrative/worldview는 리다이렉트). 세계관 탭은 지식으로 통합(세계관 ⊃ 지식)
피드(/feed)        통합 피드 — 탭: 전체·텔레그램·블로그·유튜브·뉴스·아티클·인물·역사(source_type=canon) (최신순), 의미 검색창, 칩 클릭=필터, 전문 보기, 이미지, 채널명 표시
                   + 사이드바: 구독 채널/블로그 목록·닉네임·활성 토글·인라인 등록 폼
문서(/doc/:id)     수집 원문·이미지 내부 열람 (외부 원문은 보조 버튼)
분석(/analyze/:code) 요약·재무·밸류·사업·공시·**렌즈**(투자 원칙 원장 기반 가치·추세 관점 + 4상한 미니뷰, D-090) (기존) + 언급 탭(1D/1W/1M 다이제스트 진입 시 자동 catch-up, D-085·
                   새로운시각·매칭 키워드 관리·신호 이력·언급 문서)
미국(/us · /us/:ticker) **미국 종목 디렉토리+도시에(D-091·D-092)** — `/us`=팔로우 서브탭 '미국'(transcript_follow 그룹별 카드 → 도시에, 렌즈 stance 배지). `/us/:ticker`=경량 도시에(헤더 yfinance + 투자 렌즈 가치/추세 market='us' + **월드모델(인과 엣지·걸린 내러티브·온톨로지 딥링크)** + **여론(언급 문서)**). 컨콜 팔로우 상세 '도시에 →'로도 진입. `/analyze`(DART 한국 전용)와 분리
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
