# 통합 리포트 — 공유 인과 내러티브 취합 → 종목 다각도 재분석 → Top-down 리포트

> 2026-07-21. 상태: 착수. 배경: "반도체·HBM 내러티브가 각각 파급 시나리오·인과 구조·공유 내러티브를
> 낸다. 공유 인과로 엮인 내러티브들을 애널리스트 참고자료로 보고 취합 + 종목 분석을 합쳐 통합
> 리포트를 낸다"(사용자 2026-07-21). 앵커=주제 시드+공유 이웃, 깊이=종목 분석까지(연쇄 LLM).
> 선례: mega_narrative(공유 노드 내러티브를 하나로 꿰는 세계관 서사) — 이건 그걸 **투자 리포트**로 확장.

## 핵심 통찰 (비타협)
**같은 종목도 내러티브마다 파급효과가 다르다.** 그래서 종목별로 각 내러티브의 파급을 *다 모은 뒤*,
그 다각도를 반영해 **다시** 종목을 분석한다 — 단일 이벤트 업사이드보다 풍부한 기업 분석.

## 파이프라인 (연쇄 LLM — scenario/mega처럼 pipeline/*.py, 오케스트레이션 도구 아님)
`pipeline/report.py` — `build_report(conn, anchor_topic, force=False)`:

1. **앵커 + 공유 이웃 취합**(LLM 0): 앵커 내러티브(topic 최신 버전) + `related_narratives`(공유 인과
   노드로 랭킹)의 상위 K개 = 내러티브 집합. members_hash=(topic,version) 해시 → 멱등 캐시 키.
2. **자료 수집**(LLM 0, 캐시 재사용): 각 내러티브의 body 요약 + **캐시된 scenario**(파급 answer +
   beneficiaries[name,rel,reason]) 조회. scenario 없으면 그 내러티브는 body/인과만 사용(리포트용으로
   opus 새로 안 돌림 — 비용 통제). 공유 인과 구조(shared edges)도 취합.
3. **종목별 다각도 집계**(LLM 0): 모든 내러티브의 수혜 종목을 stock_code로 묶어
   `{stock: [(narrative_topic, rel, reason), …]}`. 등장 내러티브 수(교차 현저성)로 랭킹, 상위 M개.
4. **종목별 재분석**(연쇄 LLM, sonnet · 종목당 1콜): 그 종목의 **다각도 파급**(여러 내러티브의 rel·reason)
   + 결정적 앵커(upside_model._anchor: 주가·EPS·PER·매출·순이익률) + 캐시된 업사이드 요약 →
   통합 기업 분석 블록 `{stock, name, thesis(md), key_points[], risks[]}`. 여러 내러티브를 관통하는
   투자 포인트로 종합(단일 파급 나열 금지).
5. **리포트 종합**(opus · 1콜): Top-down 마크다운 —
   `## 산업 분석`(엮인 내러티브+파급+공유 인과 구조를 하나의 산업 스토리로) →
   `## 기업 분석`(4번 종목 블록들 = 재료로 주고 관통 서술) →
   `## 투자 포인트 · 전략`(종합 판단 + 무효화 조건[falsifier] + 타이밍 렌즈[추세추종] + 비대칭 프레이밍).
6. **적재**: `reports` 테이블(anchor_topic PK · title · body · members_json · members_hash · model).

**연쇄 구조**: 취합(0) → 종목별 종합 ×M(sonnet) → 리포트 종합 ×1(opus). 총 M+1 LLM 콜, 전부 캐시.

## 캐시 (D-038 철학)
`reports`(anchor_topic PK, members_hash로 멱등). `GET /api/spine/report?topic=`(저장분, LLM 0) +
`POST /api/spine/report/compute?topic=&refresh=`(구성원 해시 동일하면 저장분, refresh만 재생성).
구성원 내러티브/버전이 바뀌면 stale.

## 가드레일 (기존 규율)
- 취합·종합 O, **없는 사실 창작 X**(mega 프롬프트 규율 재사용) · 범위+조건부, 거짓 정밀 금지(D-034)
- 기계 초안·사람 검토 · 종목 수치는 캐시된 앵커/업사이드 재사용(리포트가 새 정량 창작 안 함)
- 품질 상한 = 밑 재료(내러티브·scenario·업사이드) 품질. 개발 DB 재무 스케일 이슈 그대로 반영됨.

## 프론트
내러티브 페이지(주제 상세)에 "통합 리포트" 진입 → 저장분 자동 표시 + '다시 생성'(refresh) +
'저장분 {날짜}'·stale 힌트(scenario 섹션과 동형). Top-down 섹션 렌더(Markdown) + 종목 블록에
/analyze 링크·업사이드 연결.

## 남김(후속)
1M 스코프 리포트 · PDF/공유 export · 종목 블록에 실시간 시세·타이밍 신호 · 편입 큐 연동.

## 참조
pipeline/report.py(신규) · narrative.related_narratives · scenario(캐시 beneficiaries) ·
upside_model._anchor · mega_narrative(선례) · routers/spine_narrative(or 신규 spine_report) ·
D-032(메가)·D-034·D-035·D-036·D-038·D-040 · 대화 2026-07-21
