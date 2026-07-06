# Phase 1 — ETL 척추 (greenfield spine)

> 온톨로지(docs/ontology.md)를 실제 스키마·파이프라인으로 내리는 첫 단계.
> 목표: 그래프 + 통합 ETL 파이프라인을 **기존 앱을 깨지 않고** 얹는다.

## Posture — greenfield 척추 + 스크레이퍼 선별 이식

기존 스키마는 "단일 기업 대시보드" 무게중심이라 그래프/파이프라인 토대로 부적합.
→ 확장(wrap+dual-write) 대신 **신규 척추를 단일 진실원천**으로 세운다.

```
[옛 세계: 기존 라우터·blog_posts/telegram_messages·프론트]  ← 손대지 않음, 계속 동작
        │ 공유(호출만)                         ▲ 나중에 읽기 cutover 후 은퇴
        ▼                                       │
[services/ 스크레이퍼: scrape_channel·scrape_rss·fetch_full_content·dart·krx]  ← 검증된 획득 로직
        │ 커넥터가 호출 (persistence/tagging 결합은 버림)
        ▼
[신규 척추: pipeline/ + 그래프 테이블]  ← 그래프·RAG·월드모델은 여기 위에만
```

두 수집 경로가 잠시 공존하되 **서로 write하지 않음** → dual-write 동기화 버그 없음.

## 성공 기준
- `python backend/database.py` 통과, 신규 테이블 생성, 기존 데이터 무손상
- `entities`가 `companies`에서 시딩됨
- 블로그 수집 시 `raw_documents`+`entity_links` 채워지고 기존 블로그 UI 무영향
- enrich 인터페이스 동작 (LLM 키 없으면 키워드 fallback)

## 확정 결정
1. **greenfield 척추** (dual-write 철회) — 신규 테이블에만 적재, 기존 앱 미변경.
2. **ANTHROPIC_API_KEY 현재 없음** → enrich는 인터페이스 + 키워드 fallback 스켈레톤만. LLM 호출은 키 확보 후 활성화.
3. **markitdown = PDF/첨부(향후 컨콜) 전용**. 블로그는 기존 텍스트 추출 유지.

## 신규 테이블 (database.py init_db에 additive)
```
entities(id PK, type, name, aliases, meta_json, status['active'|'proposed'], created_at)
  UNIQUE(type, name)
entity_relations(id, src_id→entities, dst_id→entities, rel_type,
                 epistemic_type['fact'|'hypothesis'], confidence, source_doc_id,
                 valid_from, valid_to, created_at)
observations(id, entity_id→entities, date, metric, value REAL, unit, source)
  UNIQUE(entity_id, date, metric, source)
raw_documents(id, source_type, source_id, title, url, published_at,
              fetched_at, raw_content, markdown, content_hash)
  UNIQUE(source_type, source_id)
enrichments(id, doc_id→raw_documents, summary, sentiment, model, content_hash, enriched_at)
entity_links(id, doc_id→raw_documents, entity_id→entities,
             link_type['mention'|'stock'|'industry'|'topic'], confidence)
models(id, name, spec_json, output_entity_id→entities, updated_at)
```
- `catalysts`는 이미 event 역할 → Phase 1b에서 entities(type=event)+ABOUT로 승격. 지금 미변경.
- `blog_post_tags`는 entity_links로 일반화되나 당분간 유지(옛 세계용).

## 스텝

| # | 내용 | 검증 |
|---|---|---|
| 1 | 척추 스키마 additive | `python backend/database.py`, 기존 데이터 무손상 |
| 2 | `scripts/seed_entities.py` — companies→entities, sector 노드+MEMBER_OF | entities(company) count == companies |
| 3 | `pipeline/` — SourceConnector + runner(fetch→normalize→enrich→store), content_hash 멱등 | 더미 커넥터로 1건 적재 |
| 4 | Blog/Telegram 커넥터 = 스크레이퍼 함수만 이식, 척추에만 적재 | RSS 1개 수집→raw_documents+entity_links, 기존 UI 무영향 |
| 5 | enrich 인터페이스 + 키워드 fallback (LLM은 키 확보 후) | 샘플 문서 태깅 생성, 키 없이 동작 |

## 이 단계에서 안 하는 것
- 읽기 cutover, 무역(관세청)·event 캘린더 자동적재, RAG/벡터, 연결형 모델 DAG.
