# 소스 도시에 — 채널/블로그 디테일 페이지

## 배경 (문제)
소스(텔레그램 채널·블로그)는 각각 다른 주인이 다른 관점으로 follow-up 해온 맥락을 갖는다.
현재는 수집만 하고 "이 채널은 어떤 맥락 속에서 이런 말을 했지?"에 답할 화면이 없다.
기업에 도시에(언급 요약)가 있듯, 소스에도 도시에가 필요하다. (프리미티브: 도시에 = entity pull — 새 탭 아님)

## 요약 생성 정책 (사용자 확정)
1. **열람/호출 시점에 생성** — cron 선계산 없음
2. **지난 요약 이후 새 글이 있을 때만 재생성** — `doc_ids_hash` 가드 (entity_digests 패턴 재사용)
3. 새 글이 없으면 캐시 반환, LLM 호출 0회

## 데이터
- 소스 레지스트리: `telegram_channels`(channel_name, display_name) / `blog_sources`(url, blog_name, author)
- 문서 매칭: telegram → `source_id LIKE '{channel}/%'`, blog → `url LIKE '{blog_url}%'` (health와 동일)
- 신규 테이블 `source_digests`: kind, key, digest(관점 프로필 마크다운), insights(지난 프로필 대비 변화),
  doc_count, doc_ids_hash, model, created_at — `UNIQUE(kind, key)` 1행 upsert

## API
- `GET /api/spine/sources/dossier?kind=telegram|blog&key=` — **LLM 호출 없음, 즉시 응답**
  - source 프로필(이름·저자·활성·총 글수·7d/24h·최초~최근), 캐시된 summary(+created_at),
    `summary_stale` 플래그, top 엔티티(90d stock/industry/topic 링크 집계), 최근 글 20건
- `POST /api/spine/sources/dossier/summary?kind=&key=` — stale이면 haiku로 프로필 생성 후 반환
  - 최근 40건(제목+발췌 500자) + 이전 프로필(새로움 판단 기준) → JSON {digest, new_insights}
  - LLM 호출은 트랜잭션 밖 (락 방지 원칙)

## 화면 `/source?kind=&key=` (쿼리 파라미터 = 단일 상태 소스; blog key=URL 인코딩 안전)
- 헤더: 이름 · 저자 · kind 뱃지 · 수집 통계
- **관점 프로필 카드**: digest 마크다운 + insights("지난 요약 이후") / stale이면 자동 생성 트리거 + "새 글 반영해 요약 생성 중…"
- 주로 다루는 것: 종목 칩(→/analyze) + 산업/토픽 칩(→/feed 필터)
- 최근 글 리스트(→/doc/:id)

### 5-state
- Empty: 수집 문서 0건 → "아직 수집된 글이 없습니다" (프로필 카드 생략)
- Loading: 페이지 스켈레톤 / 요약 카드 자체 로딩("요약 생성 중…")
- Partial: LLM 불가·실패 → 통계·문서 리스트는 정상, 요약 카드에 안내
- Error: 소스 미등록(404)/네트워크 → ErrorState + 재시도
- Ideal: 프로필 + 엔티티 + 최근 글

## 진입점 (앤티-분산: 새 탭 0개)
- 피드 카드의 채널명 → 링크 (FeedDocument에 channel_kind/channel_key 추가)
- 옴니바: 등록 소스 목록 "소스" 그룹
