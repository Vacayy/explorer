# 담당 유니버스 큐레이션 — 산업 맵(밸류체인)을 유니버스로 (action_thesis 후속)

> 2026-07-21. 상태: 착수. 배경: 애널리스트는 담당 섹터 유니버스를 갖고, 편입/편출은 별도 리서치로
> 수행한다(워크플로 ①). 통합 체인(D-036)의 시나리오 수혜 종목이 '유니버스 내'인지 '신규 후보'인지
> 태그하려면 안정적 유니버스가 필요. 결정: **산업 맵(industry_groups, 밸류체인)을 유니버스의 집으로**
> + **크로스체크 태그**(하드 필터 아님 — D-036 말뭉치 탈출을 안 깨뜨림). 대화 2026-07-21.

## 왜 새로 만드나 (기존 소스가 부적합)
- **산업 맵**(`industry_groups`/`industry_members`, 밸류체인 category): 목적에 맞는 홈이나 **비어 있음**.
- **KSIC**(`companies.sector`, 2,760종목): 완비하나 taxonomy 불일치(투자 테마 아님, D-023 기각 이유).
- **투자 섹터 엔티티**(389): 그래프·내러티브가 쓰나 섹터→종목 **멤버십 없음**(그래서 공동언급을 씀).
→ 유니버스는 **직접 큐레이션**한다. 방식 = **기계 제안(공동언급+RS·밸류) → 사람 필터/승인**(D-020·D-022).

## 데이터 (기존 테이블 재사용, 스키마 변경 없음)
- `industry_groups(id, name, description)` — 산업(투자 관점). 예: 반도체, 우주항공.
- `industry_members(group_id, stock_code, category, sort_order)` — category=밸류체인 단계(소재/부품/장비/…).

## 백엔드 (industries.py 확장)
- `POST /api/industries/` {name, description?} → 그룹 생성(기존엔 생성 엔드포인트 없음). 중복명 400.
- `GET /api/industries/{group_id}/propose?limit=30` → **기계 후보 제안**: 그룹명으로 `screen_beneficiaries`
  (공동언급+RS·밸류·관련도) 실행, **이미 멤버인 종목 제외**. 반환: BeneficiaryCandidate + 이미 없음 표시.
  사람이 체크 → 밸류체인 category 지정 → 기존 `POST /{group_id}/members`로 승인 적재.
- **크로스체크 헬퍼** `beneficiary.universe_membership(conn, codes)` → `{code: [group_name,…]}`
  (industry_members ⨝ industry_groups). `resolve_and_enrich` 출력에 `in_universe`(bool)·`universe_groups`
  (list) 추가 → 시나리오 수혜 종목이 유니버스 내인지 태그. **하드 필터 아님**: 유니버스 밖도 그대로
  '신규 후보(편입 검토)'로 노출(D-036 유지, 편입/편출은 사람의 별도 리서치=워크플로 ①).

## 프론트
- **IndustryPage 큐레이션**: '새 산업 그룹' 생성 + 선택 그룹에 '종목 후보 제안' → 후보 체크리스트
  (RS·밸류·공동언급·관련도 배지 + category 지정) → '선택 추가'. 기존 밸류체인 맵/멤버 삭제 그대로.
- **ScenarioBeneficiaries 태그**: 각 종목에 `유니버스: {group}` 배지(in_universe) 또는
  '신규 후보 · 편입 검토'(밖). 애널리스트의 커버리지 대비 이 이슈가 부른 종목 위치를 즉시 보여줌.

## 관통 원칙
- 기계는 제안, 사람은 승인(D-020·D-022) — 자동 확정 안 함. 유니버스 편입/편출은 사람 결정.
- 크로스체크는 태그일 뿐 필터가 아니다 — D-036의 '논리상 수혜(말뭉치 밖)' 노출을 유지.

## 남긴 후속
- KSIC↔투자섹터 매핑 보조 제안 · 밸류체인 category 자동 추론 · 유니버스 기반 정기 스크린/알림.

## 참조
industries.py · pipeline/beneficiary.py(screen_beneficiaries·resolve_and_enrich·universe_membership) ·
frontend IndustryPage.tsx·useIndustry.ts·CausalDetail.tsx(ScenarioBeneficiaries) · D-023·D-036 · 대화 2026-07-21
