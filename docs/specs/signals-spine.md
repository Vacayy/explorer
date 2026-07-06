# 신호(Signals) 계층 — 척추 위의 파생 분석 (기획 기록)

> 상태: **①(언급량 급증) 구현됨** — `pipeline/signals.py` + `scripts/compute_signals.py`, cron으로 ingest 후 자동 계산. ②③은 기획 단계. 원시 데이터가 아닌 **파생 계층**으로,
> ETL 척추(raw_documents/entity_links/observations)와 그래프(MAKES/MEMBER_OF) 위에서 주기 재계산된다.
> 기존 discover/signals 페이지(docs/specs/discover-signals.md)가 UI 착지점.

## 기획된 신호 3종

### 1. 언급량 급증 종목
- A종목: 최근 7일 n회 언급 (baseline 대비 급증 감지)
- 주요 키워드 / 주요 내용 요약
- 주가 추이 차트, 밸류에이션(12m fwd P/E 등)
- **재료**: `entity_links(link_type='stock')` ⨝ `raw_documents.published_at`로 시간축 언급 카운트.
  키워드·요약은 `enrichments`. 주가·밸류는 stock_prices/fundamentals/consensus.
- 척추 변경 불필요 — 지금 구조로 계산 가능.

### 2. 수출 데이터 변화 종목
- B섹터: 미국향 수출 YoY +50% 감지, 직전 분기 대비 상승폭
- 관련 종목: product의 `MAKES` 엣지 역추적으로 도출
- 시장 해석: 실적 추정치 상향 가능성 등 (LLM)
- **재료**: observations(product 노드) YoY/QoQ 계산 + 무역 커넥터(P0 예정).
- **규약**: 국가향 차원은 metric 점 네임스페이스로 인코딩 — `export_usd.US`, `export_usd.CN`.

### 3. 52주 신고가 종목
- F종목 + 기업분석 + 테마 + 시장 해석
- **재료**: stock_prices 롤링 max 계산 + `MEMBER_OF`(섹터/테마) 조인 + LLM 해석.

## 설계 규약 (확정)

1. **observations metric 차원 규약**: `metric`은 점 네임스페이스로 차원 인코딩 가능
   (`export_usd.US`). 별도 dim 컬럼은 실제 필요 시 추가.
2. **signals 테이블 (additive, 구현 시)**:
   ```
   signals(id, signal_type, entity_id→entities, date, payload_json,
           interpretation, interpretation_model, created_at)
   ```
   - 신호 산출값(payload)과 LLM 해석(interpretation)을 분리 저장.
3. **epistemic 규율 적용**: "시장 해석"은 LLM 가설이다. 해석이 특정 문서에 근거하면
   entity_links/source_doc 참조를 남기고, UI에서 사실(수치)과 해석을 시각적으로 구분한다.
4. 신호 계산은 스케줄 배치(ingest 후 후처리)로 재계산 — 척추 테이블은 읽기만 한다.
