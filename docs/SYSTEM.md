# Explorer — 시스템 현황 명세

> 최종 갱신: 2026-07-10 (feat/etl-spine 브랜치 기준)
> 목적: 현재 시스템의 전체 구조·기능·데이터를 한눈에 파악하기 위한 현황 문서.
> 기획 배경·온톨로지는 docs/ontology.md, docs/specs/product-v2.md 참조.
> (구 ARCHITECTURE.md는 초기 대시보드 시절 문서 — 본 문서가 현행)

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

## 2. 아키텍처 조감

```
[소스]  텔레그램(텍스트+이미지) · 블로그(네이버/티스토리/RSS) · vault/notes(내 가설)
        DART(전시장 공시) · FDR(전종목 주가) — (대기: 관세청 무역)
   │
   ▼  30분 cron 체인 (logs/ingest.log)
ingest(수집→enrich→그래프) → compute_signals → extract_events(이미지 비전)
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
| `entities` | 4,135 | 노드: company(3,943)·sector(KSIC 165+태그)·theme·(예약: person/policy/macro…) |
| `entity_relations` | 2,760 | 엣지: MEMBER_OF(기업→섹터). epistemic_type·confidence·valid_from/to 보유 |
| `raw_documents` | 264 | 모든 소스의 문서 원본+markdown+media_json. UNIQUE(source_type, source_id) |
| `enrichments` | 264 | 문서당 1행: 요약·감성·모델 (content_hash 캐시) |
| `entity_links` | 563 | 문서↔엔티티. confidence 계층: 위키링크 1.0 > LLM 0.9 > 사용자 키워드 0.7 > 정식명 substring 0.6 > 태그 0.5 |
| `signals` | 9 | mention_surge(7일 vs 직전 7일)·high_52w(52주 신고가). payload+interpretation 분리 |
| `entity_digests` | 30 | 종목별 1D/롤링7D 요약+새로운시각. (entity, period, KST날짜) 키로 영구 아카이브 |
| `corporate_actions` | 57 | 시총 5,000억+ 유·무상증자/합병/분할/공개매수/감자 (DART 전시장 스캔+haiku 요약) |
| `capital_raise_details` | 16 | 유무증 Pro: 발행가 1·2차·확정/구주·신주/기준일·권리락(파생)·청약·납입·상장/주관사 |
| `media_analysis` | 31 | 이미지 비전 분류 캐시 (calendar면 → catalysts 적재) |
| `entity_keywords` | 6 | 종목별 사용자 매칭 키워드 (등록 시 소급 링크) |
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
| `store` | 멱등 적재(content_hash)·재enrich 시 stale 링크 제거·4층 confidence 링크 |
| `enrich` | 엔진 선택(claude-code/api/keyword)·구조화 태깅 |
| `search` | FTS5+sqlite-vec 하이브리드(RRF)·인덱스 빌드 |
| `signals` | mention_surge·high_52w (200일+ 히스토리 요구) |
| `vision` | 이미지 분류→증시일정 이벤트→catalysts |
| `actions` / `rights` | 기업활동 스캔·요약 / 유무증 구조화 추출(종속회사 제외) |
| `digests` | 1D/7D 롤링(계층 요약)·새로운 시각(이전 요약 대비) |
| `rag` | 검색 top-8→sonnet 종합·출처 인용 강제·갭 분석 |
| `dates` / `normalize` | ISO 정규화(KST 버킷) / markitdown(PDF)·HTML 텍스트화 |

### 5-2. API (spine 라우터 10종)
| 엔드포인트 | 기능 |
|---|---|
| `GET /api/spine/home` | 캘린더(내 종목 우선)+왓치리스트·팔로우 delta 스트림+시장 하이라이트 |
| `GET /api/spine/feed` | 통합 피드 — q(하이브리드 검색)·source·stock·industry·topic 필터, 전문·이미지·채널명 |
| `GET /api/spine/doc/{id}` | 문서 디테일 (raw content·이미지·태그·요약) |
| `GET /api/spine/signals` | 신호 (type·days) |
| `POST /api/spine/ask` | RAG 질의응답 (인용+갭 분석) |
| `GET /api/spine/actions` (+`/rights`) | 기업활동 목록+요약 / 유무증 Pro (차액·증자비율 계산 포함) |
| `GET /api/spine/digests` | 종목 1D/7D 요약 아카이브 |
| `GET·POST·DELETE /api/spine/follows` | 엔티티 팔로우 |
| `GET·POST·DELETE /api/spine/keywords` | 매칭 키워드 (등록 시 소급 링크) |
| `POST /api/spine/sources/telegram·blog` | 소스 등록 (실검증→저장→백그라운드 첫 수집) |

기존 라우터(companies·financials·disclosures·stock_prices·watchlist·screener 등 17종)는 종목 디테일·리서치노트·스크리너가 계속 사용.

### 5-3. 스크립트 (`scripts/`)
시딩: `seed_companies`(DART) · `seed_entities`(그래프) · `seed_sectors`(FDR KSIC)
운영(cron): `ingest` · `ingest_prices` · `compute_signals` · `extract_events` · `scan_actions` · `compute_digests` · `vault_sync` · `build_search_index`
1회성: `backfill_enrich`

## 6. 프론트엔드 (React 19 + shadcn + TanStack Query)

### IA (내비게이션)
```
홈(/home)          내 종목·팔로우 delta 스트림 + 이번주 캘린더 + 시장 하이라이트 (빈화면 방지 승격)
탐색               신호(/explore: mention_surge·52주신고가 카드) · AI 질문(/ask) ·
                   기업활동(/actions: 목록+요약 | 유무증 Pro 토글+방식 필터) · 산업군 · 스크리너 · 대안데이터
피드(/feed)        통합 피드 — 의미 검색창, 칩 클릭=필터, 전문 보기, 이미지, 채널명 표시
                   + 사이드바: 구독 채널/블로그 목록·닉네임·활성 토글·인라인 등록 폼
문서(/doc/:id)     수집 원문·이미지 내부 열람 (외부 원문은 보조 버튼)
분석(/analyze/:code) 요약·재무·밸류·사업·공시 (기존) + 언급 탭(1D/7D 다이제스트 2열·
                   새로운시각·매칭 키워드 관리·신호 이력·언급 문서)
VS 비교 · 리서치노트(워치리스트/투자메모/카탈리스트)
```

### 공통 시스템
- 디자인 토큰: Apple HIG light/dark (next-themes 토글), 도메인 토큰 `--color-up/down`(상승빨강/하락파랑)·`--color-fact/hypothesis`
- shared 컴포넌트: SignalCard(확장형 카드 시스템)·DocumentCard·EntityChip(저신뢰 흐림)·SourceBadge·EpistemicBadge류·FreshnessStamp·ThemeToggle
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
