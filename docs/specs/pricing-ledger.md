# 시장 프라이싱 원장 — 시장이 지금 무엇을 가격에 반영하고 있나

상태: P0 구현(2026-10-27). 화면: 탐색 › 국면 이력 '지금 시장 읽기' §5. 재료: 매일 아침 미국장 브리핑([us-briefing](us-briefing.md))과 이미 수집 중인 시장 지표.

## 1. 왜

브리핑은 매일 저장되지만 그날 하루치로만 읽혔다(홈 화면·대화 도구·텔레그램). 날짜를 이어 보면 "어떤 전제가 언제 처음 나왔고, 얼마나 이어지고, 언제 사라졌나"가 보인다. 이것을 가격 지표의 변화와 나란히 두면 **시장이 무엇을 가격에 반영하는지와 그 변화**를 관찰할 수 있다. 조건 → 행동 계획(시나리오 플레이북)은 이 원장을 몇 주 써 본 뒤 따로 설계한다.

## 2. 두 층

| 층 | 무엇 | 만드는 법 |
|---|---|---|
| 가격 층 | 시장 가격에 직접 드러난 기대 — 2년 금리(정책 경로)·10년·5년 뒤 5년 기대인플레·기간 프리미엄·HY 스프레드·VIX·달러·금 | `market_indicators`의 기존 계열에서 지금 값과 1주·4주 변화를 읽을 때 계산(LLM 0) |
| 이야기 층 | 브리핑이 말하는 '시장이 전제로 삼고 움직이는 것' — 예: "FOMC는 동결한다", "유가에 이란 위험 프리미엄이 붙어 있다" | 브리핑 하루마다 LLM 1회로 전제 주장을 뽑고, 기존 전제와 같으면 이어 붙인다 |

**전제(claim)의 정의**: 사건이 아니라 시장이 가격에 반영하고 있는 기대·믿음. 여러 날에 걸쳐 같은 문장으로 다시 쓸 수 있어야 한다(날짜·수치를 문장에 박지 않는다). 하루 최대 6개.

## 3. 추출 (`pipeline/pricing_ledger.py`)

- 입력: 그날 브리핑의 지수 요약·동인·개별 이슈·핵심 포인트, 출처 목록, 최근 45일 안에 관측된 전제 목록(id·문장·테마).
- 출력(JSON): 기존 전제 관측 `{claim_id, stance, evidence, sources}` · 새 전제 `{statement, theme, evidence, sources}`. stance = `present`(그대로)·`stronger`(강해짐)·`weaker`(약해짐)·`contested`(반론 등장).
- 테마: rates·inflation·growth·credit·geopolitics·energy·ai·sector·fx·policy·other.
- 모델: sonnet(effort low). 브리핑 signature가 같으면 다시 뽑지 않는다(`pricing_days`). 기존 57일은 날짜 오름차순으로 소급 추출한다(그날까지의 전제 목록만 보이므로 미래 정보가 섞이지 않는다).
- 매일 07:30 `scripts/compute_briefing.py`가 브리핑을 만든 직후 그날을 추출한다. 실패해도 브리핑 발행은 막지 않는다.

## 4. 데이터

| 테이블 | 내용 |
|---|---|
| `pricing_claims` | id·statement·theme·first_seen·last_seen·created_at |
| `pricing_observations` | (trade_date, claim_id) PK·stance·evidence·sources_json([{publisher,title,url,doc_id}]) |
| `pricing_days` | trade_date PK·signature(브리핑)·model·new_claims·observed·created_at |

## 5. 읽기 — 변화 관찰

`read(weeks)`:
- 전제마다 관측 날짜·처음/마지막 관측·관측 일수·최근 stance·최근 근거.
- 상태(마지막 브리핑일 기준): **새로 등장**(처음 관측이 최근 5거래일 안) · **강해짐**(최근 5거래일 안 stronger) · **약해짐**(최근 5거래일 안 weaker·contested) · **사라짐**(최근 5거래일 관측 없음, 그 전 20거래일 안 3회 이상) · **지속**.
- 가격 층 표와 테마별 관련 지표(rates→2년·10년, inflation→기대인플레, credit→HY, geopolitics·energy→유가·금, fx→달러, policy→기간 프리미엄).

## 6. API · 대화 · 해설

- `GET /api/spine/pricing?weeks=8` — 가격 층·전제 목록(관측 날짜 포함)·이번 주 변화 요약·브리핑 날짜 축.
- `POST /api/spine/pricing/extract` — 아직 추출 안 한 브리핑 날짜를 오름차순으로 추출(소급·수동).
- 대화 도구 `get_pricing_ledger(weeks)` — "시장이 뭘 반영하고 있나·최근 바뀐 전제·언제부터" 질문에.
- 국면 이력 AI 해설 입력에 최근 5거래일의 새로·강해짐·약해짐 전제를 더한다.

## 7. 화면 (지금 시장 읽기 §5 '시장이 가격에 반영하는 것')

1. 읽는 법 단락.
2. 이번 주 변화 — 새로 등장·강해짐·약해짐·사라짐 칩.
3. 가격 층 표 — 지표·지금·1주·4주 변화.
4. 전제 타임라인 — 행 = 전제(테마 배지), 열 = 브리핑 날짜, 점 = 관측(색 = stance). 행을 누르면 최근 근거와 출처.

## 8. 5-state

Empty(브리핑 없음 → 안내. 추출 전 날은 아침 브리핑 작업이 잇고 화면엔 띠의 빈 칸으로만 — 2026-11-05 '소급 추출' 버튼 제거, ia-redesign §4.28) · Loading Skeleton · Error ErrorState · Partial(가격 지표 일부 결측은 '-') · Ideal §7.

## 9. 범위 밖

조건 → 행동 시나리오 플레이북(별도 설계), 전제별 시장 반응 계량(전제 등장일 전후 지표 변화), 한국장 브리핑 원장.
