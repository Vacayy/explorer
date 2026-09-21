# 종목 발견 성능 — 병목 지도·측정·개선 기록

종목 발견(시장 CodeAct, [market-codeact.md](market-codeact.md)) 실행 한 번이 어디에 시간을 쓰는지 측정하고, 개선을 적용할 때마다 전후 수치를 이 파일에 이어 쓴다. 측정 방법을 먼저 고정해 두어 개선 전후를 같은 잣대로 비교한다. 결정 이유는 DECISIONS, 구조 변경은 SYSTEM에 두고 여기에는 **측정치와 진단**만 남긴다.

## 0. 현재 상태 요약 (2026-09-21)

| 실행 유형 | 현재 | 목표 |
|---|---|---|
| 자연어 실행(모델 3콜, 조건 3개) | 46초 / $0.11 | 25초 이하 / $0.07 이하 |
| 선택 실행(모델 0콜) | 12~21초 | 5초 이하 |
| 같은 질문 재실행 | 위와 동일 | 1초 이하(결과 캐시) |

개선 상태표는 §5 맨 아래.

## 1. 측정 방법

- **저장된 실행의 단계 시간**: `logs/market-analysis/runs/*/events/*.json`의 `analysis.state` 이벤트가 `phase`와 ms 타임스탬프를 가진다. 연속 phase 전이 간격이 그 단계의 소요 시간이다. 스크립트는 events 디렉터리를 순서대로 읽어 `queued → isolation → snapshot → analysis → calculation → verification → finished` 구간을 뽑는다.
- **단계 내부 분해**: `export_snapshot`·`analytics.screen`은 cProfile로 in-process 프로파일. 샌드박스(`runtime.Sandbox`)는 `print(1)`·import만·전체 계산 3종 코드를 같은 스냅샷에 돌려 기동비를 분리.
- **모델 호출 고정비**: 운영과 같은 격리 플래그로 `claude -p`에 `{"q":"say ok"}`를 보내는 빈 호출. `--output-format json`의 `duration_ms`(CLI 내부)·`duration_api_ms`(API 왕복)와 셸 wall time을 비교하면 프로세스 기동·API·생성 시간이 갈린다.
- 표본 스냅샷: `5a5e798c…`(2026-09-18 기준, 137만 행·2,992종목). 표본 spec: `high_52w + sma_bullish_order + volume_increase`(실행 `e6a141ab`).

## 2. 병목 지도 (개선 전)

### 2.1 단계별 시간 — 저장된 실행 36개

| phase | 실제로 하는 일 | 중앙값 | 최대 |
|---|---|---|---|
| isolation | preflight + **모델 호출 1**(질문 → spec 해석) | 11.0s | 178s(실패 실행) |
| snapshot | SQLite 137만 행 → Parquet 내보내기, 실행마다 새 폴더 | 7.4s | 10.3s |
| analysis | **모델 호출 2**(실행할 Python 작성) | 11.0s | 38.1s |
| calculation | 샌드박스 계산(2~7s) + **모델 호출 3**(`finish` 선언, ~10s) | 12.0s | 45.4s |
| verification | 같은 계산을 별도 샌드박스에서 독립 재계산 | 2.3s | 6.5s |

표본 실행 `e6a141ab`(46.2s): isolation 9.8 → snapshot 7.5 → analysis 10.0 → calculation 14.6 → verification 4.0. 모델 ≈ 30s(65%), 백엔드 ≈ 16s(35%).

모델 0콜인 선택 실행 8건: 11.7~21.4s = snapshot 7.2~10.3 + calculation 2.0~6.8 + verification 1.7~6.5. **이것이 백엔드만의 바닥이다.**

### 2.2 스냅샷 내보내기 — 7.4s (프로파일 13.7s, 프로파일 오버헤드 포함)

| 구간 | 시간(프로파일) | 비고 |
|---|---|---|
| SQLite 읽기(`fetchmany` 171회 + execute) | 2.3s | 전 행 스캔. 인덱스로 줄지 않음 |
| 행별 Python 검증 `_bad_prices`·`_number`·`_iso_date`·정규식 | ~7s | 137만 행 × 7열, 순수 Python 루프 |
| Parquet 쓰기(pyarrow) | 0.3s | |
| sha256 (21MB) | 0.008s | 무시 |

부산물: 실행마다 21MB 새 폴더. 현재 20개·421MB. 시세는 하루 한 번(16:10 ingest) 바뀐다.

### 2.3 계산 — 3.7~4.1s (조건 3개 × 2,992종목)

| 구간 | 시간 | 비고 |
|---|---|---|
| 샌드박스 기동(`sandbox-exec` + `python -I`) | 0.07s | 무시 |
| duckdb + analytics import | 0.19s | 무시 |
| DuckDB `read_parquet` → Python dict 행 변환 | ~1.2s | `_series` 2,993회 |
| `evaluate_strategy` 7,962회 | 5.8s(프로파일) | 종목×조건 순수 Python. `_sma`·`_lines`·`_finite_number` 142만 회 |
| `_valid_price` 81만 회 · `date.isoformat` 445만 회 | ~2.2s(프로파일) | 같은 날짜를 조건마다 다시 문자열화 |

검증 단계는 위 계산을 그대로 한 번 더 한다(D-176 독립 재계산). 계산이 빨라지면 같이 빨라진다.

### 2.4 모델 호출 — 콜당 ~10s, 3콜

빈 호출(운영 플래그 동일, 4회):

| 모델 | wall | CLI `duration_ms` | `duration_api_ms` |
|---|---|---|---|
| haiku | 3.6s / 2.9s | 2.6s / 1.7s | 1.5s / 1.5s |
| sonnet | 2.5s / 3.3s | 1.5s / 2.2s | 1.2s / 2.0s |

→ 프로세스 기동 + 인증 ≈ 1.0~1.3s, API 왕복 ≈ 1.2~2.0s. 실제 호출이 ~10s인 나머지 7~8s는 **모델의 출력 생성 시간**(plan 문장 + spec/코드 JSON 수백 토큰). 요청 본문은 8KB로 작다(첫 호출만 카탈로그 60개 30K자 포함, 이후는 선택 조건만 1.1K자).

## 3. LLM 쪽 진단

### 3.1 `claude -p` 자체가 문제인가? OpenRouter·로컬 모델로 바꾸면 나아지나?

- CLI가 더하는 고정비는 콜당 약 1~1.3초(위 표). 3콜이면 3~4초, 전체 46초의 8%. 직접 API(OpenRouter 포함)로 바꿔 얻을 수 있는 최대치가 이 정도다. 호출당 7~8초를 차지하는 생성 시간은 어떤 경로로 부르든 같다.
- 이 프로젝트는 API 키를 붙일 수 없다(2026-08-18 사용자 확인, 로컬 실행 제약). OpenRouter도 키가 필요해 같은 제약에 걸린다.
- 로컬 모델은 왕복은 없지만 생성이 느리다. 랩탑에서 20~40 tok/s면 500토큰 출력에 12~25초로 지금보다 느리고, spec 해석·코드 작성 정확도도 sonnet보다 떨어질 가능성이 높다. 격리 계약(D-176)을 로컬 서버로 다시 검증해야 하는 비용도 든다.
- 결론: 경로를 바꾸는 것은 병목이 아니다. **호출 횟수**(3 → 1~2)와 **출력 길이**를 줄이는 것이 지렛대다.

### 3.2 `finish` 왕복은 왜 있고, 어떻게 동작하며, 무엇을 잃고 얻나

동작. 루프는 모델 액션 `interpret → run_python → finish`로 돈다(`runner.py` 메인 루프, `models/market_analysis.ModelAction`).
1. `run_python`: 모델이 쓴 코드를 호스트가 샌드박스에서 실행하고 관찰(id·exit code·stdout·stderr)을 만든다.
2. 호스트는 그 관찰을 다음 요청의 `observations`에 넣어 **모델을 다시 부른다**. 모델은 stdout을 읽고 "결과 파일이 제대로 만들어졌다"고 판단하면 `finish{result_path, evidence_ids}`를 낸다. 결과가 이상하면 코드를 고쳐 다시 `run_python`.
3. 호스트는 `_finish`에서 evidence_ids가 성공한 관찰인지, 스냅샷 해시가 그대로인지 확인하고 result.json을 읽어 독립 재계산으로 대조한다.

왜 필요했나. 범용 CodeAct에서는 호스트가 "결과가 완성됐는지"를 모른다. 코드가 exit 0으로 끝나도 파일을 안 썼거나 잘못된 경로에 썼을 수 있고, 모델이 탐색 단계를 더 원할 수도 있다. 완료 판단을 모델에 맡기고 대신 `evidence_ids`로 "성공한 실행에서 나온 결과만 완료로 인정"하게 묶은 것이 D-176의 무결성 장치다.

효과와 비용. 모든 정상 실행에 콜 하나가 더 들어간다. ~10초, 약 $0.03~0.04(실행 비용의 1/3). 그런데 저장된 자연어 성공 실행 18개 중 `run_python`을 두 번 이상 돈 것은 6건이고(나머지 12건은 첫 실행이 곧 결과), 카탈로그 모드의 코드는 사실상 전부 `analytics.screen(data_dir, spec)` 호출 + JSON 저장이다. 결과 완성 여부는 호스트가 결정적으로 알 수 있다: exit 0, `result.json`이 존재하고 JSON 객체이며 `status`·`items`·`spec` 키를 가진다.

제안. 관찰이 그 조건을 만족하면 호스트가 `finish{result_path='result.json', evidence_ids=[그 관찰]}`을 스스로 합성해 `_finish`로 들어간다(선택 실행이 이미 그렇게 한다 — `runner.py`의 explicit 분기). 만족하지 않으면 지금처럼 모델에 관찰을 돌려준다. 잃는 것은 `finish.summary`(모델의 마무리 문장)인데, 호스트는 이 값을 result에 넣지 않고 화면도 읽지 않는다(`runner.py`·`AnalysisResults.tsx`에 참조 없음). 독립 재계산·해시 검증은 그대로다.

### 3.3 Jev(TypeSafe AI)로 나아질 수 있나 — 리서치

Jev는 2026-09-15 얼리액세스로 나온 "System One" 모델이다. 텍스트를 생성하지 않고, 상태(텍스트·프로그램 상태)와 사전에 정의한 출력 구조를 받아 **타입이 고정된 확률적 결정**을 돌려준다. 분류·라우팅·점수·추출·분기용이고, 응답 70~500ms, 입력 $0.042/MTok·출력 무료. ([TypeSafe 소개](https://typesafe.ai/blog/introducing-system-one-models-and-jev), [LangChain 하네스 글](https://www.langchain.com/blog/building-a-harness-with-jev), [TechCrunch](https://techcrunch.com/2026/09/18/a-new-kind-of-ai-model-from-a-chatgpt-inventor-is-thrilling-developers/), [DataCamp](https://www.datacamp.com/blog/system-one-models-jev))

우리 루프에 대입하면:

| 콜 | 성격 | Jev 적합성 |
|---|---|---|
| 1 해석(질문 → spec) | 60개 조건 중 다중 선택 + `within_days`·매개변수 추출 + 미지원 조건 서술 + plan 문장 | 조건 선택은 "classify/extract"라 맞다. 매개변수 숫자 추출도 가능하다고 주장. 그러나 두루뭉술한 질문("바닥 찍고 올라오는 거")을 조건 조합으로 푸는 추론과 `unsupported_conditions` 서술은 텍스트 생성이 필요해 어렵다 |
| 2 코드 작성 | Python 생성 | 불가(텍스트 생성 안 함) |
| 3 finish 판단 | "결과가 완성됐나" 결정 | 맞는 유형이지만 §3.2대로 결정적으로 풀 수 있어 모델 자체가 불필요 |

판단: 지금 가장 큰 두 병목(finish 콜, 스냅샷)은 Jev 없이 결정적으로 없어진다. Jev가 줄일 수 있는 것은 해석 콜 10s → 0.5s인데, (a) 얼리액세스 대기열이고 (b) API 키가 필요해 이 프로젝트의 자격증명 제약(§3.1)에 걸리며 (c) 정확도 검증 데이터가 없다. **후보로 기록해 두고, 결정적 개선을 먼저 끝낸 뒤 해석 콜만 A/B로 시험**하는 순서가 맞다. 시험 시 비교 대상은 refine(D-186)의 조건 후보 목록과 같은 입력이다.

## 4. 백엔드 최적화 기법별 적용 가능성

| 기법 | 적용 대상 | 예상 효과 | 설계 충돌 |
|---|---|---|---|
| **캐싱 ① 스냅샷 재사용** | 원본 DB 지문(최신 거래일·행 수·`PRAGMA data_version`)이 같으면 기존 스냅샷 폴더를 가리킨다. 해시 검증·읽기 전용은 그대로 | 실행당 -7.4s, 디스크 증가 정지 | D-176 "실행마다 고정 스냅샷"의 구현만 바뀜(정신 동일). DECISIONS 기록 |
| **캐싱 ② 결과 캐시** | (스냅샷 해시, 정규화 spec 해시, 스킬 해시) → 검증 완료 result | 같은 질문 재실행·후속 질문 부모 조건 0s | 없음. 재실행은 새 run id에 캐시 출처를 기록 |
| **캐싱 ③ 일일 신호 사전계산** | 16:10 ingest 뒤 51개 일봉 조건 × 전 종목을 한 번 평가해 표로 저장, 질의는 AND 조회 | 계산 4s → ms. 기술적 분석 스캔·감시 규칙도 같은 표를 씀 | 크다. CodeAct의 계산이 스냅샷 밖 표에 의존하면 격리·독립 재계산 계약을 다시 설계해야 함. **후순위** |
| **배치/벡터화** | `evaluate_strategy` 종목별 Python 루프 → DuckDB 윈도 함수(SMA·rolling max/min·전일 대비)로 전 종목 한 번에, 또는 pandas groupby 벡터 | 계산·검증 4s → 1s 이하 추정 | 스킬 파일이 바뀌므로 카탈로그 버전·테스트 54개로 등가 증명 필수 |
| **행 검증의 SQL 이동** | 스냅샷 내보내기의 Python 행별 검증 → SQL `WHERE`/pyarrow 벡터 필터 | 7.4s 중 ~4s 감소(재사용이 안 걸리는 첫 실행에만 의미) | 없음 |
| **인덱싱** | `stock_prices` 인덱스 | 효과 없음 — 내보내기는 전 행 스캔이고 읽기 2.3s는 순차 I/O | — |
| **조기 탈락** | AND 조건에서 첫 탈락 후 나머지 건너뛰기 | 탈락 종목이 많을 때 계산 절반 | 탈락 종목의 조건별 `checks`가 사라져 화면 "왜 탈락했나" 표시가 바뀜. 보류 |
| **날짜 1회 변환** | Parquet에 날짜를 문자열로 두고 `isoformat` 445만 회 제거 | 계산 -0.5s | 없음 |
| 폴링 | UI는 SSE + 2.5s 폴링 | 최대 2.5s 표시 지연 | 이미 SSE 있음. 변경 불필요 |

## 5. 개선 계획과 상태

권장 순서: 효과 큰 것부터, 설계 충돌 없는 것부터.

| # | 항목 | 예상 | 상태 | 측정(적용 후) |
|---|---|---|---|---|
| 1 | 호스트가 finish 합성(§3.2) | -10s, -$0.035 | 제안 | |
| 2 | 스냅샷 재사용(캐싱 ①) | -7.4s | 제안 | |
| 3 | 결과 캐시(캐싱 ②) | 재실행 0s | 제안 | |
| 4 | 계산 벡터화 + 날짜 1회 변환 | -3~6s(계산+검증) | 제안 | |
| 5 | 행 검증 SQL 이동 | 첫 실행 -4s | 제안 | |
| 6 | 해석 콜을 haiku/Jev로 A/B | -3~9s | 후보 | |
| 7 | 일일 신호 사전계산(캐싱 ③) | 계산 ms | 후순위 | |

1+2만으로 자연어 실행 46s → 약 29s, 선택 실행 12~21s → 5~14s. 4까지면 각각 ~25s, ~5s.
