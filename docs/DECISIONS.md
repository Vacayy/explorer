# Explorer — 의사결정 로그 (append-only)

> **규칙**: 이 파일은 결정의 *이유*를 보존하는 append-only 로그다.
> - 기존 항목은 **수정·삭제 금지**. 결정을 뒤집으면 새 항목으로 쓰고, 원 항목 끝에 `→ D-0XX에서 번복` 한 줄만 추가한다.
> - 최신 항목이 **맨 위**. 번호는 시간순 오름차순(다음 번호 = 최대 번호 + 1).
> - 기록 대상: 되돌리기 비싼 결정, 대안을 기각한 결정, "왜 이렇게 돼 있지?"가 나올 결정.
>   사소한 구현 선택·버그 수정은 커밋 메시지로 충분 — 여기 쓰지 않는다.
> - 형식: 결정 / 맥락·이유 / 기각한 대안 / 참조(커밋·파일·문서).
> - 현재 시스템 구조는 [SYSTEM.md](SYSTEM.md), 전략·지표는 [STRATEGY.md](STRATEGY.md), 우선순위는 [BACKLOG.md](BACKLOG.md).

---

## D-040 · 2026-07-21 · 액션 씨어리 순환 — 커버리지↔이슈 파급의 닫힌 고리 (종합)

**결정**: action_thesis를 하나의 **닫힌 순환**으로 정박한다. 개별 결정(D-036~039)이 이 고리의
조각들이며, 이 항목은 그 전체를 하나의 그림으로 종합·기록한다("왜 이렇게 돼 있지?"의 최상위 답).

```
  ①담당 유니버스 (커버리지, 구조: 산업그룹×밸류체인)   ← 애널리스트 워크플로 ①
        │  레퍼런스(안정적 커버 프레임)
        ▼
  ③이슈 발생 → scenario opus 파급 체인 → 논리로 수혜 종목 지목 (+왜)   ← 워크플로 ③, D-036
        │      (공동언급 통계 아님 = 말뭉치 최신편향 탈출)
        ▼
  크로스체크: 지목 종목이 '유니버스 내'인가 '신규 후보'인가   ← D-037 (태그, 하드필터 아님)
        │
        ├─ 유니버스 내 → 업사이드/하방 모델(D-035, 캐시)로 콜
        └─ 신규 후보 → ③→① 편입: 그룹×단계 골라 커버리지로 승격   ← 원목적 완성
                          │
                          └──────────▶ ①로 환류 (다음 이슈부턴 '유니버스 내'로 잡힘)
```

**맥락·이유**: 출발은 "문서 기반이라 이미 자주 회자된 과거에 갇힌다"는 함정(사용자 2026-07-21).
애널리스트는 언급 빈도가 아니라 **담당 커버리지 + 논리적 상상력**으로 이슈의 영향을 추론한다.
그래서 (1) 수혜 종목 선정을 공동언급→**파급 논리**로 바꾸고(D-036), (2) 논리 지목을 판단할 **안정적
레퍼런스**로 유니버스를 세우고(D-037), (3) 논리가 끌어올린 **유니버스 밖 신규 종목을 커버리지로 편입**해
고리를 닫았다. 이 순환이 있어야 시스템이 "말뭉치 안"에 머물지 않고 **이슈가 밀어올린 새 종목으로 커버리지가
계속 확장**된다 — 최신편향 탈출이 일회성이 아니라 지속 메커니즘이 되는 지점. 유니버스는 '또 하나의
watchlist'가 아니라 이 크로스체크의 레퍼런스이고(팔로우=능동 확신 subset, ★로 연결·D-039 후속),
캐시(D-038)로 매 진입 opus 재생성을 막아 순환을 값싸게 반복한다.

**비타협 규율(유지)**: 기계는 제안·사람이 승인(편입·팔로우 모두 수동, D-020·D-022) · 크로스체크는 태그일
뿐 하드필터 아님(신규 후보=말뭉치 밖 논리 수혜를 계속 노출, D-036 유지) · 업사이드는 범위+조건부
(거짓 정밀 금지, D-034) · 수혜 종착=섹터 규율은 그래프 물질화에만, 종목 지목은 콜 출력에만(D-023).

**남은 고리 보강(후속)**: 편입 직후 태그 즉시 갱신(현재는 재분석 시 반영) · 신규 후보 편입 큐(제안-승인
흐름으로) · 펀더+심리+기술 종합 '콜' 스코어(워크플로 ④) · 엑셀式 드라이버 유지모델.

**참조**: D-034(범위·거짓정밀)·D-035(업사이드 모델·캐시)·D-036(파급 논리 수혜)·D-037(유니버스
크로스체크)·D-038(시나리오 캐시)·D-039(유니버스=팔로우 모드) · pipeline/scenario.py·beneficiary.py ·
routers/spine_narrative.py·industries.py · frontend CausalDetail.tsx(ScenarioBeneficiaries·InductButton)·
UniversePage.tsx · docs/specs/action-thesis.md·universe-curation.md · 대화 2026-07-21

---

## D-039 · 2026-07-21 · 유니버스 페이지 = 팔로우 모드 신설 (구 산업 페이지 폐기)

**결정**: 담당 유니버스 큐레이션 UI를 **팔로우 모드의 새 서브탭 '유니버스'(`/follow/universe`, UniversePage)**로
신설한다. D-037에서 큐레이션을 얹었던 `/discover/industry`(IndustryPage)는 **이미 폐기된(nav 미노출)
휴지통 페이지**였음이 확인돼(사용자 2026-07-21), 그 페이지의 큐레이션 추가분을 원상복구(D-037 이전
상태로 `git checkout`)하고 새 집으로 이전. 팔로우 모드에 서브탭 신설(FOLLOW_TABS: 팔로우/유니버스,
ModeNavigation). 백엔드(industries create_group·propose·universe_membership)와 훅은 그대로 재사용 —
바뀐 건 프론트 홈뿐. UniversePage: 그룹 pill 선택 → 밸류체인 category별 멤버 + '새 산업 그룹'·'종목 후보 제안'
Dialog + 멤버 삭제.

**맥락·이유**: 팔로우(/follow)가 '내가 따라가는 것(종목·채널·태그)' 개인 커버리지 허브라, '담당 섹터
유니버스'와 성격이 같다 — 둘 다 사용자의 커버리지. 그래서 탐색/월드모델보다 팔로우가 개념적 집(사용자
선택). 구 산업 페이지에 얹은 게 실수였던 이유: 그 페이지가 nav에 없어 도달 불가한 죽은 화면이었음.

**기각한 대안**: ① 탐색에 탭 신설 — RS 산업 맵(/map) 옆이나 커버리지는 개인 성격이라 팔로우가 맞음
② 월드모델에 신설 — 시나리오 크로스체크와 가까우나 유니버스는 커버리지(팔로우)지 인과 그래프가 아님
③ 구 산업 페이지 되살리기 — 사용자가 이미 폐기한 화면.

**참조**: frontend/src/components/follow/UniversePage.tsx · hooks/useIndustry.ts(useRemoveMember 추가) ·
layout/ModeNavigation.tsx(FOLLOW_TABS)·App.tsx(/follow/universe) · IndustryPage.tsx(큐레이션 원복) ·
D-037(유니버스 큐레이션 백엔드·데이터) · 대화 2026-07-21

---

## D-038 · 2026-07-21 · 파급 시나리오 캐시 — 내러티브 버전 기반 (매 클릭 opus 재생성 방지)

**결정**: 파급 시나리오를 `scenarios` 테이블(topic PK · answer · beneficiaries · citations ·
narrative_version)에 캐시한다. `GET /api/spine/narrative/scenario`(저장분 즉시, LLM 0) +
`POST /scenario/compute`(기반 내러티브 버전이 동일하면 저장분 반환, `refresh=1`일 때만 opus 재생성).
내러티브 버전이 캐시 시점과 다르면 `stale` 플래그(재분석 권장). 프론트: 진입 시 저장분 자동 표시 +
'다시 분석' 버튼(refresh) + '저장분 {날짜}'·stale 힌트. upside 캐시(models, D-035)와 같은 철학.

**맥락·이유**: 파급 분석은 opus 심층 추론이라 콜드 ~85초. 내러티브가 안 바뀌었는데 진입/재방문마다
새로 돌리는 건 낭비이자 UX 저하(사용자 지적 2026-07-21). 무효화 키를 **내러티브 버전**으로 잡은 이유:
시나리오의 event가 최신 내러티브 title에서 파생되고 내러티브가 doc_ids_hash로 이미 멱등 버전 관리되므로,
버전이 그대로면 입력이 그대로 = 재생성 불필요. 문서 집합 자체 해시 대신 버전을 쓴 건 단순·일관(내러티브
갱신이 곧 재분석 트리거). 강제 갱신은 사람이 '다시 분석'으로만 — 자동 재생성 폭주 방지.

**기각한 대안**: ① 무캐시(현행) — 매 클릭 opus, 낭비 ② TTL 시간 만료 — 내러티브 안 바뀌면 무의미한 재생성
③ 문서집합 해시 무효화 — 내러티브 버전과 중복(내러티브가 이미 doc 해시로 버전업), 복잡도만 증가.

**참조**: backend/database.py(scenarios 테이블) · routers/spine_narrative.py(scenario_cached·scenario_compute
캐시 가드) · pipeline/scenario.py(build_scenario 순수 계산 유지) · frontend NarrativePage.tsx(ScenarioSection
저장분+다시 분석) · D-035(upside 캐시)·D-036(통합 체인 beneficiaries) · 대화 2026-07-21

---

## D-037 · 2026-07-21 · 담당 유니버스 = 산업 맵(밸류체인) 큐레이션 + 크로스체크 태그 (하드 필터 아님)

**결정**: 애널리스트의 '담당 섹터 유니버스'(워크플로 ①)를 **산업 맵**(`industry_groups`/`industry_members`,
category=밸류체인 단계)에 담는다. 기존 소스가 부적합해 **직접 큐레이션**: KSIC(`companies.sector`)는
taxonomy 불일치(D-023), 투자 섹터 엔티티(389)는 멤버십 없음, 산업 맵은 목적 맞으나 비어 있었음.
방식 = **기계 제안 → 사람 승인**(D-020·D-022): `GET /api/industries/{id}/propose`가 그룹명으로
`screen_beneficiaries`(공동언급+RS·밸류·관련도, 기존 멤버 제외) 후보를 내고, 사람이 체크·밸류체인 단계
지정 후 `POST members`로 적재. 그룹 생성 `POST /api/industries/`(신규, 이름 UNIQUE). 통합 체인(D-036)의
시나리오 수혜 종목은 `universe_membership`으로 `in_universe`·`universe_groups` **태그** — '유니버스 내'
vs '신규 후보(편입 검토)'. **크로스체크는 태그일 뿐 하드 필터가 아니다**: 유니버스 밖의 '논리상 수혜'도
그대로 노출해 D-036의 말뭉치 탈출을 안 깨뜨린다. 스펙: docs/specs/universe-curation.md.

**맥락·이유**: 유니버스가 있어야 이슈 수혜 종목이 '내 커버리지 안인지 밖(편입 검토)인지'를 애널리스트처럼
판단한다. 하드 필터로 하면 안정성은 얻지만 D-036이 막 열어젖힌 '아직 회자 안 된 논리상 수혜'를 다시
가두므로, 유니버스는 **안정적 커버리지(①)**로 두고 편입/편출은 사람의 별도 리서치로 남긴다(태그만).
기계 후보엔 공동언급 노이즈(반도체에 금호타이어 등)가 섞이는데, 이는 결함이 아니라 '사람이 필터한다'는
설계의 전제 — 자동 확정하지 않는 이유.

**기각한 대안**: ① KSIC 그대로 유니버스 — taxonomy 불일치 ② 투자 섹터 엔티티 자동 멤버십 — 공동언급
자동 확정은 노이즈 유입(사람 승인 우회) ③ 유니버스 하드 필터 — D-036 말뭉치 탈출 무효화 ④ 새 테이블 —
산업 맵이 이미 그룹/밸류체인 구조를 가짐, 재사용.

**참조**: docs/specs/universe-curation.md · backend/routers/industries.py(create_group·propose_members) ·
pipeline/beneficiary.py(universe_membership·resolve_and_enrich 태그) · frontend IndustryPage.tsx·
useIndustry.ts·types(IndustryCandidate)·CausalDetail.tsx(태그 배지) · D-020·D-022·D-023·D-036 · 대화 2026-07-21

---

## D-036 · 2026-07-21 · 통합 체인 — 수혜 종목을 '문서 공동언급'에서 '파급 논리'로 (말뭉치 최신편향 탈출)

**결정**: 이슈→수혜 종목→업사이드를 **한 체인**으로 잇되, 통합 체인의 수혜 종목 선정은 공동언급 통계가
아니라 **scenario opus가 파급 논리로 직접 지목**한다. `build_scenario`가 같은 콜에 `beneficiaries`
`[{name, rel:수혜|피해, reason}]`를 산출(파급 체인에서 왜 영향받는지 한 문장) →
`beneficiary.resolve_and_enrich`가 종목명을 종목코드로 resolve(company 엔티티 `name`/`aliases`, fallback
`companies.corp_name`) + RS·per·pbr·시총·52주 enrich, 미해소는 이름·이유만. `ScenarioResult.beneficiaries`로
반환, NarrativePage 파급 시나리오 섹션이 파급 마크다운 아래 **논리 기반 수혜/피해 종목**(이유 + RS·밸류 +
'업사이드' 버튼=upside 모델)으로 렌더. 기존 공동언급 `BeneficiaryList`는 '언급 상위(참고)'로 병존(리네이밍).

**맥락·이유**: 수혜 종목을 문서 공동언급으로 고르면 **이미 자주 언급된 과거에 갇힌다** — 새 이슈의 파급으로
논리상 수혜인데 아직 회자 안 된 종목을 놓친다(사용자 지적 2026-07-21). 애널리스트는 언급 빈도가 아니라
**담당 유니버스 + 논리적 상상력**으로 영향을 추론한다(애널리스트 워크플로 ③). LLM(opus)의 인과 추론을
종목 지목에 쓰면 말뭉치 밖의 논리상 수혜까지 잡는다 — 검증: HBM 시나리오가 한미반도체·주성엔지니어링·
이수페타시스 등 공급망 하위 종목을 논리로 지목(공동언급 스크린이 놓칠 것). 사용자 선택지 중 '시나리오
인과 논리'(하이브리드·섹터 유니버스 대비) 채택. 그래프 물질화의 **수혜 종착=섹터 규율(D-023)은 유지** —
개별 종목 지목은 애널리스트 '콜'용 출력(beneficiaries 필드)에만, 그래프 엣지엔 물질화 안 함.

**남긴 후속(연구급)**: 펀더+심리(salience×conviction)+기술 종합 '콜' 스코어 · 엑셀식 드라이버 유지모델
(docs/references/Krafton_1Q25… = CLSA式 살아있는 모델, 현 1회성 opus 범위와 층 다름) · 섹터 유니버스
편입/편출 리서치.

**기각한 대안**: ① 공동언급 유지 — 말뭉치 최신편향, 함정 그대로 ② 섹터 유니버스 기반(companies.sector) —
'담당 유니버스'에 가장 충실하나 섹터 매핑 큐레이션 선행 필요, 후속으로 ③ 하이브리드(공동언급 풀+논리 필터)
— 여전히 공동언급 풀에 갇힘.

**참조**: docs/specs/action-thesis.md(Phase 3 계약) · pipeline/scenario.py(beneficiaries 프롬프트·파싱) ·
pipeline/beneficiary.py(resolve_and_enrich) · routers/spine_narrative.py(ScenarioResult) ·
frontend CausalDetail.tsx(ScenarioBeneficiaries)·NarrativePage.tsx · D-023(수혜 종착=섹터)·D-034·D-035 · 대화 2026-07-21

---

## D-035 · 2026-07-21 · action_thesis — 이벤트→수혜 종목→조건부 업사이드/하방 (에이전트화 다음 단계)

**결정**: 갖춰진 준비물(주가·재무·RS·인과 그래프·내러티브·scenario 엔진·falsifier·lenses)을 하나의
**액션 명제**로 엮는다 — "이벤트 터지면 뭘 사고, 업사이드/하방 얼마인지"(사용자 피드백 2026-07-21).
플로우: 이벤트/신호 → scenario 파급 → 수혜 섹터 → **종목 후보(문서 공동언급+RS·밸류)** →
업사이드(모델링: 매출 P×Q·Capa·TAM→이익률→EPS→적정주가, 불확실하면 멀티플) →
하방(펀더멘탈 지지선 대비 현재가, 비대칭 프레이밍) → 매매(추세추종 렌즈) →
**범위+조건부** action_thesis 카드 → 홈 승인. 스펙: docs/specs/action-thesis.md.
**Phase 1 착수 = 수혜 섹터→종목 스크린만** (결정적·LLM 0). 나머지는 후속 Phase.

**맥락·이유**: 이 시스템의 구조적 강점(연속 수집→인과 그래프)이 "애널 안 기다리는 실시간 대응"을
가능케 한다 — scenario 엔진이 이미 이벤트→수혜 섹터를 함. **범위+조건부 표현 못박음**(point target은
거짓 정밀, 시장은 물리 아님 — D-034 연장). 정량(업사이드 모델링)은 이벤트로 스코프된 소수 종목에만
(ontology.md models 층, 애널리스트 소유 가정). "기계는 제안, 사람은 승인" 유지(D-020·D-022). 무효화
조건은 falsifier 재활용. 매매 타이밍은 기업 질과 분리(추세추종) — "좋은 기업 ≠ 좋은 종목". **품질
경고**: 액션 카드 품질은 밑바닥 그래프 품질이 상한(정체성·상류 인과·커버리지) — 얇은 위에 얹으면
'자신만만한 오답'(돈 걸림). 불확실성 정직한 v1부터.

**섹터→종목 연결 = 문서 공동언급** (MEMBER_OF는 KSIC라 투자언어 테마와 taxonomy 불일치 — research_candidates 검증 패턴 재사용).

**기각한 대안**: ① point target 업사이드 — 거짓 정밀 ② 범용 전종목 정량 모델 — 파라미터화 불가·false precision, 이벤트 스코프 소수만 ③ 자동매매 — 영구 out(제안-승인 철학) ④ MEMBER_OF로 섹터→종목 — taxonomy 불일치.

**참조**: docs/specs/action-thesis.md · pipeline/scenario.py·research_candidates.py(_rs_short·공동언급) · pipeline/beneficiary.py(신규 Phase 1) · falsifiers·lenses · ontology.md(models) · D-020·D-022·D-023·D-034 · 대화 2026-07-21

---

## D-034 · 2026-07-20 · 인과 주장에 장소 정박 — geo_scope 엣지 스칼라 (보편 노드 + 스코프 있는 엣지)

**결정**: 인과 노드는 시간·장소 없는 **보편 개념**으로 유지하고(A방향), 인과 주장(엣지)에 **`entity_relations.geo_scope`(통제어휘 스칼라)를 추가** — 시간 `reference_period`과 대칭. 통제어휘 `한국|미국|중국|유럽|일본|대만|글로벌|기타`(프리폼 파편화 방지, D-033 교훈), 공용 상수 `GEO_VOCAB`(narrative.py)를 추출 프롬프트 3곳(narrative·doc_causal·scenario)이 공유, `_norm_geo`로 어휘 밖 값은 None. 적재는 `_persist_causal` 한 곳(INSERT + 기존엣지 COALESCE). 기존 ~1,352 엣지는 `scripts/backfill_geo_scope.py`(haiku 배치, dry-run→apply, 애매하면 null 유지). 프론트: 노드 상세에 "관측 시점·지역" 집합 + 각 인과 행·엣지 상세에 geo 배지. 스펙: docs/specs/geo-scope.md.

**맥락·이유**: "전력요금 인상" 같은 보편 노드가 "언제·어디서?"가 없어 정보 가치가 약하다는 지적(대화 2026-07-20). 시간은 이미 엣지에 있었으므로(D-021·D-023) 장소도 엣지에 대칭으로 붙이는 게 일관된다. 노드를 개별 사건("2026 한국 전력요금 인상")으로 쪼개는 대안은 노드 폭발·반복 패턴 상실로 기각 — 보편 노드는 재사용·반복 패턴 인식이라는 이 도구의 강점을 지킨다. **범위 규율**: geo_scope는 인과 주장을 시공간에 *위치*시키는 것이지 영향 *계산*(전파·시차·크기)이 아니다 — 정량 exposure 추론(호르무즈式 "각국 영향도")은 geo 태그가 아니라 가중 의존 그래프(geo 1급 노드 + DEPENDS_ON, observations, models)를 요구하는 별도 종의 시스템이며, 시장은 물리가 아니라 반사적 도메인이라 결정론적 시뮬레이션은 거짓 정밀 위험(대화 2026-07-20). 정량은 좁은 렌즈에만.

**기각한 대안**: ① 개별 사건 노드(token) — 노드 폭발·dedup·반복성 상실 ② geo 1급 노드/OCCURS_IN 즉시 활성화 — 시간이 노드가 아닌데 geo만 노드면 비대칭, 추출·dedup·UI 비용 큼(정량 exposure가 실제 목표일 때 별도 트랙) ③ 프리폼 geo — 지명 파편화(서울/한국/코리아), 통제어휘로 방어 ④ 억지 지정 — 애매한 엣지는 null 유지(거짓 정밀 방지).

**참조**: docs/specs/geo-scope.md · backend/database.py(geo_scope 마이그레이션) · backend/pipeline/narrative.py(GEO_VOCAB·_norm_geo·_persist_causal·추출 프롬프트·causal_subgraph) · doc_causal.py·scenario.py(프롬프트) · narrative_graph.py(full_causal_graph) · routers/spine_causal.py · scripts/backfill_geo_scope.py · frontend WorldviewPage.tsx·graph/types.ts · D-021(시간 정박)·D-023(인과=시간 종속)·D-033(파편화 교훈) · 대화 2026-07-20

---

## D-033 · 2026-07-19 · 어휘 통합 — theme·macro 파편화 치유 (승격 루프 소생)

**결정**: 인과 그래프 추상 노드(theme·macro)의 표기 파편화를 **배치 병합 + 쓰기 시 리다이렉트**로 치유한다(스펙: docs/specs/vocab-consolidation.md). ① `entity_merges` 테이블(audit+redirect 겸용) ② `pipeline/vocab.py` — fastembed 코사인(≥0.90, 같은 type 내) 후보 → sonnet 배치 쌍 판정(same/different, "수준·방향·시점 다르면 different, 애매하면 different") → survivor(인과 엣지 참조 多, 동률이면 오래된 id)로 FK 전수 재배선(PRAGMA 동적 발견; entity_relations는 UNIQUE 충돌 시 confidence=max·메타 non-null 우선으로 엣지 병합 + narrative_edge_evidence 이관) 후 loser 삭제 ③ `scripts/consolidate_vocab.py` — dry-run(기본)이 계획을 출력·저장, 사람 검토 후 `--apply`가 그 계획 그대로 적용(LLM 재호출 없음) = D-020 "기계는 제안, 사람은 승인"의 CLI 배치 승인 ④ `_resolve_or_create_node`가 병합으로 사라진 이름을 entity_merges로 survivor에 해소(재파편화 방지).

**맥락·이유**: 온톨로지 점검(2026-07-19, MS Ontology-Playground 대비 교차검증)에서 실측 — theme 745·macro 149 중 근접 중복 다수("AI 고점론"/"AI 거품론·고점론", "AI Agent"/"AI 에이전트", "금리 상승"/"연준 금리인상"류), 그 결과 인과 엣지 1,283개 중 corroborated(2+) 35개, **지식 승격 0건** — 같은 주장이 다른 노드로 갈라져 교차확인 카운트가 쪼개지면서 Phase 2 §2-5 내러티브↔지식 루프가 한 번도 발화하지 못했다. D-023이 방어책으로 명시한 "임베딩 dedup"은 실제 구현된 적 없음(_resolve_or_create_node는 정확 이름 매칭뿐). 진단 결론: 표현 스키마는 건전(형식 온톨로지 방향은 퇴행), 병목은 어휘 정체성 — 가장 싼 레버로 죽은 승격 루프를 살린다. 원칙: **쓰기 시 = 결정적 해소, 배치 = 의미적 치유** (쓰기 경로에 임베딩·LLM 금지).

**기각한 대안**: ① ApprovalsCard 쌍별 승인 UI — 1회성 백필 수십 쌍에 UI 과투자, CLI dry-run 검토가 같은 승인 원칙을 더 싸게 충족 ② 쓰기 시 임베딩 유사 노드 재사용 — 쓰기 경로가 느려지고 비결정적, 배치 치유로 충분 ③ soft-merge(merged_into 컬럼로 tombstone 유지) — 모든 읽기 경로가 tombstone 필터를 알아야 함, 재배선+삭제+redirect 테이블이 더 단순 ④ company 포함 — 정체성 semantics가 다르고(종목코드) 승격 루프를 죽이는 건 추상 노드, 별도 트랙.

**참조**: docs/specs/vocab-consolidation.md · backend/pipeline/vocab.py · scripts/consolidate_vocab.py · backend/database.py(entity_merges) · backend/pipeline/narrative.py(_resolve_or_create_node redirect) · D-023(임베딩 dedup 설계)·D-020(승인 원칙)·D-028(배치=sonnet 티어 논리) · 온톨로지 점검 대화 2026-07-19

---

## D-030 · 2026-07-19 · 세계관 완성도 — 노드 중력(pace_layer) + 정전(canon) 지식층

**결정**: 인과 그래프가 "평평하고(모든 노드 동일 무게) 뿌리가 없는(시간 지평이 수집 30일+미래 전망뿐)" 문제를 4층으로 해소한다. 실측 근거: '세계질서 재편'(시대의 중력급 힘)이 out=6·**in=0**으로 설명되지 않는 출발점이고, 전 그래프의 reference_period가 2026~2030뿐이며, 프롬프트가 뽑는 layer(event~regime)를 `_persist_causal`이 폐기 중.

① **Layer 0 — 노드 중력 물질화**: 이미 추출되는 `layer ∈ event·flow·cycle·structure·regime`을 `entities.meta_json`에 저장(Phase 1 스펙 §2-1 예고분 이행). 기존 인과 노드는 haiku 배치 백필. 세계관 뷰에서 layer별 시각 무게(regime 크게/짙게), 순회 루트 정지를 위상적 소스 → **regime/structure 도달 시 정지**로 정밀화.
② **정전(canon) 지식층**: `vault/canon/`에 사람+Claude가 작성한 요약 노트(원저 통째 수집 금지 — 저작권+발췌 철학)를 `source_type='canon'`으로 흡수. 시간 정박은 D-021 그대로 — published_at(정리일)이 아니라 역사적 reference_period(2001, 2011, 2018…). 감쇠는 기존 LAYER_DECAY의 regime(0.1)이 자연 처리 — 늙지 않는 지식.
③ **역사 인과 체인**: canon 노트에서 인과 추출해 그래프의 뿌리 확장 — `epistemic_type='observed'`(신규 중간 티어: 시장 가설(hypothesis)보다 강하고 순수 사실(fact)보다 약한 '널리 수용된 역사 해석'), 높은 confidence, 과거 reference_period. '세계질서 재편'이 뿌리 없는 소스에서 "중국 WTO 가입(2001)→…→칩스액트(2022)→현재"의 사반세기 체인의 현재 단면이 된다.
④ **해석 렌즈 확장**: 책의 프레임워크(투키디데스 함정·지리결정론·화폐사 사이클·멱법칙 등)는 그래프 노드가 아니라 `lenses.py`(멍거 격자)로 — 프롬프트 주입 렌즈.

**핵심 규율 — 사실은 그래프로, 프레임은 렌즈로**: 역사적 사실 체인(관세 부과 2018 — 일어난 일)과 해석 프레임(투키디데스 함정 — 하나의 관점)을 다른 층에 넣는다. 프레임을 corroborated 지식으로 넣으면 반증 규율(D-022)과 충돌 — 정전도 관점이다(사피엔스·총균쇠 모두 학술 논쟁 존재).

**모델 배분**: canon 노트 작성=Fable 5(세션 직접, 고지능 종합) · canon 인과 추출=opus(깊은 다단 인과, 소량) · 기존 노드 layer 백필=haiku 배치(좁은 분류, 대량) · 신규 노드 layer=기존 생성 프롬프트에 편승.

**진행 규율**: 볼륨 규율 — 20권 일괄 주입 금지, '세계질서 재편'(stakeholder 지목 최강 중력) 하나로 파일럿 → 기존 그래프(지정학·미-이란·CPTPP·AI 수출통제 노드)와의 연결·내러티브 품질 개선 검증 후 화폐사·전쟁사·실리콘밸리사 확장.

**기각한 대안**: ① 노드 무게를 degree 등 창발 지표로만 — 창발은 수집 편향에 종속(많이 언급=무겁다는 보장 없음), 추출된 layer가 더 정직 ② 책 원문 통째 수집 — 저작권+발췌 철학 위배 ③ 프레임까지 그래프 노드로 — 반증 규율 충돌(위 핵심 규율) ④ 한 번에 다권 주입 — 검증 없는 스케일업.

**참조**: 대화 2026-07-19(스테이크홀더 제안: 전문 지식 뼈대 주입 — 현대사·사회사·화폐사·전쟁사·실리콘밸리사) · pipeline/narrative.py(_persist_causal)·lenses.py·doc_causal.py · D-021(시간 정박)·D-022(반증 규율)·D-023(물질화)·narrative-causal-phase1.md §2-1(layer 적재 예고)

---

## D-032 · 2026-07-19 · 메가 내러티브 층 — 공유노드 군집의 상위 세계관 서사 (D-023 §2-4 완성)

**결정**: 토픽 내러티브(원자, 버전·드리프트 추적 단위)는 유지하고, **인과 노드를 공유하는 내러티브 군집(연결요소, 크기 3+)마다 상위 '세계관 서사'를 생성**하는 층을 신설한다(pipeline/mega_narrative.py). 계량 근거: 살아있는 내러티브 15개 중 10쌍이 노드 공유, 공유 노드가 'AI 데이터센터 투자·전력수요·빅테크 CAPEX'로 수렴 — 대부분이 단일 메가 서사의 sub-story라는 stakeholder 직감이 실측으로 확인됨. 저장은 narratives 테이블 재사용(kind='mega', topic=군집 라벨(LLM 명명), members_json=구성 토픽, doc_ids_hash=멤버 (topic,id) 해시) — 멤버 구성/버전 변경 시에만 opus 재생성(기존 게으른 패턴). 표면: 내러티브 랜딩 최상단 '세계관' 카드(구성 토픽 배지→sub-story 딥링크, Collapsible 전문). cron은 compute_narratives 끝에 편승. 첫 실행: 'AI 전력 슈퍼사이클'(7개 서사)·'AI 컴퓨트 슈퍼사이클'(3개) 생성.

**맥락·이유**: topic당 1내러티브 구조는 원자 단위로는 옳지만 층이 하나 비어 있었다 — D-023 §2-4가 "머지 = 공유 서브그래프 = 상위 세계관 내러티브"를 설계해놓고 뷰(related·worldview 그래프)만 구현되고 서사 생성은 미완이었다. sub-story 개별 follow-up은 유지(각자의 드리프트가 신호), 읽는 층위만 하나 추가.

**기각한 대안**: ① 계층 트리(parent_id) — 그래프가 소속을 더 유연하게 인코딩, 토픽이 군집을 옮길 때 트리는 경직 ② 노드 공유 2+ 임계 — 실측상 허브 노드 1개 공유(AI 데이터센터 투자)가 이미 강한 신호, 2+면 군집이 잘게 쪼개짐 ③ 지식 세계관 브리핑(D-019)에 통합 — 그건 느린 층(지식) 종합, 메가는 빠른 층(내러티브) 종합으로 층이 다름(CLS 두 속도), 별도 유지.

**참조**: pipeline/mega_narrative.py · narratives(kind·members_json) · GET /api/spine/narrative/mega · NarrativePage.tsx(MegaNarrativeSection) · scripts/compute_narratives.py 편승 · D-023 §2-4 · D-019 · 군집 실측 대화 2026-07-19

---

## D-031 · 2026-07-19 · IA 재편 — '월드모델' 모드 신설(내러티브·세계관·지식), 신호에서 분리

**결정**: 최상위 네비(L1)에 **'월드모델' 모드**를 신설하고, 그 아래 `내러티브 · 세계관 · 지식` 3서브탭을 둔다. 기존에 내러티브·세계관은 탐색 '신호'(/explore) 착륙 페이지 안에 묻혀 있었고 지식만 탐색 서브탭이었다 — 셋을 신호에서 떼어내 한 모드로 통합. URL은 그대로 유지(/narrative, /narrative/worldview, /knowledge — 리다이렉트·딥링크 보존), 모드 그룹핑은 네비 계층에서만 처리. `/narrative`는 topic 없이 진입 시 내러티브 목록 랜딩(신규), `?topic=`이면 기존 상세. 신호 페이지엔 내러티브 **티저(상위 3개+월드모델 링크)** 만 남긴다. 지식은 탐색 서브탭에서 제거.

**맥락·이유**: D-023에서 정의한 대로 **내러티브(빠른 층)와 지식(느린 층)은 "같은 인과 그래프의 두 속도"** 이고 세계관 뷰는 그 인과 그래프 자체의 시각화 — 셋은 한 몸(월드모델)이다. 반면 '신호'는 변화 감지(delta/스크리닝) 표면이라 성격이 다르다. 흩어져 있던 셋을 개념적으로 한곳에 모아 "세계 모형을 보는 곳"과 "변화를 훑는 곳"을 IA에서 분리(stakeholder, 2026-07-19). 목록 렌더는 신호 티저와 월드모델 랜딩이 공유하도록 `NarrativeList` 컴포넌트로 추출(중복 제거).

**기각한 대안**: ① 탐색 서브탭으로 승격(신호 옆에 내러티브·세계관 추가) — 탐색 탭이 비대해지고 "한 몸(월드모델)" 신호가 희석 ② URL도 /worldmodel/* 로 재구성 — 딥링크 다수·리다이렉트 유지비용 대비 이득 적음(네비 그룹핑만으로 충분) ③ 세계관을 내러티브 하위 상세로 유지 — 세계관은 전역 그래프라 특정 내러티브의 하위가 아님, 형제 서브탭이 맞음.

**참조**: frontend/src/components/layout/ModeNavigation.tsx(worldmodel 모드+WORLDMODEL_TABS+getActiveMode/SubTab) · frontend/src/components/explore/NarrativeList.tsx(신규 공유) · NarrativePage.tsx(목록 랜딩) · ExplorePage.tsx(티저 축소) · WorldviewPage.tsx(뒤로가기 제거) · docs/SYSTEM.md IA · D-023(두 속도 원칙)

---

## D-029 · 2026-07-19 · both_temporal 판정을 엣지에 물질화 — feedback_note (contested 오탐 해소)

**결정**: contested_edge 제안을 승인해 opus가 `both_temporal`(역방향 CAUSES 쌍이 상충이 아니라 시점 다른 피드백 나선, D-027)로 판정하면, 그 판정을 두 엣지의 **`entity_relations.feedback_note`(신규 컬럼)에 물질화**한다(근거 rationale 저장). 그리고 세계관 뷰·서브그래프의 `contested` 온더플라이 계산(narrative_graph.py·narrative.py)이 **feedback_note 있는 엣지를 contested에서 제외**한다. 이미 승인된 both_temporal 제안은 `scripts/backfill_feedback_edges.py`로 노드 이름 매칭해 소급 반영.

**맥락·이유**: 기존 both_temporal 분기는 "둘 다 유지"만 하고 **아무것도 기록하지 않아**, opus의 판정·근거가 `agent_proposals.result_json`에만 갇혀 사실상 버려졌다(승인 목록은 status='proposed'만 노출 → 다시 볼 화면 없음). 더 심각한 건 엣지에 흔적이 안 남아 `contested` 계산이 이 쌍을 **여전히 상충으로 오탐**한다는 것 — 같은 엣지가 세계관 뷰에서 flywheel(자기강화 루프, SCC 감지)이면서 동시에 contested(빨간 상충)로 **모순된 신호**를 냈다. D-023의 "판정을 그래프에 물질화" 원칙 위반. 엣지는 upsert(삭제 없이 UPDATE, id 안정)라 feedback_note가 재계산에도 살아남는다.

**기각한 대안**: ① result_json에만 두기(현행) — 근거 유실·contested 오탐 지속 ② mechanism에 근거 덧쓰기 — 엣지별 인과 서사(mechanism)를 쌍 단위 판정으로 오염 ③ 별도 boolean 플래그 + 근거 분리 컬럼 — nullable TEXT 하나로 플래그(non-null)+근거를 겸하면 충분, 컬럼 최소화 ④ opus가 두 reference_period를 반환해 시점 자체를 채우기 — 더 완전하나(D-027 이상형) 프롬프트·구조화 출력 변경 필요, 이번 범위 밖(후속).

**참조**: backend/database.py(feedback_note 마이그레이션) · backend/pipeline/agent_proposals.py(_resolve_contested) · backend/pipeline/narrative_graph.py·narrative.py(contested 계산+노출) · backend/routers/spine_causal.py · frontend/src/components/explore/WorldviewPage.tsx · scripts/backfill_feedback_edges.py · D-027(반사성 나선) · D-023(물질화 원칙)

---

## D-028 · 2026-07-18 · 지능 깔때기 해소 — 배치 재태깅(sonnet)·커버리지 트리거·문서 레벨 인과 추출

**결정**: 수집(2주간 2,000+건)에 비해 지능층(인과 그래프 60엣지·지식 10건)이 못 자라는 갭의 원인을 깔때기 실측으로 진단하고 3개 레버로 해소한다. ① **배치 재태깅** — keyword 폴백 1,524건(전체의 67%)을 문서 10건/콜 배치로 LLM 재태깅. 모델: **배치 백필=sonnet, 증분 cron 단건=haiku 유지**. 단건 태깅은 haiku로 741건 검증된 좁은 작업이지만, 배치는 여러 문서를 한 응답에서 혼동 없이 분리 태깅해야 해(멀티 문서 구조화 출력) 지시 추종 요구가 높고, 1회성 토대 작업이라 품질이 이후 모든 지능의 상한이 됨. ② **커버리지 트리거** — compute_top_narratives가 theme_surge 상위 5만 보던 것에 "30일 문서 풍부(기준치+) & 내러티브 부재/오래됨" 트리거 추가(사이클당 +2 순환, 문서유형 라벨 제외). 반도체 725건·자동차 316건 등이 내러티브 0인 문제 해소 — 내러티브가 늘어야 공유 노드가 생겨 교차검증(corroboration)이 작동하기 시작한다(2026-07-18 기준 60엣지 전부 단일 출처). ③ **문서 레벨 인과 추출** — 인사이트 밀도 높은 문서에서 인과 엣지 직접 추출(source_doc_id, 내러티브와 독립된 제2 공급원). 별도 스펙 docs/specs/doc-causal-extraction.md.

**맥락·이유**: 깔때기 실측(2026-07-18) — 수집 2,265건 → LLM 태깅 741건(33%, ①에서 67% 유실) → 내러티브 소화 108건(~5%, ②에서 95% 유실) → 인과 추출 경로는 내러티브 하나뿐(③). "양질 인사이트가 쌓이는데 지능이 안 큰다"(stakeholder)의 기계적 원인. 재태깅이 안 밀린 이유는 문서당 claude -p 콜드스타트(HANDOFF §6 기록) — 배치가 해법.

**기각한 대안**: ① 지켜보기(축적 대기) — 병목이 축적량이 아니라 소화 기관 구조라 대기는 무익 ② 재태깅 병렬화(워커 N개) — 콜드스타트 오버헤드가 콜 수만큼 그대로, 배치가 콜 수 자체를 1/10로 ③ 전 문서 sonnet 상시 태깅 — 증분 경로는 haiku로 충분(검증됨), 비용 낭비.

**참조**: scripts/backfill_enrich_batch.py · pipeline/enrich.py(enrich_batch) · pipeline/narrative.py(compute_top_narratives 커버리지 트리거) · docs/specs/doc-causal-extraction.md · 깔때기 실측 대화 2026-07-18

---

## D-027 · 2026-07-18 · 인과 그래프 표현력 — 반사성 나선 이행 + person/company 중간 행위자 (D-023 정제)

**결정**: ① **반사성(나선) 이행** — D-023 하위결정 5("피드백은 사이클이 아니라 같은 노드의 다른 시점 두 엣지")는 설계만 있고 구현이 없었다(프롬프트가 '순환 금지'만 말하고 시간으로 펴는 법을 안 가르침 → 역방향 쌍 0개 실측). 내러티브 프롬프트에 나선 추출 지침(피드백 발견 시 reference_period가 전진하는 두 엣지로), 순회를 노드 방문집합 → 엣지 방문집합으로 변경(시간-합법적 재방문 허용), 세계관 뷰에 플라이휠(자기강화 루프) 감지·표시. 젠슨 황의 스케일링 법칙 순환(에이전틱 AI→합성 데이터→사전학습→더 강한 AI)이 대표 사례 — AI 시대의 핵심 메커니즘인 자기강화를 담는다. ② **person/company 중간 행위자 허용** — 인과의 뿌리·중간에 특정 인물의 선언/비전/자본배분(젠슨 황·머스크류 매니페스터)이나 특정 기업의 결정이 메커니즘의 실체면 person/company 노드로 명시. 판별 기준: "그 사람/기업이 사라지면 이 인과가 약해지는가" — 논평가·스쳐가는 언급은 탈락. **수혜 종착 = 섹터 원칙은 유지** (D-023 하위결정 3 번복 아님 — 그 결정이 기각한 건 '수혜 끝을 종목으로 강제'이고, 중간 사슬 행위자는 수혜 예측이 아니라 관측·반증 가능한 동인).

**맥락·이유**: ① 세상은 결과가 원인에 되먹임하는 복잡계인데(stakeholder, 2026-07-18) 단방향 DAG 서술만으로는 AI 시대 최강 메커니즘(자기강화 플라이휠)을 못 담는다. D-023이 이미 답(시간으로 풀기)을 설계했으므로 새 결정이 아니라 미완 이행. ② 매니페스터 인과(믿음을 경유하는 인과 — 선언이 실현 전부터 시장을 움직임)는 선행 신호라서 "이미 반영됐나 vs 아직 안 왔나"(D-022 salience×conviction 갭)를 읽는 눈이 하나 더 생긴다. 구조주의(구조가 역사를 만든다)만 있고 행위자(인물이 미래를 선언하고 실현한다) 축이 없던 세계관의 보완.

**기각한 대안**: ① 새 rel_type(SHAPES/MANIFESTS) 신설 — 온톨로지 파편화, CAUSES+mechanism 서술로 충분 ② 사이클 허용 그래프 — D-023에서 이미 기각(무한루프·루트/종착 모호) ③ 모든 인물 발언을 person 노드로 — 소음 오염, "사라지면 약해지는가" 기준으로 방어.

**참조**: D-023(하위결정 3·5) · pipeline/narrative.py(_build_prompt) · pipeline/narrative_graph.py(엣지 방문집합·플라이휠) · 젠슨 황 렉스 프리드먼 인터뷰 논의(대화 2026-07-18)

---

## D-026 · 2026-07-18 · 세계관 뷰 — React Flow + dagre 채택

**결정**: 인과 그래프 노드-링크 시각화(세계관 뷰, docs/specs/causal-worldview.md)에 **React Flow(`@xyflow/react`)** + **dagre**(레이아웃 알고리즘)를 신규 의존성으로 도입. dagre로 **좌(근본원인)→우(수혜) 계층 배치**(rankdir=LR) — force-directed(d3-force)가 아니라 방향 배치를 택한 이유는 "인과는 시간에 종속된다"(narrative-causal-graph.md §2, D-023) 원칙을 시각 언어로 그대로 반영하기 위함.

**맥락·이유**: 기존 차트 라이브러리(recharts·lightweight-charts)는 노드-링크 그래프를 못 그린다. Phase 2(D-023)에서 "노드-링크 풀 인터랙티브 시각화"를 1차 Out of Scope로 미뤘으나(narrative-causal-phase2.md §6), 2026-07-18 stakeholder 결정으로 이 트랙을 먼저 진행. narrative_id 스코프 없는 전역 인과 그래프(`pipeline/narrative_graph.py` `full_causal_graph`)에 union-find 연결요소(cluster_id)를 얹어 "같은 세계관"을 시각적으로 드러낸다.

**기각한 대안**: ① d3-force(force-directed) — 조직적이지만 방향성이 시각적으로 희석돼 시간 그래디언트 원칙과 어긋남 ② cytoscape.js — 네트워크 그래프 전문이나 React 통합이 React Flow보다 무겁고 커스텀 노드/엣지 DX가 떨어짐 ③ 순수 SVG+수동 배치 — 줌/팬/미니맵을 직접 구현해야 해 비용 과다.

**참조**: docs/specs/causal-worldview.md · backend/pipeline/narrative_graph.py(`full_causal_graph`) · backend/routers/spine_causal.py · frontend/src/components/explore/WorldviewPage.tsx

---

## D-025 · 2026-07-18 · 유튜브 요약 상태를 명시 컬럼으로 — digest_status + 열람 시 lazy 재시도

**결정**: `raw_documents`에 `digest_status`(ok|failed) 컬럼을 추가해 유튜브 opus 정리본 성공 여부를 명시적으로 관리한다(기존: `raw_content LIKE '%opus 정리본%'` 문자열 매칭으로 암묵 판별). `GET /api/spine/doc/{id}` 열람 시 해당 문서가 youtube이고 digest_status가 ok가 아니면 그 자리에서 opus 재요약을 1회 시도하고 성공하면 갱신(lazy retry) — 사용자가 문서를 열어보는 행위 자체가 백필 트리거가 된다.

**맥락·이유**: 진단 결과 최근 유튜브 요약 누락(11건)의 실제 원인은 PC 전원이 아니라, **cron이 띄우는 `claude` CLI 서브프로세스가 macOS Keychain의 로그인 세션에 접근하지 못해 "Not logged in" 실패를 반복**하는 것이었다(대화 중 로그 확인, `logs/ingest.log` 반복 패턴). 같은 세션의 인터랙티브 `claude` 호출은 정상 동작 — 즉 cron 컨텍스트 특유의 인증 문제. 이 근본 원인(cron 인증)은 이번 작업 범위에서 제외하고(stakeholder 결정), 대신 사용자 체감 문제(요약 누락이 방치됨)를 flag+lazy 트리거로 완화하는 쪽을 먼저 택했다 — 문서 열람은 보통 백엔드 서버(로그인 세션 있는 상태로 기동)에서 처리되므로 cron과 달리 성공 가능성이 높다.

**기각한 대안**: ① cron 인증 문제 자체를 먼저 해결(예: ANTHROPIC_API_KEY 환경변수로 전환, launchd 재구성) — 근본적이지만 별도 조사·검증이 필요해 범위 분리 ② 문자열 마커 유지 — 신뢰 불가(요약 본문에 우연히 유사 텍스트가 있으면 오판, 상태 조회 시 매번 LIKE 스캔).

**참조**: backend/database.py(마이그레이션+백필) · backend/pipeline/base.py · backend/pipeline/store.py · backend/pipeline/connectors/youtube.py · backend/routers/spine_doc.py · docs/SYSTEM.md §connectors/youtube, §GET /api/spine/doc/{id}

---

## D-024 · 2026-07-17 · 30분 수집 체인 겹침 방지 — run_chain.sh 락 래퍼

**결정**: crontab의 긴 인라인 `*/30` 체인(`ingest && redigest_youtube && compute_signals && … && build_search_index`)을 **`scripts/run_chain.sh` 단일 래퍼**로 옮기고, **겹침 방지 락**을 건다. 한 사이클이 30분을 넘겨 다음 cron이 이전 위에 쌓이면 두 writer가 SQLite를 동시에 두드려 busy_timeout 경합·락이 난다(실제 사고 이력). 락: flock이 macOS 기본 미포함이라 **mkdir 원자성 + PID 생존확인(stale 자동 회수)** 으로 이식성 있게. 이전 실행 진행 중이면 이번 회차 조용히 skip. 전환기·수동 실행 대비 `pgrep -f 'scripts/ingest.py'` 2차 가드. 기존 `&&` 실패-중단 의미 보존.

**맥락·이유**: cron 주기(30분)보다 런타임이 길면 stacking은 구조적 결함(stakeholder 지적). 근본 런타임(문서당 claude-CLI 콜드스타트 enrich가 느림)은 별개 최적화 과제 — 락은 "겹치지 않게"를 즉시 보장하는 올바른 1차 처방(런이 길어도 다음 회차 skip 후 30분 뒤 재개하면 됨).

**기각한 대안**: ① flock — macOS 미포함(brew 의존) ② ingest.py 내부 락 — 체인 전체가 아니라 ingest 단계만 보호 ③ 런타임 최적화(배치 enrich)를 먼저 — 오래 걸리고 겹침을 즉시 못 막음(후속).

**참조**: scripts/run_chain.sh · crontab `*/30` → run_chain.sh · 관련 락 사고: 유튜브 백필×cron 겹침(대화 2026-07-14)

---

## D-023 · 2026-07-17 · 내러티브를 인과 그래프 위 살아있는 월드모델로 — "하나의 인과 그래프, 두 개의 속도"

내러티브와 지식은 분리되어있음.
각 정보들의 정보에 시점과 더불어 '인과(from, to)' 개념을 더함. 이를 통해 노드간 관계로 이루어진 거대한 그래프가 구축되고, 거대한 그래프의 sub graph 경로 중 하나가 곧 특정 내러티브가 된다.

**결정**: 내러티브(theme_surge 고도화)를 md 덩어리 생성기에서 **인과 그래프 기반 지능 시스템**으로 격상한다. 기획: docs/specs/narrative-causal-graph.md(비전·로드맵), docs/specs/narrative-causal-phase1.md(Phase 1 기획서).

**관통 프레임**: 내러티브가 매번 opus로 뽑되 md 텍스트에만 버리던 "인과 구조 A→B→C, 수혜/피해 주체"를 그래프로 **물질화**한다 — `entity_relations`에 `CAUSES`/`BENEFITS_FROM` 엣지(epistemic=hypothesis, D-005 규약)로 적재. 그러면 내러티브는 "문서"가 아니라 **인과 그래프 위의 시간순 경로(walked path)**가 되고, **내러티브(빠른 층: 최근 문서의 종합)와 지식(느린 층: 공고화된 전제)이 같은 인과 그래프의 두 속도**가 된다(CLS 해마/신피질). 최종 지향은 둘이 서로를 먹이는 루프: 내러티브가 인과를 제안 → 반복·독립된 것이 지식으로 승격 → 지식이 다음 내러티브를 지지 → 지식의 falsifier가 감시 → 반증 시 지식이 흔들려 내러티브 재생성. = 진화계획 3단계(자율 에이전트).

**인과는 시간에 종속된다 (핵심 원리)**: 원인은 결과에 선행한다. D-021의 "수집 시각 ≠ 정보가 가리키는 시점(reference_period)" 분리를 인과 층에 끌어올려, **각 인과 엣지에 시간 스탬프**(reference_period·time_orientation)를 붙인다. 효과: ① 시간 그래디언트 = 체인의 읽기 순서(과거 뿌리 → 현재 → 전망 효과), 그래서 뒤의 끝(수혜)은 forward·hypothesis 영역이고 거기에 엣지가 있다 ② 시간 정합성 검증(원인이 결과보다 늦으면 유사인과 경고) ③ salience×conviction의 "이미 반영됐나(past·priced) vs 아직 안 왔나(forward·edge)"와 맞물림.

**확정한 5개 하위 결정** (2026-07-17 stakeholder):
1. **내러티브 = 1급 객체** — `narratives` 테이블(버전 보존·supersedes). source_digests 덮어쓰기 폐기 → 내러티브 드리프트("핵심 고리가 유가→금리로 이동") 추적 가능.
2. **인과 노드 = 예약 타입 활성화** — company·sector·theme·person에 **macro·policy·event** 추가(온톨로지 D-004 reserved 채움). 인과 체인은 기업만이 아니라 사건·매크로·정책을 통과하므로. 파편화는 임베딩 dedup + 기존 노드 주입으로 방어.
3. **뒤의 끝 = 섹터에서 종착** — 종목 하강은 후속(종목 노드·리서치 성숙 후). 억지 종목 지정은 거짓 정밀 = 사실/가설 분리 위반. 앞의 끝 = regime/structure급 루트에서 정지(무한 후퇴 방지).
4. **카테고리 = 도메인 렌즈** — 매크로·지정학·산업·수급·기술·정책(지식 A-7 live vocab). 교차 렌즈는 가중(lollapalooza). 루트 원인 emergent 클러스터는 그래프 성숙 후.
5. **반사성 = 시간으로 푸는 DAG** — 인과 엣지는 원인→결과 방향, 피드백("가격↑→낙관 내러티브→가격↑")은 사이클이 아니라 **같은 노드의 다른 시점 두 엣지**로 표현. 무한루프 없음, 앞/뒤 끝 순회 정의 명확.

**단계 (Phase 2는 필수 — 미룰 수 있는 옵션 아님)**:
- **Phase 1(토대)**: 위 5결정 물질화 — narratives 1급 객체·노드 타입·인과 엣지 적재·시간 스탬프·카테고리 + 최소 UI(인과 체인 구조 뷰).
- **Phase 2(필수 commit)**: 앞/뒤 끝 순회(루트 원인↑·수혜 섹터↓)·메르식 서사·버전 드리프트 시각화·내러티브 머지/교차검증·**내러티브↔지식 루프**. 이 단계라야 이번 고민(인과 양 끝·세계관 내러티브·상호 지능)이 실제로 시스템에 반영된다 — Phase 1만으로는 데이터만 쌓이고 가치는 미실현. stakeholder 명시(2026-07-17): "Phase 2도 반드시 해야 한다."

**기각한 대안**: ① 인과를 계속 프롬프트가 프로즈로만 생성(스키마 무변경) — 질의·연결·추적·머지·지식 연동 전부 불가, 매번 재추론 낭비. ② source_digests 유지(1급 객체화 안 함) — 버전·머지·그래프 연결을 억지로 얹어야 해 구조 지저분. ③ 인과 노드를 기존 엔티티(company/sector/theme)로 한정, 이벤트/매크로는 엣지 텍스트로 — 매크로 체인(유가→인플레→금리)을 노드로 못 그림. ④ 뒤의 끝을 항상 종목까지 강제 — 근거 약한데 종목 찍는 거짓 신호. ⑤ 사이클 허용 방향그래프 — 무한루프·루트/종착 모호(시간 DAG가 반사성을 더 정확히 표현). ⑥ 루트 원인 emergent 클러스터를 처음부터 — 그래프 미성숙 시 무의미, 도메인 렌즈로 시작 후 진화.

**참조**: docs/specs/narrative-causal-graph.md(§5-0 결정)·narrative-causal-phase1.md · pipeline/narrative.py·signals.py(theme_surge) · 엣지 D-005 · 온톨로지 D-004 · 시간 정박 D-021 · 지식 위계·CLS·§G D-022·docs/specs/knowledge-hierarchy-design.md · 대화 2026-07-17

---

## D-022 · 2026-07-17 · 지식 위계 — 주목(salience)과 확신(conviction) 분리 + 반증-우선 주입 + /knowledge 관측 페이지

**결정**: ① 지식 승격 기준의 "반복=지식" 함정을 축 분리로 정면 대응 — **salience(시장 주목: 주체 엔티티 최근 언급량)와 conviction(근거 강도: 독립 관측·소스 다양성·느린 pace 층·반박 감점)을 직교 축으로** 계량하고(pipeline/knowledge_state.py, LLM 0), 4상태로 위치: `주목받지 않은 확신`(기회·소외)·`주목받는 확신`(선반영)·`확신 대비 과한 주목`(진자 경고)·`단순 노이즈`. 하나의 "지식" 점수로 합치지 않는다 — 그 갭 자체가 알파(설계 §G). ② **반증-우선 주입**: 사용자 주입 시 corroboration을 수동으로 기다리지 않고 **opus가 반증 조건을 구조화**(condition·target_entity·metric·threshold·window)로 즉시 생성, 감시·판정은 기존 결정적 로직(falsifiers). 반례 축적 시 contested 강등 — 시스템 지식과 같은 수명주기. ③ `/knowledge`를 **3섹션 관측 페이지**로 개편(구조 지도·현황 대시보드·주입 콘솔), 사용자 주입은 이 페이지에서(+rationale·source). 내 주입 지식(model='user')은 삭제 가능, 시스템 승격분은 superseded만(역사 보존).

**맥락·이유**: stakeholder 통찰 — "반복 뉴스는 세상 인식(주목) 시그널이고, 영향력 있는 현자의 단발 통찰은 진리근접 시그널인데, 둘은 다른 축이다." 기존 승격은 독립 관측 2+ 하한이라 현자의 단발 통찰(독립 관측 1)은 승격 불가였고, salience/conviction을 안 나누면 '붐비는 합의'와 '소외된 엣지'를 구분 못 했다. 반증-우선은 ACH(A-4)의 능동형 — 주입을 수동 축적이 아니라 스트레스 테스트로. 반증 생성만 opus(심층), 감시는 LLM 0(재현성·비용). 관측 페이지는 기존 평면 리스트가 체계 구조·현황을 못 보여주던 문제 해결.

**기각한 대안**: ① 승격 기준을 "더 똑똑하게" 단일화 — 두 축을 하나로 뭉개면 정보 소실, 분리가 정답. ② 순수 Opus 반증(생성+판정 매번 LLM) — 비용·비재현·드리프트로 기각, 하이브리드(구조화+결정적 감시) 채택. ③ 소스 권위/트랙레코드 가중을 지금 도입 — 편집자적 편향 위험 + 트랙레코드 데이터 미축적, 국지성/캘리브레이션은 K1+ 후속으로 보류(Out of Scope). ④ 홈 "통념 vs 나의 가설" 갭 패널 — P2 후속.

**참조**: docs/specs/knowledge-page.md · pipeline/knowledge_state.py·falsifiers.py·knowledge.py · routers/spine_knowledge.py · frontend KnowledgePage.tsx · 설계 원본 docs/specs/knowledge-hierarchy-design.md §A-3·A-4·G · 대화 2026-07-17

---

## D-021 · 2026-07-14 · 시간 정박 — 발행일 ≠ 사건 발생일

**결정**: 문서의 `published_at`(수집·작성 시각)을 사건 발생 시각처럼 쓰던 것을 바로잡는다. enrich 태깅 haiku 콜에 **같은 호출로** `time_orientation`(past/current/forward/mixed)과 `reference_period`(발행일과 다른 실제 대상 시기, 예 '2027 전망')를 추가 추출 → enrichments 2컬럼. 이를 (1) 내러티브 — '전개' 섹션을 '무엇이 회자되고 있나'로 개칭, 수집일이 사건일이 아님을 명시하고 회고/현재/전망을 구분, (2) 다이제스트 — 문서별 [현재]/[전망]/[회고] 태그로 "전망을 방금 벌어진 사건으로 단정 말라", (3) mention_surge — 급증의 시간 방향 구성(orient_mix·orient_driver)을 실어 '전망 위주 급증'과 '실제 사건 급증'을 구분, 에 반영. 기존분은 scripts/backfill_temporal.py(title+요약만 쓰는 경량 haiku, 최신순)로 백필.

**맥락·이유**: "3일에 A를 수집" → "3일에 A가 발생"으로 처리되어, 실제로는 몇 달·미래에 걸친 이슈가 수집 기간(며칠)에 압축돼 '급격한 전개'처럼 보이는 착시가 시스템 전반에 있었다(예: Web3 내러티브가 8일 만의 급전개로 오독). 월드모델의 시간 감각은 토대라 미룰 수 없다. 비용은 사실상 0 — 태깅 콜에 필드 2개 추가일 뿐.

**기각한 대안**: ① 내러티브 프롬프트만 고쳐 opus가 본문에서 시간 추론(스키마 무변경) — 즉효지만 신호·다이제스트엔 무력, 매 생성마다 재추론 낭비 ② 정밀 event_date 파서(정규화된 날짜) — haiku가 다양한 문서에서 정확한 날짜를 뽑기엔 취약, orientation+coarse period가 비용 대비 실익의 균형점.

**참조**: enrich.py(classify_temporal), store.py, database.py(enrichments +2), narrative.py, digests.py, signals.py(mention_surge), scripts/backfill_temporal.py

## D-020 · 2026-07-14 · RS 활용 = 승인 게이트형 리서치 제안 (항상-켜짐 4분면 기각)

**결정**: 산업 맵의 RS 지표를 펀더멘탈과 결합하는 방식으로, **전 종목 RS×펀더멘탈 4분면을 매일 opus로 돌리지 않고**, 값싼 감지로 후보를 골라 **제안 → 사용자 승인 시에만 opus 리서치**를 실행. 감지(LLM 0) = 관심 유입(단기 RS≥70 & 1주 대비 +8pp↑) ∩ 규모(시총 5000억+) ∩ 화두(theme_surge 테마와 초점 문서 공동언급). 승인 = stock_brief(opus) 실행 → 추정치 방향 콜(up/down/hold) 기록. 표면: 신호 탭 '리서치 제안' 섹션(ApprovalsCard와 동일한 기계 제안→사람 결정 패턴).

**맥락·이유**: 비싼 자원은 opus 리서치 하나뿐 — RS 계산·시총·테마 공동언급은 전부 공짜 SQL. 후보 감지를 값싸게 하고 비싼 노동을 사람 판단 뒤로 미루면 opus 호출이 (RS 상승 전 종목 매일) → (승인한 소수)로 ~10배 감소. 프로젝트 철학 "노동은 기계가, 판단은 사람이"와 정확히 일치. 사용자 제안이 원안(항상-켜짐 4분면)보다 싸다는 계산을 확인하고 채택.

**기각한 대안**: ① RS×펀더멘탈 4분면 상시 계산(전 종목 매일 opus) — 비용 과다, 대부분 안 볼 종목까지 리서치 ② 펀더멘탈 축을 값싼 신호(컨센서스 방향·감성)로만 채운 상시 배지 — 컨센서스 이력이 하루치라 방향 판정 부정확, 승격 후 재검토. ③ 종목↔테마 연결을 MEMBER_OF(KSIC)로 — theme_surge(투자언어 테마)와 taxonomy 불일치 → 문서 공동언급으로, 시황 요약글(종목 링크 6개 초과)은 오염원이라 제외.

**참조**: pipeline/research_candidates.py, routers/spine_research.py, database.py(research_candidates), scripts/compute_signals.py, ExplorePage.tsx

## D-019 · 2026-07-12 · 세계관 브리핑 — 지식 종합과 주간 갈무리를 하나로

**결정**: "지식 기반 세계관 브리핑"(아이디어 1)과 "인물·채널 주간 갈무리"(아이디어 2)를 별개 기능으로 만들지 않고 **하나의 세계관 브리핑**으로 통합. 내부 3단 구조가 두 아이디어를 흡수: [자리 잡은 전제(느린 층 지식) / 도전받는 것(contested·반박) / 이번 주 달라진 것(빠른 층 관측·신호)] + 만장일치 경고 1줄. 표면: /knowledge 상단 카드, 게으른 생성(hash 가드), 종합=sonnet.

**맥락·이유**: 두 아이디어의 본질적 차이는 pace layer(느린/빠른)일 뿐 — 위계 설계가 정확히 이 구분을 위해 존재하므로 기능을 나누면 중복·중구난방(stakeholder 우려)이 된다. §G "시장의 통념 계량"의 1호 소비 표면.

**기각한 대안**: ① 별개 두 기능(지식 브리핑 + 주간 갈무리) — 재료 중복, 소비 지점 분산 ② 아침 텔레그램 브리핑에 통합 — 세계관은 매일 갱신될 이유가 없음(지식 상태 변경 시에만).

**참조**: 커밋 80fa90a, pipeline/worldview.py, knowledge-hierarchy-design.md §G

## D-018 · 2026-07-11 · 강조 카드 = 좌측 보더 → 배경 틴트

**결정**: 강조 카드(홈 브리핑·AI 응답 말풍선·AI 요약/브리프/다이제스트/소스요약)의 `border-l-2 border-l-primary|hypothesis`를 제거하고 **불투명 배경 틴트**로 강조: `bg-[color-mix(in_srgb,var(--{primary|hypothesis})_8%,var(--card))]`. 두 강조 유형을 동일 8% 강도로 평행하게. 적용 6곳: HomePage 브리핑, ChatPage AI 말풍선, StockBriefCard, DigestSection, DocPage·SourcePage AI 요약.

**맥락·이유**: 좌측 보더 강조는 나머지 카드 언어(ring+shadow, 배경 대비)와 어긋나는 변칙. 배경 틴트가 일관적. `color-mix`로 카드색 위에 얹어 불투명하게 만들어 카드 입체감·다크모드 대비를 유지(저알파 `bg-x/5`는 다크에서 카드 표면을 잃어 부적합).

**유지(강조 카드 아님)**: 채팅 스레드 선택 마커(`border-l-primary` 활성 표시, 사이드바 선택 패턴과 동일)·인용 들여쓰기(`border-l-2 border-border`)·밸류체인 다이어그램 헤더.

**참조**: docs/DESIGN_SYSTEM.md §3 패턴표 · 6개 파일

---

## D-017 · 2026-07-11 · shadcn-first 정책 + 헤더 정리 + 보더리스 + 팔로우 레일 Sidebar화

**결정**:
1. **shadcn-first (정책)**: 기능에 대응하는 shadcn 공식 컴포넌트가 있으면 반드시 CLI 설치해 쓴다. atom뿐 아니라 Sidebar·Sheet·Dialog·Progress·AlertDialog 등 복합 컴포넌트 포함. 그 위에 토큰+wrapper만 씌운다. 수제 div/raw HTML 금지.
2. **헤더 정리**: 중복 검색(360px 검색창 + "이동·검색·질문 ⌘K" 버튼)을 단일 필드형 검색 진입점으로 통합 — 클릭·⌘K 모두 Omnibar 오픈(Omnibar가 이미 회사검색·이동·문서검색·질문 커버). 헤더 회사 배지 제거(ModeNav pill과 중복). raw kbd→`Kbd`.
3. **보더리스**: "아웃라인→면(surface)"으로 전환. 헤더·네비의 `border-b` 제거(카드색 vs stone 바탕 대비로 층 표현). 카드는 이미 ring+shadow. 표 행 구분선·인풋·세그먼트는 스캔/조작에 필요하므로 유지.
4. **팔로우 레일 = shadcn Sidebar**: 수제 `<aside>`(fixed·localStorage·✕)를 공식 `Sidebar`(side=right, collapsible=offcanvas)로 교체. 앱 셸을 `SidebarProvider`+`SidebarInset`로 재구성(헤더/네비가 inset 안으로). 넓은 데스크톱(≥1280px)=펼침, 그 이하=토글(헤더 패널버튼/⌘B), 모바일=Sheet 오버레이 자동.
5. **감사 후속 일괄 교체**: 패널토글 2곳(Financials·Industry)→SegmentTabs, 카탈리스트 기간필터→FilterChips·펼침→Collapsible, native `confirm()` 2곳→AlertDialog, 수제 진행바→Progress. **미교체(사유 있음)**: UnifiedFeed 전문펼침(요약숨김+이미지리사이즈 얽힘)·SignalCard 부분리스트노출(slice)·Expandable(fade+높이클램프)·인라인 추가폼(Dialog화는 UX 변경이라 보류).

**맥락·이유**: 공식 컴포넌트 CLI 설치가 접근성·키보드·포커스·엣지케이스 안정성을 보장(사용자 지시). 헤더 번잡함의 원인은 검색 중복+겹치는 하드보더였음.

**기각/주의**: Sheet 오버레이(항상 보이는 레일 목적과 상충), Sidebar in-flow collapsible=none(반응형 접힘 안 됨) → offcanvas 채택. shadcn Sidebar는 뷰포트 우측 고정·전체높이 모델이라 기존 '중앙 셸+전폭 헤더 위' 구조에서 **헤더/네비가 inset 폭으로 축소**되는 레이아웃 변화 수반(사용자가 반응형 collapse 의도를 확인해 수용). CLI가 파일을 `@/` 경로에 잘못 생성 → 필요한 것만 `src/`로 이동, 재생성된 button/input 등은 커스텀 보존 위해 폐기.

**참조**: memory `shadcn-first-policy` · App.tsx(SidebarProvider) · FollowRail.tsx · Header.tsx · index.css(sidebar 토큰은 D-016) · 설치: sidebar·sheet·progress·alert-dialog·toggle·toggle-group·checkbox

---

## D-016 · 2026-07-11 · 라이트/다크 팔레트 재설계 — 멀버리 정체성

**결정**: Apple HIG 캔디블루(#0071e3) 팔레트를 버리고 **멀버리(#8e4162) 프라이머리** 중심으로 라이트/다크를 하나의 정체성으로 재설계. 확정값(index.css):
- **낮 (쿨 스톤 & 멀버리)**: ground `#f9f8f9` · card `#ffffff` · primary `#8e4162` · secondary `#ebedf0`(서늘한 회석) · accent `#f6eef2` · border `#e0e2e7`
- **밤 (더스크 플럼)**: ground `#282130` · card `#332a3c` · primary `#e199ba` · secondary `#3f3447` · accent `#402d49` · border `#504358` · primary-foreground `#23121b`
- 등락 빨강/파랑·사실 초록·가설 주황 컨벤션 유지(형광기만 조정). 차트 캔디블루(#0071e3→#1268c3 / #409cff→#5aa6f5)만 팔레트에 맞춰 눅임 — 나머지 차트 시리즈색은 유지(별도 검토 대상).

**맥락·이유**: 기존 라이트가 "촌스럽다"는 사용자 피드백. 원인은 순백+캔디블루+진한 보더의 강한 평면 대비. 멀버리는 AI 서비스가 거의 안 쓰는 좌표라 차별화되고 금융 에디토리얼(FT 계열) 헤리티지가 있음. 다크는 "라이트 반전"이 아니라 **같은 방 불 끈 상태**로 설계 — 프라이머리가 바탕에도 흐르는 정체성. 다크 밝기는 사용자 눈 편안함 기준으로 순검정(#17121b) 대신 더스크 플럼(#282130)까지 올림(halation 완화).

**기각한/킵한 대안** (재검토 시 참조 — 값은 스크래치패드 아티팩트에 목업 존재):
- 낮 뉴트럴: L-1 딥 블러시 `secondary #f4e2ea`(무드) · L-2 웜 샌드 `#efeae1`(절제). L-3 쿨 스톤 선택 — "앤트로픽 크림 느낌"이 가장 덜함.
- 낮 프라이머리 후보: 코발트 인디고 #3b5bdb, 딥 틸 #0f766e, 딥 네이비 #2f4f96 — 멀버리로 확정.
- 밤 온도/밝기: 웜 오베르진 진함(#17121b)~살짝(#1c1621)~중간(#221b28) · 쿨 슬레이트 계열 — 더스크 플럼(#282130) 선택. **더 밝혀도 무방**하다는 사용자 의견 있음(추후 조정 여지).

**참조**: frontend/src/index.css `:root`·`.dark` · 어제까지의 Apple HIG 값은 git 히스토리 · docs/DESIGN_SYSTEM.md §2

---

## D-015 · 2026-07-11 · 프론트 레이아웃 컨트랙트 + 디자인 시스템 명문화

**결정**: ① 모든 라우팅 페이지의 최상위는 `shared/PageContainer`(width: full|reading, gap: sm|md) — 페이지가 자체 max-w/padding을 갖지 않고 폭은 셸 토큰 `--layout-shell`(1440px)이 단독 결정. ② 풀하이트 페이지(Chat)는 `--shell-offset` 토큰 기반 `calc` 예외. ③ 다열 그리드는 반드시 `grid-cols-1`에서 시작하는 반응형. ④ 단일선택 세그먼트는 Radix ToggleGroup, 접기/펼치기는 Radix Collapsible로 단일화. ⑤ 전체 규약을 docs/DESIGN_SYSTEM.md로 명문화 (Meta astryx의 CSS-변수 테마·강한 컨벤션·조합성 원칙 차용).

**맥락·이유**: 페이지마다 max-w(없음/2xl/3xl)·간격(space-y-4/5/6)·자체 패딩이 제각각이라 화면 넘침/미달이 혼재했고, 같은 세그먼트 토글이 4곳에서 다르게 수제 구현돼 있었다. 폭 결정권을 셸+PageContainer 두 곳으로 좁히면 규격 불일치가 구조적으로 불가능해진다.

**기각한 대안**: 페이지별 개별 수선(재발 방지 안 됨) · shadcn Tabs로 세그먼트 대체(패널 전환 의미론이라 부적합, 값 토글은 ToggleGroup이 정합) · 셸 폭 무제한 확대(초광폭 모니터 가독성 저하).

**참조**: docs/DESIGN_SYSTEM.md · shared/PageContainer.tsx · index.css 레이아웃 토큰 · grandfathered 예외 목록(DESIGN_SYSTEM.md §3)

---

## D-014 · 2026-07-11 · 컨텍스트 3층 문서 체계 + 유지 규율

**결정**: 프로젝트 문서를 변경 빈도별 3층으로 고정하고, CLAUDE.md에 갱신 규칙을 명문화한다.
- **규칙층** CLAUDE.md — 매 세션 자동 로드, 거의 불변
- **상태층** docs/SYSTEM.md — 살아있는 시스템 지도, 구조가 바뀌는 커밋에 *같이* 갱신
- **결정층** docs/DECISIONS.md(본 파일) — append-only, 중요 결정마다 추가

**맥락·이유**: ARCHITECTURE.md가 초기 커밋(7/4) 이후 방치돼 일주일 만에 낡은 문서가 됐고, SYSTEM.md에 "본 문서가 현행" 면책 문구가 필요해졌다. 낡은 문서는 없는 것보다 나쁘다(다음 세션의 LLM이 믿고 판단). 유지 비용이 0에 가까운 구조(append-only 로그 + 커밋 동반 갱신)만이 지속된다.

**기각한 대안**: ① 매 작업 세션별 작업일지 — 의식이 무거워 몇 주 내 붕괴 예상, "어떻게 했는지"는 git 히스토리가 이미 담당. ② CLAUDE.md에 아키텍처 내용 직접 기술 — 매 세션 컨텍스트를 태움, CLAUDE.md는 규칙+포인터만. ③ codebase-memory MCP의 ADR 기능 — md 파일이 git 리뷰·이식성에서 우위.

**참조**: CLAUDE.md "Context Discipline" 섹션 · 구 문서는 docs/archive/로 이동

---

## D-013 · 2026-07-10 · 앤티-분산(anti-sprawl) 정책 — 새 기능은 새 탭 0개

**결정**: 새 기능은 원칙적으로 새 페이지·새 탭을 만들지 않고 기존 화면에 편입한다. IA 확장은 명시적 결정이 있을 때만.

**맥락·이유**: 기능이 붙을 때마다 탭이 늘면 "매일 아침 여는 터미널"이 미로가 된다. 북극성 지표(주간 열람일수)는 화면 수가 아니라 홈·피드의 밀도에서 나온다. 소스 건강 모니터·보관함부터 첫 적용(새 탭 0개).

**기각한 대안**: 기능별 전용 페이지 — 발견성은 옴니바(⌘K)가 대체.

**참조**: 커밋 7a45160 · 옴니바 52d7e86

---

## D-012 · 2026-07-10 · 지표 체계 — 북극성 = 주간 열람일수, OMTM = "홈이 조용한 날" < 10%

**결정**: 북극성 지표는 주간 열람일수(5일 만점), 당면 단일 지표(OMTM)는 "홈이 조용한 날" 비율 < 10%. 레버는 소스 확충·키워드·별칭 recall.

**맥락·이유**: 실사용 피드백에서 검증된 가치 패턴은 "기계가 읽고·모으고·연결"이고 "기계가 종합 판단"은 시기상조. 따라서 매일 열 이유(delta 밀도)가 제품의 생명선. 조용한 날이 시장 탓인지 수집 고장 탓인지 구분하기 위해 소스 건강 모니터가 OMTM 방어 장치로 함께 도입됨.

**기각한 대안**: AI 답변 품질을 당면 지표로 — 문서 1,000+건 축적 전에는 측정 무의미(가설 H3, 월말 재평가).

**참조**: docs/STRATEGY.md · 커밋 5a71cbb

---

## D-011 · 2026-07-10 · SQLite 유지 + WAL + busy_timeout 30s — Postgres·AWS는 보류

**결정**: 단일 SQLite 파일(WAL 모드, busy_timeout 30초)을 유지한다. Postgres 전환과 AWS 배포는 멀티유저(S2) 트리거가 실제로 당겨질 때 함께 진행.

**맥락·이유**: 로컬 개인 도구에서 SQLite는 운영 비용 0·백업 단순. 30분 cron 수집 쓰기와 API 읽기가 충돌해 락 오류가 났고, WAL + busy_timeout 30s로 해결(543148c). 이 해법의 한계(단일 라이터)는 인지하고 있으며 멀티유저 전 Postgres 리프트&시프트 설계는 논의 완료 상태로 보류.

**기각한 대안**: 즉시 Postgres — 현 단계에서 운영 복잡도만 증가. 사용자가 AWS 배포 명시적 보류.

**참조**: 커밋 543148c · docs/BACKLOG.md "AWS 배포(사용자 보류)"

---

## D-010 · 2026-07-10 · 텔레그램 수집 = 공개 프리뷰(t.me/s) 스크랩만, 이미지는 로컬 보관

**결정**: 텔레그램은 로그인 없는 공개 프리뷰 페이지 스크랩으로만 수집한다(공개 채널, 최근 ~20개 창). 첨부 이미지는 CDN URL 만료에 대비해 `media/telegram/`에 결정적 파일명(채널_메시지ID_순번)으로 다운로드 보관.

**맥락·이유**: Telethon(계정 로그인) 방식은 비공개 채널·과거분 수집이 가능하지만 계정 보안·약관 리스크가 있어 보안 논의를 선행 조건으로 보류. 프리뷰 창이 좁은 대신 30분 cron이 촘촘히 돌아 실질 유실은 적다.

**기각한 대안**: Telethon 즉시 도입 — 보안 논의 선행. CDN URL 직접 참조 — 만료로 이미지 유실.

**참조**: backend/services/telegram_service.py · pipeline/connectors/telegram.py · 커밋 a62b047

---

## D-009 · 2026-07-09 · LLM 계층 = Claude Code headless(구독 인증) + 용도별 모델 티어

**결정**: LLM 호출은 API 키 대신 Claude Code headless(`claude -p`) 구독 인증으로 구동. 용도별 티어 고정 — 태깅·요약·비전·다이제스트 = haiku, RAG 질의응답 = sonnet, 임베딩 = 로컬 fastembed(다국어 MiniLM 384d). `ANTHROPIC_API_KEY` 설정 시 자동 API 모드 전환(코드 준비됨).

**맥락·이유**: 개인 도구에서 LLM 한계비용을 0으로(구독에 포함). 문서당 1회 원칙 + `content_hash` 멱등 캐시로 재수집 시 재호출 방지. keyword 엔진 → LLM 자동 백필로 모델 티어 업그레이드 경로 확보.

**기각한 대안**: API 키 직접 사용 — 종량 비용 발생, 단 전환 스위치는 유지. 임베딩도 LLM API — 로컬 fastembed로 충분하고 무료.

**참조**: 커밋 2f32680 · backend/pipeline/enrich.py · SYSTEM.md §3

---

## D-008 · 2026-07-08 · 검색 = FTS5(BM25) + sqlite-vec 하이브리드, RRF 융합

**결정**: 피드 검색은 SQLite 내장 FTS5(BM25)와 sqlite-vec 벡터 검색을 RRF(Reciprocal Rank Fusion)로 융합한 하이브리드로 구현. FTS 인덱스는 트리거로 동기화.

**맥락·이유**: 한국어 종목명·별칭은 키워드 매칭이 강하고, 문맥 질의는 벡터가 강함 — 단독으로는 어느 쪽도 recall이 부족. 별도 검색 인프라(Elasticsearch 등) 없이 단일 SQLite 안에서 해결(D-011과 일관).

**참조**: 커밋 8b93569 · backend/pipeline/search.py

---

## D-007 · 2026-07-08 · vault 소유권 분할 — 대칭 sync 금지

**결정**: Obsidian vault와 DB의 동기화는 단방향 2개로만. 자동수집 데이터 = **DB가 원본** → vault/entities/로 투영(generated). 사람의 가설·메모 = **마크다운이 원본**(vault/notes/, `[[위키링크]]`) → DB로 흡수. 양방향 sync는 금지.

**맥락·이유**: 대칭 sync는 충돌 해소 로직이 필요해지고, 어느 쪽이 진실인지 모호해진다. 데이터 종류별로 원본 소유자를 고정하면 충돌이 원천 불가능. 위키링크는 confidence 1.0 엔티티 링크로 흡수(사람이 직접 연결한 것이 가장 신뢰도 높음).

**기각한 대안**: 양방향 동기화 — 충돌 해소 복잡도. vault 없이 DB만 — 가설 작성 UX는 Obsidian이 압도적.

**참조**: 커밋 8b93569 · scripts/vault_sync · SYSTEM.md 비타협 원칙

---

## D-006 · 2026-07-06~08 · entity_links 신뢰도 계층 (5단계)

**결정**: 문서↔엔티티 링크는 출처별 고정 confidence를 갖는다: 위키링크 1.0 > LLM 추출 0.9 > 사용자 키워드 0.7 > 정식명 substring 0.6 > 태그 0.5. UI는 저신뢰 링크를 흐리게 표시(EntityChip).

**맥락·이유**: 초기 substring 매칭이 오탐을 냈고(8f64e4a에서 수정), "누가 이 링크를 만들었나"를 보존해야 오탐 정리·재enrich 시 stale 링크 제거가 가능. 사람이 만든 링크(위키링크·키워드)는 기계보다 위.

**참조**: backend/pipeline/store.py · 커밋 8f64e4a · SYSTEM.md §4-1

---

## D-006 · 2026-07-12 · 지식 위계 K0 게이트 조기 해제 (stakeholder 지시)

**결정**: K0(공고화 계층)의 문서 1,000건 게이트를 해제하고 즉시 구현·가동. 승격 배치는 주 1회(일 07:00 cron), 산출은 승인 큐(홈 카드)로 — 자동 확정 없음(D-005 설계 결정 유지).

**맥락·이유**: 설계 문서(knowledge-hierarchy-design.md v4)가 문헌 검증(부록 F)까지 마쳐 승인됨. 게이트의 목적은 '반복 관측이 잡히기 시작하는 규모'였는데, 조기 가동의 해악이 없음 — 초기엔 후보가 적게 나올 뿐이고, 승인 큐가 품질 관찰 창 역할. 코퍼스(~550건)가 쌓이는 대로 배치 산출이 자연 증가.

**기각한 대안**: 1,000건 대기 — 승인 큐 품질 관찰을 늦출 이유가 없음.

**참조**: docs/specs/knowledge-hierarchy-design.md · D-004(게이트 설정)·D-005 · pipeline/consolidation.py

---

## D-005 · 2026-07-06 · 그래프 엣지는 단방향 저장, epistemic_type 필수

**결정**: entity_relations 엣지는 단방향만 저장(`SUPPLIES` A→B만, "고객사"는 질의로 역전). 모든 엣지는 `epistemic_type`(fact | hypothesis) 필수 — fact는 공시·통계로 검증 가능한 것만, hypothesis는 confidence + source_doc_id 필수.

**맥락·이유**: 양방향 저장은 정합성 깨짐의 근원. 사실/가설을 섞으면 월드모델이 "그럴듯한 쓰레기"가 된다 — 목표는 믿는 자동 오라클이 아니라 **출처 달린 가설 트래커**. 이 원칙은 UI까지 관통(가설 = 주황 hypothesis 스타일, 모델명 표시).

**참조**: docs/ontology.md 설계 원칙 · SYSTEM.md 비타협 원칙

---

## D-005 · 2026-07-11 · P2-2 게이트 해제 — 전면 개편 즉시 진행 (stakeholder 지시)

**결정**: D-004의 "P2-2는 2주 질문 데이터 관찰 후" 게이트를 해제하고 대화 UI(/chat 스레드)와 L1 재편(오늘·탐색·피드·대화)을 즉시 진행. 분석 L1 pill 제거(도시에는 목적지 — 분석 화면에서만 컨텍스트 pill+서브탭 노출), 리서치 서브탭 그룹 해체, catch-all `*`→/home. /ask는 /chat으로 리다이렉트(쿼리 보존).

**맥락·이유**: 사용자(stakeholder) 피드백 — 원했던 것은 프로덕트 전체 리브랜딩·플로우 재정의인데 단계적 접근이 "디테일 페이지 조금 바뀐 수준"으로 체감됨. 데이터 게이트는 리스크 관리 장치였지 목표가 아니므로, 눈에 보이는 개편을 앞당기고 A1~A3 가정 검증은 출시 후 관찰로 전환.

**기각한 대안**: 게이트 유지(2주 관찰 후 개편) — stakeholder가 명시적으로 기각.

**참조**: docs/specs/product-v3.md §5 · D-004

---

## D-004 · 2026-07-06 · 온톨로지 스코프 규율 — 렌즈 1개 end-to-end 먼저

**결정**: 세상 전체를 day1에 모델링하지 않는다. 노드/엣지 타입 어휘는 미리 선언(reserved)하되, 메모리/AI 렌즈 1개를 end-to-end로 완성해 루프를 증명한 뒤에만 다음 렌즈(인물·지정학·매크로)를 채운다. 렌즈가 늘어도 DB는 1개 — entity_type/relation_type 어휘만 확장.

**맥락·이유**: 온톨로지는 넓히기는 쉽고 채우기는 비싸다. 빈 스키마 확장은 복잡도만 늘린다. observations/models 테이블도 스키마만 만들고 무역 커넥터 단계까지 비워두는 것이 같은 원칙.

**참조**: docs/ontology.md · SYSTEM.md §4-1 (observations/models 0행)

---

## D-004 · 2026-07-11 · Phase 2 — 판단 루프 축 + 대화 프리미티브 승격 (feat/phase2 분기)

**결정**: ① Phase 2 UI/UX 개편의 중심 축을 "판단 루프"(유입→델타→맥락→판단)로 삼고, 대화(채팅)를 스트림·도시에에 이은 **세 번째 프리미티브**로 승격. ② 질문·후속질문·답변 히스토리를 데이터 자산으로 영속화(conversations/chat_messages) — 웹 /ask와 텔레그램 봇 공용 풀. ③ **에코챔버 방지 불변 원칙**: AI 답변은 검색 인덱스(doc_fts/doc_vec)에 절대 넣지 않는다 — 질문은 시그널, 답변은 파생물. ④ 마이그레이션은 "데이터부터, UI는 증거 뒤에" — P2-0(영속화, UI 무변화)을 먼저 깔고, 대화 UI(P2-2)는 2주 질문 데이터 관찰 후 결정. ⑤ 작업은 feat/phase2 브랜치 — feat/etl-spine을 안정 복귀점으로 유지. ⑥ OMTM(주간 열람일수)에 텔레그램 문답을 '열람'으로 포함하도록 재정의.

**맥락·이유**: ia-map.md 진단 — 최대 허브(/analyze/summary, 13+ 엣지)가 spine과 단절된 dead-end, 판단 레이어(투자메모)가 보관함에 유배, 루프가 안 닫힘. 질문 히스토리는 이 제품이 쌓는 유일한 "사용자 의도" 데이터인데 현재 전부 버려짐(/ask 일회성, 봇 stateless). 반복 질문의 브리핑 승격은 3단계(자율 에이전트)로 가는 다리 — 에이전트의 할 일을 질문 패턴이 정의한다.

**기각한 대안**: 대화를 전역 채팅 패널로(레일과 경쟁, 산만) — 엔티티 앵커 스레드 + 도시에 내 섹션으로 대체. AI 답변도 raw_documents로 적재(검색 대상화) — 자기 참조 오염 위험으로 기각. UI 먼저 대개편 — A1~A3 가정(질문 빈도) 미검증 상태라 기각.

**참조**: docs/specs/product-v3.md(리스크 가정 10건·킬 기준 포함) · docs/specs/ia-map.md · 사용자 승인 2026-07-11

---

## D-003 · 2026-07-06 · ETL 척추(spine) greenfield — raw_documents 단일 진실원천

**결정**: 소스별 테이블(telegram_messages, blog_posts)에 각자 적재하던 구조를 버리고, 모든 소스가 `SourceConnector` 프로토콜(discover→fetch)을 구현해 **raw_documents 단일 테이블**(UNIQUE(source_type, source_id), content_hash 멱등)로 수렴하는 척추를 신설. 기존 도메인 테이블(companies, stock_prices, financial_statements…)은 삭제하지 않고 유지 — 척추가 읽기 참조하는 "옛 세계".

**맥락·이유**: 검색·태깅·요약·신호가 소스마다 중복 구현되는 것을 차단. 새 소스 추가 = 커넥터 1개 작성으로 수렴. 옛 테이블을 파괴하지 않은 것은 종목 디테일·스크리너 등 기존 화면의 안정성 때문 — 점진 cutover 후 telegram_messages 등은 휴면 처리(D-003 이후 ffcee21에서 피드 cutover 완료).

**기각한 대안**: 소스별 테이블 유지 + 뷰로 통합 — 태깅·검색 파이프라인이 소스 수만큼 분기. 옛 테이블 즉시 삭제 — 리스크 대비 이득 없음.

**참조**: 커밋 5449eec(도입)·ffcee21(cutover) · backend/pipeline/ · SYSTEM.md §4

---

## D-002 · 2026-07-04 · DART 재무 데이터 처리 규칙

**결정**: ① 연결(CFS) 우선, 없으면 별도(OFS) fallback. ② 손익계산서·현금흐름표는 분기 차감(Q2 = 반기 − Q1), 재무상태표는 시점 데이터 그대로. ③ 계정명은 `_normalize_account_name()`으로 변형 통합(영업이익 = 영업이익(손실)). ④ 모든 외부 API 호출은 cache_meta 캐시 패턴 필수.

**맥락·이유**: DART 원본은 누적 기준·계정명 표기가 회사마다 달라 그대로 쓰면 분기 비교가 불가능. 이 규칙 없이는 재무 화면 전체가 오염된다. opendartreader는 0.2.2 핀(0.3.x는 패키지 구조 변경으로 import 불가, 8f64e4a).

**참조**: backend/services/dart_service.py · CLAUDE.md 백엔드 규칙 · requirements.txt 핀 주석

---

## D-001 · 2026-07-04 · 초기 스택 — FastAPI + SQLite + React 19, 로컬 우선

**결정**: 백엔드 FastAPI + SQLite, 프론트 React 19 + TypeScript + Vite + Tailwind v4 + shadcn/ui, 차트는 Recharts + lightweight-charts, 서버 상태는 TanStack Query. 전부 로컬 실행(백엔드 :8000, 프론트 :5173), 배포 없음.

**맥락·이유**: 1인 사용 개인 리서치 도구 — 무료 데이터(DART·pykrx·yfinance·FDR) + 구독 LLM + 로컬 실행으로 월 운영비 ~0원. URL을 상태의 단일 소스로 삼는 것(useState 모드 관리 금지), 전 화면 5-state, 상승=빨강/하락=파랑(한국 컨벤션) 등 UI 규약은 CLAUDE.md·docs/policies/에 규칙화.

**참조**: 커밋 e34bc3c · CLAUDE.md · docs/policies/
