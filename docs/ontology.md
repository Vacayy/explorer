# Explorer — 투자 월드모델 온톨로지

> 세상이 자산가치를 움직이는 인과·흐름 구조를 여러 "렌즈"로 보는 지식 그래프의 스키마 정의.
> 렌즈 = 별도 시스템이 아니라 **하나의 타입드 entity/relation 그래프 위의 saved 서브그래프/뷰**.
> 축이 늘어도 DB는 1개, entity_type / relation_type 어휘만 확장된다.

## 설계 원칙

1. **사실 vs 가설 분리 (비타협)** — 모든 엣지는 `epistemic_type`을 가진다.
   - `fact`: 공시·지분·공급계약·통계로 검증 가능.
   - `hypothesis`: LLM이 인터뷰·논문·글에서 추출한 인과 주장 → `confidence` + `source_doc_id` 필수.
   - 둘을 섞으면 월드모델이 그럴듯한 쓰레기가 된다. 목표는 "믿는 자동 오라클"이 아니라 "출처 달린 가설 트래커".
2. **엣지는 단방향 저장** — `SUPPLIES` A→B만 저장, "고객사"는 질의로 역전. 양방향 저장 금지(정합성).
3. **분업** — 애널리스트가 온톨로지 skeleton(노드/엣지 타입, 핵심 밸류체인, 모델 formula)을 소유. 파이프라인은 인스턴스·observations·가설 엣지 후보를 채우고 사람이 승인/기각.
4. **스코프 규율** — 세상 전체를 day1에 모델링하지 않는다. 메모리/AI 렌즈 1개를 end-to-end로 완성해 루프를 증명한 뒤 렌즈 추가.

---

## 노드 타입 (entity_type)

`active` = 메모리/AI 렌즈에서 지금 채움 · `stub` = 연결점만 · `reserved` = 타입만 선언, 타 렌즈에서 채움.

| 상태 | type | 정의 | 예시 |
|---|---|---|---|
| active | `company` | 상장/비상장 기업 | 삼성전자, SK하이닉스, Micron, NVIDIA, TSMC, ASML, 한미반도체 |
| active | `institution` | 기업 아닌 수요/자본 주체 | MS·구글·아마존·메타(하이퍼스케일러), OpenAI·Anthropic·xAI(AI랩) |
| active | `product` | 밸류체인을 흐르는 재화 | HBM3E, DRAM, NAND, GPU(B200), EUV장비, 웨이퍼 |
| active | `theme` | 내러티브/수요 동인(추상 노드) | "AI 학습·추론 수요", "AI CAPEX 사이클" |
| active | `sector` | 산업 분류(롤업·스크리닝용) | 메모리반도체, 반도체 소부장 |
| active | `event` | 시점 이벤트(증시일정 캘린더 통합) | 실적발표, FOMC, 규제발표, 컨콜 |
| stub | `person` | 방향성을 이끄는 인물 (인물 렌즈 hook) | 젠슨황, 알트만, 다리오 |
| reserved | `policy` | 정책·규제 (지정학 렌즈) | 대중 반도체 수출규제, CHIPS Act |
| reserved | `macro_indicator` | 할인율/유동성 축 (매크로 렌즈) | 기준금리, TGA 잔고, CPI |
| reserved | `paper` | 피인용 최신 논문 (인물 렌즈) | — |
| reserved | `geo` | 국가/진영 (지정학 렌즈) — 1급 노드는 아직 예약. 장소는 현재 인과 엣지의 `geo_scope` 스칼라로 정박(D-034) | 미국, 중국 |
| reserved | `commodity` | 원자재 (에너지 렌즈) | 원유, 가스, 전력 |

---

## 엣지 타입 (relation_type)

### FACT (검증 가능)

| type | 방향 | 예시 |
|---|---|---|
| `SUPPLIES` | A→B (A가 B에 공급) | SK하이닉스 →SUPPLIES(HBM)→ NVIDIA / ASML →SUPPLIES(EUV)→ TSMC |
| `CAPEX_TO` | A→B (A의 설비투자가 B로) | 마이크로소프트 →CAPEX_TO→ NVIDIA |
| `MAKES` | A→product | SK하이닉스 →MAKES→ HBM3E |
| `COMPETES_WITH` | A↔B | 삼성전자 ↔ SK하이닉스 |
| `LEADS` | person→org | 젠슨황 →LEADS→ NVIDIA |
| `MEMBER_OF` | A→sector/theme, product→category | SK하이닉스 →MEMBER_OF→ 메모리반도체 |
| `ABOUT` | event↔entity (캘린더 연결) | "삼성 2Q 실적발표" →ABOUT→ 삼성전자 |
| `OWNS`/`HOLDS` | institution→company (예약: 포트폴리오 렌즈) | 국민연금 →HOLDS→ 삼성전자 |

### HYPOTHESIS (LLM 추출, `confidence` + `source_doc_id` 필수)

| type | 방향 | 예시 |
|---|---|---|
| `DRIVES_DEMAND` | theme→product | "AI 학습 수요" →DRIVES_DEMAND→ HBM |
| `CONSTRAINS` | policy/macro→entity | "대중 수출규제" →CONSTRAINS→ 중국 파운드리 |
| `DISCOUNTS` | macro→theme | 기준금리↑ →DISCOUNTS→ AI CAPEX 밸류에이션 |
| `INFLUENCES` | person→theme | 젠슨황 발언 →INFLUENCES→ "AI CAPEX 심리" |
| `IMPACTS` | event→entity (예상 효과) | FOMC →IMPACTS→ 위험자산 |

---

## 인스턴스 그래프 — 메모리/AI 현금흐름 렌즈

현금흐름 순서 = 방향성 엣지의 경로.

```
[자본시장/소비자]
     │ FUNDS
     ▼
[하이퍼스케일러/AI랩]  ── MS·구글·메타·OpenAI
     │ CAPEX_TO
     ▼
[NVIDIA] ──MAKES──▶ [GPU]
     ▲ SUPPLIES(HBM)
     │ BUYS_FROM(=SUPPLIES 역질의)
     ▼
[메모리 IDM] ──MAKES──▶ [HBM/DRAM/NAND]
  하이닉스·삼성·마이크론
     │ BUYS_FROM
     ▼
[소부장] ── ASML(EUV)·한미반도체(TC본더)·주성엔지니어링

  (theme) "AI 학습·추론 수요" ──DRIVES_DEMAND(가설)──▶ HBM
  (person) 젠슨황 ──LEADS──▶ NVIDIA,  발언 ──INFLUENCES(가설)──▶ "AI CAPEX 심리"
  (sector) 메모리반도체 ◀──MEMBER_OF── 하이닉스·삼성·마이크론
```

"메모리 투자를 연다" = 메모리 IDM 노드에서 up/downstream 순회 + 각 노드에 최신 observations·문서·가설을 얹기.

---

## 시계열 (observations) & 2계층 저장

수치 데이터는 도메인 원본 테이블(source-of-record)을 유지하고, 핵심 라인만 observations로 투영한다.

| 데이터 | 원본 테이블 | 그래프 투영 | 붙는 노드 |
|---|---|---|---|
| 재무제표(DART) | `financial_statements`(계정·연결/별도·분기 그대로) | 매출·OP·CAPEX·재고 → observations | `company` |
| 공시(DART) | `raw_documents` | 실적발표·유증 등 → `event` 노드 | `company` + `event`(ABOUT) |
| 주가/밸류(KRX) | 기존 테이블 | 종가·시총·PER → observations | `company` |
| 수출입(관세청) | 신규 상세 테이블(HS·국가·방향·월·금액) | HS별 수출입액 → observations | `product` (HS↔product↔company 매핑 필요) |

- **metric 차원 규약**: `metric`은 점 네임스페이스로 차원을 인코딩할 수 있다
  (예: `export_usd.US` = 미국향 수출금액). 별도 dimension 컬럼은 실제 필요가 증명될 때 추가.
- **재무**: company observations + 공시 events로 완전 fit.
- **수출입**: product 노드에 붙고 `product ─MAKES─ company`로 기업까지 전파. 유일한 추가작업 = HS↔product↔company 매핑(초기엔 산업 단위 거친 매핑).

---

## 살아있는 모델 (엑셀 continuity)

독립형 단일 모델부터 시작하되, **출력을 observation으로 기록**해 연결형(chained)이 emergent하게 자라도록 한다. 풀 DAG 엔진은 만들지 않는다.

**예: SK하이닉스 HBM 매출 추정**
```
inputs (전부 그래프 노드에 연결):
  · HBM ASP            ← product[HBM] observation
  · 하이퍼스케일러 CAPEX ← institution observation
  · HBM capa/수율       ← 수동 가정 (애널리스트 소유)
formula:  HBM매출 = capa × 수율 × ASP × 점유율
output:   SK하이닉스 HBM 매출 추정  → observation으로 기록 → valuation 입력 / 하류 모델 입력
```
ASP observation이 갱신되면 자동 리프레시.

---

## 스키마 사상 (테이블)

```
entities(id, type, name, aliases, meta)
entity_relations(src_id, dst_id, rel_type,
                 epistemic_type[fact|hypothesis],
                 confidence, source_doc_id,
                 valid_from, valid_to,
                 mechanism, reference_period, time_orientation,  -- 인과 서사·시점(D-021·D-023)
                 geo_scope)  -- 인과 주장의 장소 스코프(통제어휘, D-034). 노드는 보편 유지, 시공간은 엣지에.
observations(entity_id, date, metric, value, unit, source)
models(id, name, spec_json, output_entity_id)
-- 도메인 원본 테이블은 별도 유지: financial_statements, trade_*, stock_prices ...
-- 문서: raw_documents, enrichments, entity_links (문서↔엔티티)
```

새 렌즈 추가 = `type`/`rel_type` 값이 늘 뿐, 테이블 불변.
