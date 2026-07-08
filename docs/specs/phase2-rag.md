# Phase 2 — RAG (검색 레이어 구현됨 / 생성은 LLM 키 대기)

## 구현된 것 — 하이브리드 검색

```
질의 → ┬ BM25 (FTS5 doc_fts, database.py 트리거로 raw_documents와 동기화)
       └ 벡터 (sqlite-vec doc_vec + fastembed 로컬 임베딩)
       → RRF 융합 (1/(60+rank) 합산) — gbrain 패턴 차용
```

- 임베딩: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384d, 0.22GB, 로컬·무료).
  한국어 검증: 관련 0.71/0.53 vs 무관 0.21. API 키 불필요.
- `pipeline/search.py`: `search(q, k)` + `build_index()` (FTS 리빌드 + 미임베딩 문서만 임베딩).
- graceful degrade: sqlite-vec/fastembed 미가용 시 BM25 단독.
- 노출: `GET /api/spine/feed?q=…` — 검색 모드 시 RRF 순 정렬. FE 피드 검색 인풋(?q= 동기화).
- cron 체인: ingest → compute_signals → vault_sync --export → **build_search_index**.

검증: "HBM 수요" → 1위 사용자 가설 노트, 이어 메모리 가격 텔레그램 포스트 (제목에 HBM 없어도
의미 매칭 — 벡터의 기여). 사람 가설과 자동 수집이 같은 검색 공간에서 랭킹된다.

## 남은 것 — 생성 (ANTHROPIC_API_KEY 확보 시)

1. **/chat 질의응답**: 하이브리드 검색 top-k → Claude로 종합, **출처 인용 필수** (인용 없는 답변 금지).
2. **갭 분석을 일급 출력으로** (gbrain 차용, 사실/가설 월드모델과 정합):
   - 이 가설(note)을 뒷받침하는 수집 문서가 없다 → "인용 없음"
   - 이 가설과 모순되는 문서/관측이 있다 → "모순 후보"
   - 관련 문서가 오래됐다 → "최신성 경고"
3. 청킹: 현재 문서 단위 임베딩(대부분 짧음). 컨콜 PDF 등 장문 소스 추가 시 청크 단위로 확장.
4. 검색 필터: 엔티티/기간/소스 필터와 벡터 검색 결합 (지금은 feed 필터와 교집합으로 동작).
