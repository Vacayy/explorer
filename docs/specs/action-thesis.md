# action_thesis — 이벤트 → 수혜 종목 → 조건부 업사이드/하방 (에이전트화 다음 단계)

> 2026-07-21. 상태: 기획 — Phase 1 착수 (D-035). 배경: "이벤트 터지면 애널 안 기다리고 실시간으로
> 뭘 사야 하고, 업사이드/하방 얼마인지 딱" (사용자 피드백 2026-07-21). 준비물(주가·재무·RS·인과
> 그래프·내러티브·scenario 엔진·falsifier·lenses)이 갖춰져 이들을 하나의 액션 명제로 엮는다.

## 관통 원칙 (비타협)

- **기계는 제안, 사람은 승인** (D-020·D-022). action_thesis는 자동매매가 아니라 사람이 결정할 명제.
- **범위+조건부, point target 금지**: "업사이드 +37%" (거짓 정밀) ✗ → "시나리오 X 실현 시(확률~)
  대략 +20~40%, 무효화 조건 Y" ✓. 시장은 물리가 아니다(반사적 도메인) — 정직한 범위가 더 값지다.
- **정량은 좁은 렌즈에만**: 전 종목 범용 모델 금지. 이벤트로 스코프된 소수 종목에만 모델링 적용.
- **좋은 기업 ≠ 좋은 종목**: 기업 질(업사이드/하방)과 매매(타이밍·사이징)를 분리. 후자는 추세추종 렌즈.

## 전체 플로우

```
이벤트/신호 발화
  → scenario 엔진: 1·2·3차 파급 → 수혜 섹터 (이미 있음, BENEFITS_FROM 종착=섹터)
  → [Phase 1] 수혜 섹터 → 종목 후보 (문서 공동언급 + RS + 밸류 스크린)
  → [Phase 2] 업사이드 = 모델링 (매출 수혜 → 이익 → EPS → 적정주가; 불확실하면 멀티플)
  → [Phase 3] 하방 = 펀더멘탈 지지선 대비 현재가 + 무효화 조건(falsifier)
  → [Phase 3] 매매 타이밍 = 추세추종 렌즈 (RS 돌파·52주 위치)
  → 범위+조건부 action_thesis 카드 → 홈 승인 (agent_proposals kind='action_thesis')
```

## 업사이드 방법론 (Phase 2 — 모델링, `models` 층 활성화)

사용자 정의 4단계(정확도 순, ontology.md "살아있는 모델" 실체화):
1. **매출 수혜**: 이벤트가 해당 기업 매출에 주는 영향. 기법 선택 — P×Q · Capa×가동률 · TAM 업데이트
   후 목표 점유율 적용. 기업·이벤트 성격에 맞는 기법을 LLM이 제안하되 핵심 가정(Capa·ASP·점유)은
   애널리스트 소유(ontology.md 원칙 3).
2. **이익 add**: 1번 매출 증분에 비즈니스 특성·대외 환경(원재료가 등) 고려한 러프 이익률 적용.
3. **EPS 업데이트 → 새 적정주가**: 갱신 EPS × 타당 멀티플.
4. **불확실(먼 미래·추론 시기상조)**: 실적 반영 대신 **기대감을 멀티플에 반영** (리레이팅 폭으로 표현).
- 출력: 범위(보수~낙관) + 각 시나리오 확률감 + 근거(모델 가정/유사 사례). `models` 테이블에 spec_json으로
  적재 → 재현·감사·자동 리프레시(입력 observation 갱신 시).

## 하방 방법론 (Phase 3)

- **펀더멘탈 지지선 대비 현재가**: 실적·전망으로 하방이 탄탄한지 판단. "틀려도 -20% (실적 하단),
  산업 수혜 맞으면 이익 상향으로 +100% 여지" 식 **비대칭(하방 제한 vs 상방 여지)** 프레이밍.
- **무효화 조건 = falsifier 재활용**: "이 조건 깨지면 논리 무효" → 하방 트리거. 승인 시 falsifier로
  주입돼 반증 센티넬이 매일 감시.

## 매매 타이밍 (Phase 3 — 추세추종 렌즈)

- 기업 질 판단과 **분리**. "아무리 좋은 기업도 너무 빠르게/늦게/많이/적게 담으면 나쁜 투자."
- RS 돌파·52주 위치·거래량으로 진입/청산 신호. 투자자별 리스크·기간이 다름을 명시(단정 금지).

## Phase 1 — 수혜 섹터 → 종목 스크린 (착수, 결정적·LLM 0)

**입력**: 수혜 섹터/테마 (엔티티 이름 또는 id — scenario/causal의 BENEFITS_FROM 종착, 또는 노드 클릭).

**섹터→종목 연결**: **문서 공동언급** (compute_research_candidates 검증 패턴 재사용). MEMBER_OF(KSIC)와
투자언어 테마는 taxonomy가 달라 직접 매칭 불가 — 최근 문서에서 그 테마와 함께 링크된 company 종목이
의미적으로 올바른 연결. `entity_links`(industry/topic ↔ stock 공동 doc), 최근 N일, 문서당 종목 수 상한.

**후보 enrich** (각 종목):
- RS: `_rs_short`(research_candidates 재사용) — 단기 RS 백분위 now/prev.
- 밸류: `fundamentals` 최신 per·pbr(·bps·eps).
- 시총·52주 위치: `stock_prices`.

**랭킹/출력**: 기본 RS 내림차순(추세 렌즈 우선) + 밸류 지표 병기. 반환:
`{stock_code, name, rs_short, rs_prev, per, pbr, market_cap, pos_52w, co_mentions}`. Top N.

**노출(Phase 1)**: `GET /api/spine/beneficiary/screen?sector=` + 세계관 뷰에서 **sector 노드 클릭 시
상세 패널에 "수혜 후보 종목"** 섹션(RS·밸류 배지). 후속 Phase에서 이 후보가 action_thesis 카드의 입력.

**검증**: BE import·실 종목 스크린 표본 확인(우주항공/반도체 등)·FE tsc.

## Out of Scope (Phase 1)
- 업사이드/하방 정량(Phase 2·3) · 타이밍 신호 · 실시간 트리거·푸시 · action_thesis 카드/승인 흐름.
- 자동매매(원칙상 영구 out).

## 참조
scenario.py(build_scenario) · research_candidates.py(_rs_short·공동언급 스크린) · entity_links ·
fundamentals · stock_prices · falsifiers(무효화) · lenses(추세·가치) · ontology.md(models 층) ·
D-020·D-022(제안-승인)·D-023(수혜 종착=섹터)·D-034(범위·거짓정밀 경계) · 대화 2026-07-21
