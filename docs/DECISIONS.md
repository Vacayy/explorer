# Explorer — 의사결정 로그 (append-only)

> **규칙**: 이 파일은 결정의 *이유*를 보존하는 append-only 로그다.
> - 기존 항목은 **수정·삭제 금지**. 결정을 뒤집으면 새 항목으로 쓰고, 원 항목 끝에 `→ D-0XX에서 번복` 한 줄만 추가한다.
> - 최신 항목이 **맨 위**. 번호는 시간순 오름차순(다음 번호 = 최대 번호 + 1).
> - 기록 대상: 되돌리기 비싼 결정, 대안을 기각한 결정, "왜 이렇게 돼 있지?"가 나올 결정.
>   사소한 구현 선택·버그 수정은 커밋 메시지로 충분 — 여기 쓰지 않는다.
> - 형식: 결정 / 맥락·이유 / 기각한 대안 / 참조(커밋·파일·문서).
> - 현재 시스템 구조는 [SYSTEM.md](SYSTEM.md), 전략·지표는 [STRATEGY.md](STRATEGY.md), 우선순위는 [BACKLOG.md](BACKLOG.md).

---

## D-108 · 2026-08-18 · 전일 국장 거래대금 상위 — 미국장 대응물이되 LLM 0 (feat/conviction-loop)
**결정**: 홈에 **전일 국장 거래대금 상위 20** 카드를 신설한다(`KrMoversSection`, 미국장 브리핑 바로 아래). 미국장(D-094·D-095)과 같은 물음("어제 돈이 어디로 몰렸나")에 답하되 **종합 산문(sonnet)은 붙이지 않는다** — 표 + 섹터 쏠림 + 개별 이슈까지 전부 결정적 계산(LLM 0콜). 소스는 `fdr.StockListing("KRX")` 1콜(거래대금 `Amount`·등락률 `ChagesRatio`·시장·시총 동시 수령) — pykrx 시장 단위 엔드포인트는 KRX 로그인이 필요해져 쓰지 않는다(`ingest_prices.py`와 같은 이유). 신규 모듈 `pipeline/kr_movers.py` · 테이블 `kr_movers`(일별 스냅샷, 7일 보존) · 라우터 `GET /api/spine/kr/movers?force=` · launchd 잡 `dev.explorer.krmovers`(평일 16:20). 판정 규칙(급등락 |8%|·그룹 역행·신규 진입)과 status(ok/stale/error) 계약은 `us_briefing`과 **의도적으로 동일**하게 맞췄다 — 두 시장을 나란히 읽을 때 어휘가 달라지면 비교가 안 된다.

**맥락·이유**: 사용자 — "국장 거래대금 상위도 보이면 좋을 것 같거든? 미국장 처럼.. 이건 웹에 일단 추가할 기능." 미국장은 이미 아침 분위기 파악의 진입점인데(D-095) 정작 본판인 국장에는 같은 뷰가 없었다. **LLM 0 선택**: 사용자가 "표 + 섹터 쏠림만"으로 확정 — 국장은 이미 신호·내러티브·다이제스트가 담론을 두껍게 덮고 있어 종합 산문의 한계효용이 낮고, 미국장 종합(sonnet 하루 1콜)은 '커버 밖 시장을 처음 읽는' 상황이라 값이 달랐다. 비용 의식 설계(D-072) 유지. **섹터 분류체계 통일**: `companies.sector`(KSIC, 2,760종목 커버) → `sector_map.group_name`(18개 대분류) 단일 경로. `industry_groups`(큐레이션 119종)와 섞으면 같은 카드 안에서 "반도체"와 "반도체·전자부품"이 공존해 라벨 어휘가 깨진다. **우선주 섹터 폴백**: `companies`가 DART corp_code 기반이라 우선주 행이 없어 삼성전자우가 '미분류'로 빠졌다 → 본주 코드(005935→005930)로 폴백. **'미분류'는 클러스터에서 제외**: 섹터가 아니라 매칭 실패 버킷이라, 묶으면 성격이 제각각인 종목들의 중앙값이 나와 **그룹 역행 판정까지 오염**시켰다(실측: 삼성전자우 +2.25%가 미분류 중앙값 -6.0% 대비 '그룹 역행'으로 오탐).

**기각한 대안**: **(a) `stock_prices`에서 종가×거래량으로 계산** — 이미 있는 데이터라 추가 수집이 없지만 ①거래대금의 근사일 뿐이고 ②`ingest_prices`가 랩탑 수면으로 자주 걸러 최신이 2026-08-13에 멈춰 있었다(D-106 이전). 원천이 `Amount`를 직접 주는데 근사할 이유가 없다. **(b) pykrx `get_market_ohlcv_by_ticker`** — 거래대금을 정확히 주지만 KRX 로그인 요구로 이미 프로젝트에서 폐기된 경로. **(c) 미국장과 완전 대칭(sonnet 종합 포함)** — 위 이유로 사용자가 기각. 붙일 자리(`_synthesize` 대응)는 남겨뒀다. **(d) ETF·리츠·스팩 포함** — 거래대금 상위를 ETF가 잠식해 '어느 사업이 화두인가'가 안 보인다. FDR 리스팅에 종류 컬럼이 없어 이름 토큰(KODEX·TIGER·스팩·리츠…)으로 제외 — 취약하지만 스키마 검증(`MoversSourceError`)이 붕괴를 잡는다.

**참조**: `backend/pipeline/kr_movers.py` · `backend/models/kr.py` · `backend/routers/spine_kr.py` · `backend/database.py`(kr_movers DDL) · `frontend/src/components/home/KrMoversSection.tsx` · `frontend/src/hooks/useKrMovers.ts` · `scripts/snapshot_kr_movers.py`

---

## D-107 · 2026-08-18 · 텔레그램 브리핑을 **누르는 브리핑**으로 — 버튼이 곧 생성 착수점 (docs/specs/telegram-briefing.md, feat/conviction-loop)
**결정**: 아침 브리핑에 ①**어젯밤 미국장**(캐시된 `us_briefings` 종합 + 쏠림·개별이슈) ②**어제의 주제 = 최다 3 + 급상승 2** ③**팔로우 유튜브 최근 3일**을 싣고, ②③을 **inline keyboard 버튼**으로 낸다. 누르면 `bot.py`의 콜백 핸들러가 **기존 생성 로직을 그대로** 돌려(주제→`compute_narrative`, 영상→`spine_doc.get_document`의 lazy digest) 결과를 같은 대화로 회신한다. 새 파이프라인은 만들지 않았다. 조립 자체는 **LLM 0콜**(전부 SQL + 이미 만들어진 캐시 읽기)이고, 비싼 생성은 **사람이 누른 것만** 돈다(D-020 계승). 콜백은 즉시 `answerCallbackQuery` + 선응답 후 **데몬 스레드**에서 실행(폴링 루프 비차단), 주제/문서 단위 `_inflight` 잠금으로 연타 시 opus 중복 기동을 막고, 4,000자 초과 응답은 문단 경계로 분할 발송한다.

**맥락·이유**: v1 브리핑은 초창기(D-056) 재료에 멈춰 실측 155~322자였다 — `기계의 3줄` + 오늘 일정 + 업데이트 **건수**뿐. 그 사이 홈은 미국장 브리핑(D-095~097)·시장 국면(D-076)·매크로 유동성(D-101)으로 자랐는데 텔레그램은 따라가지 않았고, 정작 출근길 폰에서 가장 값진 미국장이 빠져 있었다. 더 근본적으로 v1은 **읽고 끝**이었다 — "홈에서 확인"이라 써놓고 링크는 `localhost`라 폰에서 열리지 않는다. 도구 앞에 앉기 전까지 브리핑은 죽은 텍스트였다. 버튼을 달면 **가방 속에서 관심 항목을 눌러 생성을 걸어두고, 앉았을 때 판단 재료가 준비돼 있다**. v2 실측 1,457자 · 버튼 11개. **주제 top5 = 최다 3 + 급상승 2 (사용자 확정)**: 절대 최다만 쓰면 매일 같은 얼굴(AI·반도체·자동차)이고, 급상승(`theme_surge`)만 쓰면 "어제 무엇이 화두였나"에 답하지 않는다. 둘을 섞어 판의 크기와 변화를 함께 준다. 최다 집계에는 `THEME_STOPWORDS`(문서유형 메타 라벨) 제외가 **필수** — 실측상 제외 전엔 산업동향 127·실적분석 80·밸류에이션 53이 상위를 독식한다.

**알고 수용한 제약**: 발송은 launchd라 서버와 무관하지만(D-106) **콜백은 백엔드 서버가 떠 있을 때만** 처리된다(봇 폴링이 FastAPI startup 스레드). 랩탑이 가방에 있는 동안 누른 버튼은 텔레그램 `getUpdates` 백로그(최대 24h)에 남아 **서버가 켜지는 즉시 처리**된다 — "즉시"는 보장 못 해도 "유실"은 없다.

**기각한 대안**: **(a) 콜백을 launchd 폴러로 이중화** — 서버가 꺼져 있어도 즉시 처리하려 했으나, 같은 봇 토큰에 `getUpdates` 소비자가 둘이 되면 업데이트를 서로 훔쳐 메시지가 유실된다. 지연 수용이 낫다. **(b) 버튼 대신 URL 링크** — 로컬 서버(`localhost:5173`)라 폰에서 열리지 않는다. 애초에 v1이 실패한 지점. **(c) callback_data에 주제명 문자열** — 64바이트 상한이라 긴 한글 주제가 잘린다 → entity_id/doc_id를 싣고 핸들러에서 해소. **(d) 브리핑 생성 시점에 미리 내러티브를 만들어 첨부** — 매일 아침 opus 5콜이 고정비로 붙는다. 제안 먼저·노동은 승인 뒤(D-020).

**참조**: docs/specs/telegram-briefing.md · `backend/pipeline/notify.py`(`compose_briefing`·`_us_section`·`_topics`·`_youtube_recent`·`_keyboard`) · `backend/pipeline/bot.py`(`handle_callback`·`_run_narrative`·`_run_youtube`·`_chunks`)

---

## D-106 · 2026-08-18 · 스케줄러를 cron → launchd로 — 키체인(LLM 인증)과 놓친 스케줄이 같은 뿌리였다 (feat/conviction-loop)
**결정**: 모든 정기 작업(30분 수집 체인 + 6개 단발 잡)을 crontab에서 **launchd user agent**(`~/Library/LaunchAgents/dev.explorer.*`)로 옮긴다. 설치기는 `scripts/install_launchd.py`(plist 생성 + `launchctl bootstrap gui/$UID`, `--dry-run`·`--uninstall`). crontab은 포인터 주석만 남기고 비우며, 원본은 `scripts/crontab.legacy.bak`으로 보존(롤백 1줄). 더불어 브리핑 발송에 **이중 안전망**: ①모든 시도를 `job_runs('send_briefing')`에 ok/skipped/error로 기록 ②30분 체인이 `send_briefing.py --catch-up`으로 평일 08:00 이후 미시도분을 사후 발송(멱등 — ok/skipped는 완료로 보고 error만 재시도) ③`send_telegram`은 망 실패를 삼키지 않고 3회 재시도(5s·10s 백오프). 그리고 **LLM 엔진 생사 프로브**(`scripts/probe_llm.py` → `ops.probe_llm`, `job_runs('llm_probe')`): 정상이면 하루 1콜, 고장 중이면 매 회차 재시도(복구 즉시 감지)하는 비대칭 폴링. 실패 시 `ops.llm_down_reason()`이 홈 브리핑 **최상단 경고**로 노출되고, 그 경고가 텔레그램 브리핑에도 그대로 실린다.

**맥락·이유**: "아침 브리핑이 오는 날도 있고 안 오는 날도 있다"는 사용자 관찰을 파고들다 **두 개의 독립된 고장이 같은 뿌리**임을 발견했다. ① **발송 41%** — 평일 22일(7/20~8/18) 중 발송 9일. 로그상 `sent: False`가 **0건**이라 "보낼 내용이 없어서"가 아니라 **cron이 아예 안 뜬 것**이 전부였다. macOS cron은 놓친 작업을 기상 후 재실행하지 않는데, 08:00은 랩탑이 가방 속에서 자는 시각이다(8/18 전원 로그: 07:57 Sleep → 08:07 DarkWake(cron 미실행) → **08:18:44 lid Wake**, 그날 첫 체인은 08:30). ② **cron의 LLM이 한 달째 전멸** — `Not logged in · Please run /login` **45,294건**(7/17~8/18). claude CLI 자격증명이 **macOS 키체인**(`Claude Code-credentials`)에 있는데 cron은 GUI 로그인 세션 밖이라 접근이 거부된다. 그 결과 enrich는 키워드 fallback(이틀간 2,916건), 유튜브 정리본은 `failed 223 / ok 116`으로 고착, `redigest_youtube`는 `정리본 0 · 실패 5`만 반복, vision·extract_events·digests도 전부 실패. **각 파이프라인이 조용히 fallback해 표면상 돌아가는 것처럼 보인 탓에 한 달간 아무도 몰랐다** — 이것이 프로브를 별도 신호로 세운 이유다. launchd user agent는 사용자 Aqua 세션에 적재되어 키체인이 열리고(②), `StartCalendarInterval`·`StartInterval`은 기상 시 놓친 회차를 실행한다(①). 즉 **한 번의 이전으로 두 고장이 함께 풀린다**. 가설은 추정으로 두지 않고 실측했다: 동일 `claude -p`를 launchd 프로브로 실행 → `OK`(cron은 `Not logged in`), 이어 `redigest_youtube` 1건을 launchd로 → **`정리본 1 · 실패 0`**(한 달 만의 첫 성공).

**기각한 대안**: **(a) `ANTHROPIC_API_KEY` 추가** — 인증 문제를 우회하는 가장 단순한 길이지만 사용자가 "당장은 API 키를 못 붙인다"고 명시. 게다가 `llm_engine()`이 `ENRICH_ENGINE=claude-code`를 우선 반환해 키가 있어도 게이트 수정 없이는 안 쓰인다. launchd 이전은 **키 없이** 같은 문제를 푼다. **(b) `pmset repeat wakeorpoweron`으로 07:55 자동 기상** — 발송 시각 문제만 풀고 키체인 문제는 그대로. 게다가 배터리로 가방 속에서 매일 강제 기상시키는 부작용. **(c) cron 유지 + 캐치업 가드만** — 브리핑은 살아나도 나머지 LLM 파이프라인은 계속 죽어 있다. **(d) 캐치업을 launchd로 대체하고 생략** — launchd가 기상 시 실행하지만 *전원이 꺼져 있던* 경우·*발송이 망 실패로 error 난* 경우는 못 덮는다. 30분 체인 편승은 비용 0(발송 완료면 SQL 1회 후 즉시 반환)이라 마지막 그물로 남겼다. **(e) LLM 실패를 로그 grep으로 모니터링** — 이미 로그에 45,294건이 있었는데도 한 달간 못 봤다는 것이 이 방식의 반증. 명시 신호(job_runs + 홈 최상단 경고)로 격상.

**참조**: `scripts/install_launchd.py` · `scripts/probe_llm.py` · `scripts/crontab.legacy.bak` · `backend/pipeline/notify.py`(`ensure_briefing_sent`·재시도) · `backend/pipeline/ops.py`(`probe_llm`·`llm_down_reason`) · `backend/routers/spine_home.py`(최상단 경고) · `scripts/run_chain.sh`

---

## D-105 · 2026-08-13 · 교차 종합의 층위 = 업황(종목 아님) + 인용은 자연어(번호 참조 금지) (D-104 후속, feat/conviction-loop)
**결정**: D-104 첫 산출물에 대한 사용자 피드백 2건을 프롬프트 규율로 못박는다. **(A) 층위 = 업황·판세** — 개별 종목 투자 판단(밸류에이션·목표주가·매수매도·그 회사만의 리스크)으로 좁히지 않는다. 자료가 특정 기업의 것이어도 그 기업은 **산업을 읽는 표본**으로 다뤄 "이 사실이 산업의 수요·공급·가격·자본조달·경쟁구조 중 무엇을 어디로 움직이는 증거인가"로 옮긴다. 섹션도 개편: `공통 축`→**`판의 구조`**(각 항목이 산업의 어느 축을 움직이나), `이 묶음이 던지는 질문`→**`업황이 던지는 질문`**("이 회사 주가가 오를까"가 아니라 "이 구조가 지속되는가·무엇이 판을 뒤집는가"). 안전장치: 재료가 한 기업 이야기뿐이라 넓힐 근거가 없으면 **억지 일반화 대신 무엇이 부족한지** 말하게 함(정직 우선 — 층위 지시가 환각 유발기가 되지 않도록). **(B) 본문은 자기충족** — `[문서 1]`·"문서 2에 따르면" 같은 **번호 참조 금지**. 출처는 자료의 성격(경영진 컨콜 발언·제3자 분석·현직자 글) + 채널·작성자명 + 시점을 **문장 안에 자연어로** 녹인다. 이를 위해 `_gather`가 `resolve_channels()`(spine_feed 재사용)로 채널명을 뽑아 프롬프트에 주입(`_describe`: "텔레그램 채널 글 · 출처 '루팡' · 2026-08-12"). FE의 '엮은 문서' 목록에서도 `문서 N` 번호 라벨 제거 — 본문이 번호를 안 쓰므로 가리킬 대상이 없다. **(C) 출력 계약을 JSON→마크다운으로** — `# 제목` 첫 줄 + 이후 본문. 이 산출물은 산문이고 (B)가 따옴표 인용을 권장하는데, JSON 문자열 이스케이프가 실측에서 **두 번 연속 다른 이유로 깨졌다**(① 이스케이프 안 된 개행 `Invalid control character` → `strict=False`로 흡수했으나 ② 이스케이프 안 된 따옴표 `Expecting ',' delimiter`는 흡수 불가). 마크다운은 이스케이프 개념이 없어 실패 유형 자체가 사라진다 — `_parse`가 첫 `# ` 줄만 제목으로 떼고 나머지를 body로. 겸사 실패 원인을 서버 로그로 출력(502만 보고 원인 못 찾던 문제, D-104 후속 항목 해소).
**맥락·이유**: 사용자 2026-08-13, 첫 산출물('AI인프라, 약속에서 이익으로') 리뷰 — "전반적으로 좋지만 **너무 Nebius 투자 관점에서만 질문을 뽑은 느낌**. 사용자가 **크게 돌아가는 전황·업황**에 대한 인사이트를 얻어갔으면. 이게 **산업 다이내믹 측면에서** 무엇을 의미하는지." + "**문서1, 문서2에 따르면** 이런 식으로 참조하는데 비직관적. '문서 1이 뭐지?' 찾아가봐야 하잖아. **본문 그 자체로 독립적인 콘텐츠로 기능**해야." 진단: 두 문제 모두 프롬프트 층위 문제였다 — 재료가 기업 자료(컨콜·기업 분석)면 LLM 기본값은 종목 리스크로 수축하고, `[문서 N]` 표기는 내가 프롬프트에 직접 지시한 것이었다(정박을 위해 넣었으나 **정박의 형식이 독자 경험을 해쳤다** — 근거는 유지하되 표현을 자연어로 옮기는 것이 옳은 해). 개정 후 같은 3건 재생성 실측: 제목 "AI 컴퓨트, 승부처는 가격·자본력", 첫 문단이 "무게중심이 '누가 GPU를 더 쌓았나'에서 '누가 그 캐파를 어떤 가격·어떤 자금으로 매출로 전환하나'로 이동"으로 산업 층위 진술, 판의 구조=가격·자본조달·수요구성·경쟁구조 4축, 질문도 "지금의 컴퓨트 가격 상승은 엔터프라이즈 수요 확대인가 공급 병목인가"(산업 층위)로 올라옴. 번호 참조 0건 — "네비우스 어닝콜과 직원 글", "아마존 2분기를 다룬 제3자 분석"으로 자연어 인용. 상충 섹션은 오히려 더 예리해져 "세 자료 전체가 사실상 당사자 발언 + 그것을 그래프로 재구성한 해설"이라는 에피스테믹 수축을 스스로 지적.
**기각한 대안**: ① **본문 `[문서 N]` 유지 + FE에서 칩으로 linkify** — 클릭은 되지만 읽는 흐름이 여전히 끊기고, 공유·복사 시(본문만 떼어낼 때) 다시 무의미해짐. 사용자 요구는 "본문 자체로 독립"이었다. ② **각주(footnote) 방식** — 마크다운 각주 렌더 추가 필요 + 번호 문제 재발. ③ **층위를 사용자가 선택(종목/업황 토글)** — 옵션 신설은 과설계(CLAUDE.md 단순성), 사용자가 업황을 원한다고 명시. 종목 층위 판단은 이미 리포트·렌즈·업사이드 모델이 담당(층위 중복 회피). ④ **섹션 구조 유지하고 지시문만 추가** — 섹션 제목('공통 축')이 층위를 규정하는 힘이 커서 제목까지 바꿔야 실효. ⑤ **재생성 시 기존 행 갱신** — append-only 원칙(D-104 B), 구 프롬프트 산출물도 히스토리로 남긴다.
**참조**: backend/pipeline/doc_synthesis.py(_describe·_build_prompt·_gather 채널 주입·strict=False) · routers/spine_feed.py(resolve_channels 재사용) · frontend components/synthesis/SynthesisPage.tsx(번호 라벨 제거) · docs/specs/doc-synthesis.md(산출물 구조·인용 규율) · SYSTEM.md §5-1 · [[D-104]](교차 종합 신설) · [[D-049]](BLUF) · 대화 2026-08-13
**남은 한계**: `question_report._generate`(및 산문 body를 JSON으로 받는 다른 파이프라인)도 같은 이스케이프 취약성을 갖고 있음 — 이번엔 손대지 않음(범위 밖). 재발하면 같은 마크다운 계약으로 옮긴다. 구조화 출력이 필요한 파이프라인(태깅·판정 등)은 JSON 유지가 맞음 — **산문 산출물에만** 해당하는 교훈.

## D-104 · 2026-08-13 · 문서 교차 종합 — 사람이 고른 묶음을 앵커로 (docs/specs/doc-synthesis.md, feat/conviction-loop)
**결정**: 저장됨(D-078)에서 **문서를 다중선택해 엮어 읽는** 교차 종합을 신설한다. 기존 종합은 전부 **앵커가 자동 선정**이었다 — 질문 종합(D-093)=질문 앵커, 다이제스트(D-085)=기간 앵커, 내러티브=토픽 앵커, 리포트(D-041)=종목/섹터 앵커. **"사람이 손으로 고른 묶음"을 앵커로 하는 층이 비어 있었고**, 저장됨이 이미 사람의 큐레이션이므로 그 위에 선택만 얹으면 된다(큐레이션이 곧 입력). 4결정(사용자 2026-08-13): **(A) 산출물 = 교차 프레임 + 질문·추론** — 한 줄 종합(BLUF) · 공통 축(각 축에 기여 문서 `[문서 N]`) · 상충·긴장 · **이 묶음이 던지는 질문 + 각 질문의 잠정 추론**(질문만 던지고 끝내지 않는다 — 사용자 명시) · 감시 지표. **(B) 일회성** — 묶음(collection) 객체를 만들지 않는다. 선택→생성→**결과만** 저장(`doc_syntheses`), 같은 조합 재생성=새 행(append-only 히스토리). 캐시 가드(inputs_hash) 없음 — 버튼이 곧 의도. **(C) read-only 격리** — 인과그래프·질문 트래커에 아무것도 쓰지 않는다(논지 감사 D-078의 격리 규율 계승). **(D) 재북마크** — 생성된 종합 자체를 `saved_items.kind='synthesis'`로 저장 가능(산출물이 다시 북마크 대상이 되는 고리). 모델 **sonnet**(원문 위의 종합·프레이밍 — D-093 결산과 같은 결), 문서 2~12건·문서당 8,000자 클립(앞 6,000+뒤 2,000으로 컨콜 Q&A·결론부 보존). IA는 새 탭 0개(D-013) — 진입은 `/follow/saved` 체크박스+액션 바, 산출물은 아티팩트 디테일 라우트 `/synthesis/:id`(`/question/:id` 선례) + 하단 '최근 교차 종합' 재열람 목록.
**맥락·이유**: 사용자 2026-08-13 — "저장한 문서들 중 원하는 것들을 골라, 여러 개를 엮어서 이게 의미하는 바 = 인사이트를 추출." 저장됨 실데이터가 사실상 전부 `kind='doc'`이라 문서 묶음이 자연스러운 단위. **자동 선정 앵커의 사각지대**가 이 기능의 존재 이유 — 기계가 고른 토픽·기간·질문은 사람이 "이 셋을 나란히 놓으면 뭔가 보인다"고 느낀 조합을 잡지 못한다. 실측 2건: ① 레오폴드 마진콜 3건(블로그+텔레그램) → "청산의 피날레인가" — 사후 서사와 사전 추론이 섞여 있다는 긴장을 짚음. ② Nebius 컨콜 Q&A·직원 글 + AWS 2Q26 분석 → "AI인프라, 약속에서 이익으로" — **같은 플라이휠의 초기 단계 vs 완성형**으로 프레임하고, 상충에서 "문서1·2는 CEO/직원 1인칭 자사 주장, 문서3은 제3자 분석 — 같은 무게로 취급하면 안 된다"는 **에피스테믹 비대칭**을 스스로 지적(사실/가설 분리 원칙이 산출물에서 재현). 질문 4개 전부 잠정추론+미판정 정직. 60~90초/건. FE tsc 통과.
**기각한 대안**: ① **명명된 묶음(collection)+문서 추가·재종합** — 사용자가 일회성 선택("묶음 관리 UI 없음"). 스키마 3개(묶음·멤버·결과)가 1개로 줄고, 다시 고르는 비용이 관리 UI 비용보다 싸다. 필요해지면 doc_ids 스냅샷 위에 후속으로 얹을 수 있다. ② **질문 트래커 승격·인과 엣지 추출(승인 큐)** — 사용자가 read-only 선택. 종합이 뱉은 질문을 트래커로 보내면 매력적이나, 자기확증 고리(내가 고른 문서 → 종합 → 질문 → 추적)가 생기고 이번 증분의 초점(엮어 읽기)이 흐려진다. 후속 후보. ③ **kind 혼합 종합(기업·내러티브·리포트까지)** — 재료 수집 경로가 테이블별로 달라 별 기능. ④ **opus** — 4단계 모델링(업사이드·시나리오)이 아니라 제공된 텍스트 위의 프레이밍이라 sonnet으로 충분(D-093 선례·비용 의식 D-072). ⑤ **대화(RAG)에 묶음 주입으로 대체** — 새 표면 0이지만 산출물이 대화 로그에 묻혀 append-only 아티팩트가 안 됨(재열람·재북마크 불가). ⑥ **진입 시 자동 종합** — LLM 비용, 버튼 트리거(D-093 ④ 승인 게이트 정신).
**참조**: docs/specs/doc-synthesis.md · backend/pipeline/doc_synthesis.py · routers/spine_synthesis.py · database.py(doc_syntheses) · routers/spine_saved.py(kind synthesis) · frontend hooks/useSynthesis.ts · components/synthesis/SynthesisPage.tsx · follow/SavedPage.tsx·SavedList.tsx(selectable)·RecentSyntheses.tsx · SYSTEM.md §4-1·§5-1·§5-2·§6 · [[D-078]](저장됨 — 이 기능의 입력) · [[D-093]](질문 종합 — 자동 앵커 형제) · [[D-013]](새 탭 0개) · 대화 2026-08-13
**후속**: 종합 삭제·검색 · 종합이 뱉은 질문의 트래커 승격(기각 ② 재검토) · doc 외 kind 혼합 · 실패 원인 노출(현재 `_generate` 예외를 삼켜 502만 반환 — 사용량 한도 vs 파싱 실패 구분 불가, question_report와 동일 한계)

## D-103 · 2026-08-02 · 텔레그램 답글 원문 유실 버그 — 인용문이 아니라 본문(js-message_text) 타겟 (feat/conviction-loop)
**결정**: `scrape_channel`의 본문 셀렉터를 `tgme_widget_message_text`(generic) → **`js-message_text`(실제 본문)** 로 교정. **답글 메시지**는 인용문 div(`js-message_reply_text`)도 `tgme_widget_message_text` 클래스를 가져, `find`가 문서순 **첫 매칭=인용문**을 잡아 본문 대신 **잘린 인용문("…")** 을 저장하던 버그. 기존 오손 문서는 `scripts/backfill_telegram_truncated.py`(개별 임베드 `?embed=1`에서 `fetch_message_body`로 전문 재수집 → markdown·title 갱신 + `reenrich_document`로 entity_links 재생성)로 백필. 안전장치: '…로 끝 + <500자'(단일 답글 인용문 시그니처)만 대상, 새 본문이 더 짧으면 skip(멀티메시지 버스트 오손 방지), dry-run 기본.
**맥락·이유**: 사용자 신고 "텔레그램 원문 전체가 안 되는 경우 꽤 있음, 예 doc/7408". 진단: 7408(=t.me/chunjonghyun/7624)은 **답글**이고 저장된 260자 "…"는 답글이 인용한 원 메시지의 잘린 프리뷰였음(실제 본문은 "공감하는 관점…" 355자). 텔레그램 위젯이 인용문을 truncate("…")하는데 구 셀렉터가 그걸 본문으로 오인. dry-run 실측(최근 52 후보): 21건 전문 복구(#7408 260→355·#5406 263→**1694** 메리츠 리포트·#4680 257→1394·#1266 257→1202…), 31건 정상 skip, 0 실패. **데이터 정합성**: 잘린 본문은 enrich·entity_links·내러티브·검색까지 오염시키므로 백필 시 재enrich 필수.
**기각한 대안**: ① 스크래퍼만 고치고 기존 방치 — 264개 "…" 포함 문서가 이미 오염(엔티티·검색), 백필로 교정. ② generic 셀렉터 유지 + reply div만 사후 제외 — `js-message_text` 직접 타겟이 명확·견고. ③ 버스트까지 완벽 재구성 백필 — head 임베드만으론 continuation id 미보유, '…+짧음' 필터로 단일 답글에 한정하고 새 본문이 짧으면 skip(데이터 손실 방지), dry-run 검토 게이트. ④ 인용문(reply 컨텍스트)도 함께 저장 — 잘려서 신뢰 낮고 본문이 핵심, 범위 밖.
**참조**: backend/services/telegram_service.py(scrape_channel js-message_text·fetch_message_body) · scripts/backfill_telegram_truncated.py · pipeline/store.py(reenrich_document 재사용) · [[D-024]](수집 체인) · 대화 2026-08-02
**후속**: 답글 인용문이 짧아 "…" 없이 저장된 케이스는 이 필터가 못 잡음 — 필요 시 reply 여부 재판정 백필 별도.

## D-102 · 2026-07-31 · 매크로·유동성 해석 = 신호등 산문(sonnet) — 서술 넘어 포지셔닝 가이드 (feat/conviction-loop)
**결정**: D-101의 결정적 해석 코멘트를 **LLM 산문 신호등으로 격상**. `_refresh_signal`(스냅샷/버튼 때 sonnet 1콜)이 지표 + 결정적 초안(`_interpret`)을 입력받아 **신호등**(`green` 실어도 되는 배경 / `yellow` 선별·경계 / `red` 방어) + headline + comment(①왜 이 신호인지 지표 근거 ②비중·방어·헤지 등 **포지셔닝 함의** ③가장 주시할 지표와 전환 트리거) 생성. `macro_signals` 테이블(as_of PK, signature 불변이면 재사용, 버튼 주도 D-100 — GET은 순수 읽기). 엔진 미가용이면 결정적 `_interpret` 폴백(FE도 폴백 렌더). 결정적 프레임은 폐기 아니라 **LLM 입력+폴백**으로 유지.
**맥락·이유**: 사용자 — "산문 해석으로 격상. 단순 해석을 넘어 투자자에게 **신호등 역할**을 해줄 해설이어야." → 서술("순유동성 위축")을 넘어 "그래서 어떻게"(실어도 되나·방어인가·뭘 주시)까지. 실측(2026-07-31): yellow · "유동성 실탄은 줄고 위험선호는 식는 중 — 선별 대응" · 순유동성 위축을 가장 무겁게 읽고 완화적 금리·달러와의 엇갈림·BTC/WTI↓+금↑의 위험선호 냉각을 종합 → "베타 축소·우량 선별·레버리지 축소·되돌림 매수" + 트리거(순유동성 방향→red/green). 비용: 스냅샷(버튼) 때만·signature 캐시라 하루 1콜 수준(cost-conscious).
**기각한 대안**: ① 결정적 프레임 유지(D-101) — 사용자가 산문·신호등 명시 요구, 규칙은 "그래서 어떻게"를 못 줌. 단 폴백·LLM 입력으로 존속. ② GET(로드) 때 lazy 생성 — 로드가 sonnet ~2분 멈춤(D-100 위반), 스냅샷 write 경로에서만 생성. ③ opus — 신호등 판단엔 sonnet로 충분·비용. ④ 신호등을 결정적 점수로만(색만) — 색은 결정적으로도 되나 "포지셔닝 함의·트리거" 서술이 신호등의 핵심 가치라 LLM. ⑤ market_regime 포스처에 흡수 — 국면=오늘 매매 온도(감성 오실레이터), 매크로·유동성=배경 실탄(유동성·금리·달러), 축이 달라 분리(D-101 계승).
**참조**: backend/pipeline/macro.py(_refresh_signal·_signal_prompt·_read_signal·get_macro with_signal)·database.py(macro_signals) · frontend components/home/MacroLiquidity.tsx(신호등 렌더+폴백)·types/index.ts(MacroSignal) · docs/specs/macro.md · SYSTEM.md §5-1 · [[D-101]](매크로·유동성) [[D-100]](버튼 주도) [[D-076]](지표 fact/해석 frame) · 대화 2026-07-31

## D-101 · 2026-07-31 · 매크로·유동성 트래킹 — 하이브리드 소스, 순유동성=MacroMicro 공식 재현 (feat/conviction-loop)
**결정**: 홈에 **매크로·유동성** 별도 카드 추가(시장 국면과 역할 분리 — 포스처 vs 배경 조건). 하이브리드 소스: **yfinance 무키**(미10Y ^TNX·달러 DXY·유가·금·신용 HYG·비트코인) + **FRED 무료키**(WALCL·TGA·RRP·M2). **순유동성 = WALCL − TGA − RRP**(읽을 때 계산, 혼합 주기 forward-fill) = 사용자가 레퍼런스한 **MacroMicro US Liquidity Index** 공식. 인프라 재사용: `market_indicators` 테이블에 `macro_*` 프리픽스(스키마 0), 시장 국면의 `_yf_history`·`_series` 재사용. `pipeline/macro.py`·`routers/spine_macro.py`(GET 순수읽기+lazy·POST snapshot). FE `MacroLiquidity`(4그룹 타일·미니 라인 스파크·버튼 주도 D-100). FRED 키 없으면 유동성만 degraded(`fred_enabled` 플래그로 FE 안내).
**맥락·이유**: 사용자 — "매크로 지표·유동성 지표도 트래킹" + 소스 하이브리드·네 그룹 전부·별도 카드 선택 + "유동성은 MacroMicro US Liquidity Index 참고". MacroMicro는 유료(WebFetch 403)라 스크래핑 불가·불안정 → **동일 공식(WALCL−TGA−RRP)을 무료 FRED 원데이터로 재현**(웹서치로 공식 확인). 진짜 유동성(순유동성)이 위험자산과 가장 잘 붙는 핵심이라 FRED 채택 불가피(yfinance는 금리·달러·신용 프록시까지만). 시장 국면 인프라가 이미 일별 스냅샷+버튼(D-076·D-100)이라 지표만 얹으면 배관 0. 실측(FRED 키 미설정): 매크로 6종 정상(값·변화율·스파크라인), 유동성 2종 degraded로 우아하게 안내.
**기각한 대안**: ① MacroMicro 직접 스크래핑 — 유료·403·ToS·불안정. 공식 재현이 무료·투명·안정. ② 유동성도 yfinance 프록시(신용스프레드)로만 — 순유동성이 유동성의 정수라 FRED 필수(사용자도 그 지수 지목). ③ 시장 국면 카드에 통합 — 포스처(오늘 얼마나 실을까) vs 배경 조건(판이 어떻게 깔렸나)은 역할이 달라 사용자도 별도 카드 선택. ④ 새 테이블 `macro_indicators` — `market_indicators` 프리픽스 재사용이 스키마 0·헬퍼 재사용. ⑤ FRED 키를 필수로 — 없어도 매크로는 돌게 degraded 설계(점진 도입). ⑥ 자동 크론 상시 — 버튼 주도(D-100) 일관, GET은 순수 읽기+첫 진입 lazy.
**참조**: backend/pipeline/macro.py·routers/spine_macro.py·main.py(등록) · frontend hooks/useMacro.ts·components/home/MacroLiquidity.tsx·HomePage.tsx·types/index.ts · docs/specs/macro.md · SYSTEM.md §env·§5-1·§5-2·§6 · [[D-076]](시장 국면 인프라) [[D-100]](버튼 주도) · 대화 2026-07-31

## D-100 · 2026-07-31 · 브리핑 = 버튼 주도(로드는 순수 읽기, 갱신은 버튼만) (feat/conviction-loop)
**결정**: 브리핑 갱신을 **버튼 주도**로 전환(D-099의 크론-우선 → 번복). **일반 로드(`force=False`)는 순수 읽기** — `read_leaders`(최신 스냅샷, 네트워크 없음)+`_read_synthesis`(저장된 종합, LLM 없음)+헤드라인 캐시 읽기(`_attach_headlines(fetch=False)`). **'지금 업데이트' 버튼(`force=True`)만** TradingView·뉴스 재수집+sonnet 재종합. 크론(compute_briefing.py)은 버튼과 동치인 선택적 CLI로 강등(필수 아님). 스냅샷 없으면 빈 상태+버튼 안내. 시장 국면은 이미 스냅샷+`POST /snapshot` 버튼 구조라 그대로.
**맥락·이유**: 사용자 — "그냥 cron 보단 업데이트 버튼 달아주고 그거 누르면 업데이트가 낫겠다." → 크론 셋업 부담 없이 버튼으로 통제. 핵심은 **로드가 절대 무거운 갱신을 트리거하지 않게** 하는 것: D-099의 24h 캐시+lazy는 24h 경과 후 첫 로드가 2분 멈추는 깜짝 상황이 남아 있었음 → 로드를 순수 읽기로 만들어 제거. 값은 버튼 누를 때만 바뀌므로 '전날 결산' 프레임이 예측 가능하게 고정, FreshnessStamp가 마지막 갱신 시각 노출.
**기각한 대안**: ① 크론 유지 + lazy 폴백(D-099) — 24h 경과 로드가 silent 2분 재종합, 사용자 "버튼 누르면 업데이트" 취지와 불일치. ② 로드 시 스켈레톤만 자동, 종합은 버튼 — 새 무버+옛 종합 텍스트 불일치(혼란). 순수 읽기가 일관. ③ 첫 로드 1회 lazy 생성 — 그 1회가 2분, 빈 상태+버튼 안내가 더 정직·예측가능. ④ 버튼을 비동기 잡+알림 — 타임아웃 무제한(axios)이라 동기 mutation+스핀으로 충분(재료 불변이면 즉답).
**참조**: backend/pipeline/us_movers.py(read_leaders)·us_briefing.py(build_briefing force 분기·_read_synthesis·_attach_headlines fetch 플래그) · frontend components/home/UsBriefingSection.tsx(빈 상태 버튼) · scripts/compute_briefing.py(선택 CLI) · docs/specs/us-briefing.md · [[D-099]](하루1회+버튼 — 번복) · 대화 2026-07-31

## D-099 · 2026-07-31 · 브리핑·시장 국면 = 하루 1회(아침 8시) + 수동 갱신 버튼 (feat/conviction-loop)
→ 크론-우선 부분은 D-100에서 번복(버튼-우선·로드 순수읽기). 버튼·시장 국면 구조는 유효.
**결정**: 어젯밤 미국장 브리핑과 시장 국면을 **24시간 1회 갱신**으로 고정 + **'지금 업데이트' 수동 버튼**. 브리핑: 무버 TTL 1h→24h·뉴스 6h→24h(장중 자동 재조회 제거), 크론 시각 06:10→**08:00**, 버튼=`GET /us/briefing?force=true`(재수집+재종합). 시장 국면: 이미 스냅샷 기반이라 그대로 두고 크론 16:20→**08:00**, 버튼=`POST /market-regime/snapshot` 후 invalidate. 공용 `shared/RefreshButton`(스핀·비활성), 훅이 `refresh()`·`refreshing` 노출, FE staleTime→long.
**맥락·이유**: 사용자 — "매일 아침 전날 미국장 상황 업데이트니까 24시간에 한번만, 아침 8시쯤. 수동 버튼 달아줘. 시장 국면도 마찬가지." → 아침 브리핑 용도엔 장중 실시간성이 불필요하고, 오히려 하루 안에서 값이 바뀌면 '전날 결산'이라는 프레임이 흔들림. 24h 캐시로 하루 고정 + 마감 후 크론 pre-warm + 필요 시 수동 버튼이 제품 의도에 정합. 비용도 절감(sonnet 하루 1회 상한). 시장 국면은 이미 `POST /snapshot`(수동/EOD) 구조라 버튼만 연결.
**기각한 대안**: ① 기존 층상 캐시(무버 1h·뉴스 6h·FE 5분) 유지 — 장중 값 변동으로 '전날 결산' 프레임 흔들림·재종합 비용, 사용자 요구와 불일치. ② 시장 국면 스냅샷을 16:20 KR EOD 유지 — 사용자가 아침 8시 통일 원함(8시엔 US 밤 세션 반영·KR은 전일 종가로 프리마켓 읽기). ③ 버튼 없이 크론만 — 사용자가 즉시 갱신 수단 명시 요구. ④ 버튼을 백그라운드 잡으로(비동기 완료 알림) — 지금은 동기 mutation+스피너로 충분(재종합 ~2분은 스핀으로 안내, 재료 불변이면 즉답).
**참조**: backend/pipeline/us_movers.py(TTL 86400)·us_news.py(24h) · scripts/compute_briefing.py·snapshot_market.py(크론 08:00) · frontend hooks/useUsBriefing.ts·useMarketRegime.ts(refresh mutation)·components/shared/RefreshButton.tsx·home/UsBriefingSection.tsx·MarketRegime.tsx · docs/specs/us-briefing.md·market-regime.md · [[D-098]][[D-095]][[D-076]](시장 국면) · 대화 2026-07-31

## D-098 · 2026-07-31 · 브리핑 마무리 — ADR 비파괴 크로스레퍼런스 + 일별 사전생성 크론 (feat/conviction-loop)
**결정**: 두 후속. **① ADR→본체 크로스레퍼런스(하드 병합 대신)**: US ADR 무버가 별도 US 엔티티로 해소돼(SKHY=4434, 언급 22건) 본체(SK하이닉스=1643, 언급 1349건·내러티브)의 풍부한 국내 담론을 못 받던 문제를, `_ADR_HOME={"SKHY":"SK하이닉스"}` 이름맵으로 **enrich 시점에 두 엔티티를 union 조회**(비파괴). `merge_entities` 하드 병합은 안 씀. **② 일별 사전생성 크론**: `scripts/compute_briefing.py`(run_job 게이트)로 미국장 마감 후 1회 `build_briefing(force=True)` → 캐시 데움 → 홈 첫 로딩 즉답. 30분 체인엔 미포함(장중 signature 변동으로 sonnet 매시간=비용). 권장 crontab `10 6 * * 2-6`(KST, 마감 05:00+수집 여유).
**맥락·이유**: ①**하드 병합 기각 이유**: (a) D-050이 엔티티 병합을 **사람 승인 게이트**(agent_proposals vocab_merge)로 규정 — 인라인 자동 병합은 governance 우회. (b) 병합 시 `resolve_us("SKHY")`가 엔티티 소멸로 깨져 오히려 uncovered(aliases 오버로드·resolve_us alias 지원 등 연쇄 변경 필요). (c) ADR은 자체 us_prices·ticker 정체성 보유 — 증권은 다르고 회사만 같음. → 비파괴 read-time union이 안전·되돌리기 쉬움·거래대금 정체성 보존. 실측: SKHY coverage uncovered→covered, 언급 0→304, narrative=**"한국 반도체는 왜 AI 레버리지 베팅의 담보물이 되었나?"**(레오폴드 서사) 연결 — 병합 없이 ADR을 국내 담론에 이음. ②lazy(D-095)는 첫 로딩이 sonnet ~2분 대기라 마감 후 pre-warm이 UX 큼. signature 캐시라 재료 불변이면 재호출 0, 하루 1회가 맞는 케이던스(cost-conscious).
**기각한 대안**: ①-a `merge_entities(1643, 4434)` 실행 — 위 (a)(b)(c)로 기각, 필요하면 D-050 승인 큐로. ①-b 엔티티_id 하드코딩 xref 테이블 — DB마다 id 달라 이름맵 런타임 해소가 이식성. ①-c 전 종목 자동 KR twin 탐지(임베딩) — vocab 계보의 일이라 별건, 지금은 명시적 소수 ADR 맵으로 충분. ②-a 30분 체인 편입 — 장중 sonnet 반복 비용. ②-b APScheduler 인프로세스 — 프로젝트는 crontab+run_chain.sh 패턴, 정합 위해 스크립트+크론라인. ②-c 페이지 진입 자동 opus — 이미 lazy가 그 역할, 크론은 pre-warm만.
**참조**: backend/pipeline/us_briefing.py(_ADR_HOME·_home_entity_id·_enrich_coverage union) · scripts/compute_briefing.py · docs/specs/us-briefing.md · SYSTEM.md §5-2·크론 · [[D-097]](헤드라인) [[D-050]](vocab 병합 승인 게이트) [[D-092]](인식론적 비대칭) · 대화 2026-07-31

## D-097 · 2026-07-31 · 개별 종목 '왜' — yfinance 무키 헤드라인 커넥터 (feat/conviction-loop)
**결정**: 브리핑 개별 이슈 종목에 **US 원천 헤드라인**을 붙여 '왜 이 종목이 움직였나'를 채운다. 소스=**yfinance `.news`**(무키), `pipeline/us_news.py`(정규화·`us_ticker_news` 6h 캐시), 브리핑이 **flag된 종목만** 병렬 수집(ThreadPoolExecutor, 비용 바운드)해 종합에 주입. 종합 규율: 헤드라인이 촉매를 설명하면 **스터디 후보→공유 후보로 승격**, 헤드라인이 있어도 설명 못 하면 스터디 후보로 남김(지어내지 않음). `movers[].headlines` 반출(FE 개별 행 밑 '왜' 줄+원문 링크), signature에 헤드라인 url 포함.
**맥락·이유**: D-096가 시장 레벨 '왜'(레오폴드 디레버리징)를 풀었지만 **개별 종목 '왜'(SNDK +26%·BE +26%는 여전히 스터디 후보)** 는 D-092 인식론적 비대칭(US native 커버리지 부족)으로 미해결이었음. 스택에 이미 yfinance가 있어 `.news`가 종목별 당일 US 헤드라인을 무키로 제공 — 실측(2026-07-30): BE→"Mizuho Outperform 상향·목표가 48% 업사이드", MU/SNDK/SKHY→"아마존·애플 경영진 공급부족·비용급등 언급", MSFT→어닝서프라이즈 트리거. 주입 후 **study_candidates가 14→2로 축소**(INTC·GOOGL만 잔존 — 헤드라인이 자체 촉매 설명 못 해 LLM이 정직하게 남김), 나머지는 실제 촉매를 아는 공유 후보로. 담론(왜 전체)×헤드라인(왜 이 종목)이 상보적으로 브리핑을 완성.
**기각한 대안**: ① 전 종목(20개) 헤드라인 수집 — flag 안 된 종목은 '왜'가 덜 급해 flag된 것만(비용·지연 바운드, 병렬로 ~수초). ② 유료 뉴스 API(Polygon·Benzinga) — 무키 요청·스택 정합상 yfinance 우선, 품질 부족 시 후속. ③ 헤드라인 있으면 무조건 촉매 확정 — 헤드라인이 종목 촉매와 무관할 수 있어(INTC 사례) LLM이 설명력 판단해 스터디/공유 분기. ④ 동기 순차 수집 — 14종목 순차는 홈 로딩 지연, ThreadPoolExecutor 병렬. ⑤ US-KR 엔티티 병합으로 기존 언급 재활용 — 국내 소스라 개별 촉매엔 부족, US native 헤드라인이 직접적(병합은 여전히 별건 후속).
**참조**: backend/pipeline/us_news.py·us_briefing.py(_attach_headlines·_synthesis_prompt·_signature)·models/us.py(UsHeadline)·database.py(us_ticker_news) · frontend components/home/UsBriefingSection.tsx(MoverRow 헤드라인)·types/index.ts · docs/specs/us-briefing.md · SYSTEM.md §5-2 · [[D-096]](시장 담론) [[D-092]](인식론적 비대칭) [[D-095]](브리핑) · 대화 2026-07-31

## D-096 · 2026-07-31 · 브리핑에 그날 시장 담론 주입 — 개별 종목 경로로 못 잡는 시장구조 촉매 (feat/conviction-loop)
**결정**: 브리핑 종합(D-095)에 **그날 시장 담론**을 입력으로 추가 — ①지배 테마 랭킹(그날 문서의 theme/sector 상위) ②시장구조 코멘터리 문서(`{수급·매크로}`+주도섹터 링크, **최신순** top 8, 제목 중복 제거). 종합 프롬프트가 **거래대금 쏠림(무엇) × 담론(왜)을 교차**해 시장 레벨 사건을 먼저 짚고 급증의 성격(신규매수 vs 청산·디레버리징·반등)을 담론 근거로 판단. `us_briefing._gather_discourse`, 응답에 `market_themes`·`market_docs`(FE가 테마칩→/narrative·문서→/doc/:id로 교차 근거 노출). signature에 담론 doc_id 포함(담론 바뀌면 재종합).
**맥락·이유**: 사용자 지적 2026-07-31 — "어제 중요 이슈는 doc 6848·6993(레오폴드 사태=AI 레버리지 집단 청산)인데 브리핑이 이 촉매를 못 잡는다, 왜?" 진단: ①**종합 LLM이 그날 문서를 아예 안 읽음**(구조화 팩트만 입력) → 정보가 없어 "랠리"로 오판 ②진짜 촉매가 시장 레벨(수급·매크로 테마)인데 enrich는 종목 단위뿐 ③그 문서들이 US 무버가 아니라 한국/테마 엔티티(SK하이닉스 1643≠SKHY ADR 4434)에 링크돼 개별 조인으로 안 닿음. → 담론을 종합에 직접 주입해 해결. 실측(2026-07-30): 주입 후 mood가 "MS 어닝 서프라이즈 트리거 + '레오폴드 사태' 집단 청산이 직전 하락 배경 → 이번 급등은 신규매수보다 강제청산 후 실적확인발 반등(디레버리징→리레버리징)"으로 **시장구조 촉매 + 움직임의 성격까지 포착**(주입 전엔 "광범위한 랠리"). **인식론적 비대칭(D-092) 부분 해소**: US 종목 native 커버리지는 여전히 약하나(개별 '왜'는 스터디 후보로), 시장 레벨 서사는 한국 소스에도 글로벌 공통 테마(AI·수급·매크로)로 실려 있어 교차로 건짐.
**기각한 대안**: ① **문서 랭킹을 hits(렌즈 링크 수)로** — 다중테마 대형문서(코스피 시황 랩·삼성 대형실적)가 저브레드스 샤프 서사(레오폴드=AI+수급 2링크)를 덮어 실측 실패 → **최신순**(장 마감 정리 포스트가 상단)으로 교체, 레오폴드 포착 확인. ② 개별 종목 enrich만 강화(더 많은 언급 조인) — 시장구조 사건은 종목에 안 걸려 원천적으로 못 잡음. ③ SK하이닉스↔SKHY ADR 등 US-KR 엔티티 병합으로 개별 경로 복원 — 유효하나 vocab 통합 계보의 별건, 담론 주입이 더 직접적. ④ 담론까지 LLM이 검색하게 — 결정적 쿼리(테마 랭킹·렌즈 문서)가 싸고 재현가능, LLM은 교차 해석만. ⑤ 브리핑을 US 원천 뉴스로만 채우려 대기 — 이미 가진 담론으로 시장 레벨은 지금 해결(소스 확충은 개별 '왜'용 후속).
**참조**: backend/pipeline/us_briefing.py(_gather_discourse·_synthesis_prompt 담론 교차·_signature)·models/us.py(UsMarketTheme·UsMarketDoc) · frontend components/home/UsBriefingSection.tsx(어제 시장 담론 섹션)·types/index.ts · docs/specs/us-briefing.md · SYSTEM.md §5-2 · [[D-095]](브리핑) [[D-092]](인식론적 비대칭) · 대화 2026-07-31

## D-095 · 2026-07-31 · 어젯밤 미국장 브리핑 — 리서치 대행에서 '분위기 파악 가속기'로 (feat/conviction-loop)
**결정**: 거래대금 상위 20(D-094)을 **아침 분위기 브리핑**으로 승격, 홈 상단 카드. **결정적 코어(LLM 0)**: TradingView 스크리너에 `sector·industry·전일 등락률` 컬럼 추가(같은 1콜) → ①섹터 클러스터·쏠림 비중 ②개별 이슈 탐지(`|등락률|≥8%`·클러스터 median 부호 역행·신규 진입) ③커버 종목 enrich(resolve_us→최근3일 언급수+걸린 내러티브, worldmodel 패턴)·미상은 스터디 후보. `us_movers`를 **일별 스냅샷**(PK trade_date,rank·최근7일)으로 바꿔 직전 대비 **신규 진입** 판정. **LLM은 종합 1콜만**(sonnet·하루1회·`us_briefings` signature 캐시): 구조화 팩트만 입력받아 분위기 산문+스터디/공유 후보, **촉매 미상은 지어내지 않고 스터디 후보로**. 엔진 미가용이면 synthesis=null(스켈레톤만). `pipeline/us_briefing.py`, `GET /api/spine/us/briefing`(/{ticker}보다 먼저), FE `UsBriefingSection`(홈 상단, 쏠림 바·개별 이슈·후보·Collapsible 상위20). 구 `UsMoversSection` 폐기.
**맥락·이유**: 펀드매니저 피드백 2026-07-30 — "리서치를 **대신**해주는 것보다 **분위기 파악**을 빠르게. 전날 미국장 자금이 어디 주목했나·어떤 내러티브고 새 흐름인가·**내가 뭘 스터디하고 뭘 공유할지** 아침에 빠르게." → 시스템 무게중심을 '답 생산'(리포트·시나리오·렌즈)에서 **'조준(sensemaking)'** 으로 이동. 핵심 재구성: **커버 못 하는 종목의 촉매를 억지로 만들지 않는다 — "거래대금·등락 이례적·촉매 미상 → 스터디 후보"가 실패가 아니라 요구된 기능**(조준이 결과물). 거래대금=주목의 raw 신호를 두 층(쏠림/개별)으로 읽는 게 그 조준. 실측(2026-07-30): 전자·반도체 58.5% 쏠림 헤드라인, 메모리 3인방(MU+18%·SNDK+26%·SKHY+17.5%) 동반 급등 포착, SNDK·BE·INTC 커버X=스터디 후보, META만 기존 'AI CAPEX' 내러티브로 공유 후보 — sonnet 종합이 미상을 정직히 미상으로 남김.
**기각한 대안**: ① **전부 LLM에 넘겨 클러스터링까지 생성** — sector 필드로 결정적 분류가 공짜·재현가능·검증가능(payload vs 해석 분리, signals 계보). LLM은 산문 종합만. ② **커버 안 된 종목의 '왜'를 당장 US 원천으로 채움** — D-092 인식론적 비대칭(언급 소스 한국 편중) 미해소 상태라 억지 채움은 환각 위험. 스터디 후보 프레이밍으로 정직하게 우회, US 원천 커넥터는 후속 트랙. ③ 페이지 진입마다 opus 종합 — 하루 1회 sonnet·signature 캐시로 비용 게이트(cost-conscious, [[cost-conscious-design]]). ④ 거래대금 카드 유지+별도 브리핑 카드 — 두 카드 중복, 브리핑에 상위20 Collapsible로 흡수. ⑤ ETF 포함 쏠림 신호(SOXL/SOXX 동반 급등) — 강한 방증이나 Phase 1 스코프 밖, fast-follow.
**참조**: backend/pipeline/us_briefing.py·us_movers.py(일별 스냅샷·sector/change)·models/us.py(UsBriefing·UsCluster·UsMoverBrief)·routers/spine_us.py(/briefing)·database.py(us_movers 재정의·us_briefings) · frontend hooks/useUsBriefing.ts·components/home/UsBriefingSection.tsx·HomePage.tsx(상단 승격)·types/index.ts · docs/specs/us-briefing.md · SYSTEM.md §5-2·§6 · [[D-094]](거래대금 원천) [[D-092]](US 여론·인식론적 비대칭) [[D-091]](US 도시에) · 펀드매니저 피드백 2026-07-30

## D-094 · 2026-07-31 · 홈 미국 거래대금 상위 20 — 전체시장 스크리닝(팔로우 원칙 예외) + 무키 TradingView 소스 (feat/conviction-loop)
**결정**: 홈 신호 대시보드에 **전일 미국시장 거래대금(=종가×거래량) 상위 20** 카드를 추가. 소스는 **TradingView 스크리너(`scanner.tradingview.com/america/scan`, API 키 불필요)** — `Value.Traded` desc, **전 거래소 통합(NYSE·Nasdaq·AMEX·CBOE…)·ADR 포함(type='dr')·ETF 제외(type='fund')**. `pipeline/us_movers.py`(fetch+스키마검증+status 컨트랙트) · `us_movers` 테이블(rank PK 전량교체) · `cache_meta` TTL 1h · `GET /api/spine/us/movers`. **에러를 프론트가 인지하도록 3-상태 계약**: `ok`(신선) / `stale`(갱신 실패 → 마지막 성공 스냅샷 + 경고 배너) / `error`(데이터 없음 → ErrorState). 비공식 응답 스키마가 깨지면 `MoversSchemaError`로 감지하고 마지막 성공분을 stale로 서빙.
**맥락·이유**: 사용자 2026-07-31 — "전일 미국시장 거래대금 상위 20을 홈에 리스트업(주목 주제/종목처럼), 키 없는 소스로, 스키마 변경 등 에러를 프론트가 알 수 있게". ① **팔로우 티커만**(us_data.py, D-091) 원칙은 전체 시장 랭킹과 배치 — 이건 커버리지 도시에가 아니라 **시장 델타 진입점**이라 홈=delta 층위(SYSTEM §L1)에 부합하는 의도적 예외. ② 무키 소스 비교(Polygon=합법·키 필요 vs yfinance=유니버스 수천콜 vs TradingView=무키·서버측 거래대금 정렬·1콜)에서 사용자의 '일단 키 없이' 요청에 맞춰 TradingView. ③ 비공식 엔드포인트라 **조용한 실패가 최악** → status 계약으로 스키마 붕괴를 화면에 노출(경고 배너 유지+마지막 데이터). 실측: 20종목(MU $55B…AMAT), ETF 8종(SPY·QQQ·SOXX…) 제외, ADR 2종(SKHY·TSM) 태깅, 캐시 히트·라우트 200 확인.
**기각한 대안**: ① **Polygon Grouped Daily**(하루 전종목 1콜·합법) — 키 필요, 사용자 '무키 먼저'라 후속 트랙으로. ② **yfinance + nasdaqtrader 유니버스** — 무키지만 수천 심볼 개별 조회로 무겁고 느림, 홈 위젯 부적합. ③ ETF 포함(전 종목) — 사용자 "종목", QQQ·SOXX 슬롯 낭비라 type=fund 제외(ADR은 종목이라 유지). ④ 나스닥 전용 필터 — 사용자 "미국 시장"이라 전 거래소 통합. ⑤ 실패 시 조용히 빈 리스트 — 정직한 보고 원칙 위반, stale/error 계약으로 대체. ⑥ cron 사전적재 — 홈 진입 lazy fetch+1h 캐시로 충분(get_fundamentals 패턴), 스케줄 의존 최소.
**참조**: backend/pipeline/us_movers.py·models/us.py(UsMoverItem·UsMoversResponse)·routers/spine_us.py(/movers, /{ticker}보다 먼저)·database.py(us_movers) · frontend hooks/useUsMovers.ts·components/home/UsMoversSection.tsx·HomePage.tsx·types/index.ts · docs/specs/us-movers.md · SYSTEM.md §5-2·§6 · [[D-091]](US 도시에 — 팔로우 티커만) [[D-092]](US 디렉토리) · 대화 2026-07-31

## D-093 · 2026-07-30 · 질문 종합 — 현재 결산 리포트 → 파급 시나리오 체인 (feat/conviction-loop)
**결정**: 질문 트래커에 **질문 종합**을 추가. 분할정복(서브질문·2층 판정·프록시 관측·`narrative_grounding` 딛고 선 지식)을 **sonnet으로 '현재 결산 리포트'**(지금 답할 수 있는 것, 미판정은 미판정)로 종합하고, **그 리포트를 `report_context`로 `scenario.build_scenario`에 주입해 파급 시나리오(opus)를 체인** 생성. 저장: `question_reports`(append-only) + 시나리오는 기존 `scenarios`(question_id). **캐시 체인**: 리포트 `inputs_hash`(판정·서브질문 verdict·프록시 최신 관측·근거 지식) 안 바뀌고 refresh 아니면 리포트 재사용 + 시나리오 유지 → **리포트가 새로 생길 때만(재료 변화·refresh·시나리오 부재) 시나리오 재생성**(비용 체인). FE: `/question/:id`에 '질문 종합 — 현재 결산' 카드(트리 아래·시나리오 위) + '종합 생성' 버튼(체인 한 방), 시나리오 카드는 그 결과를 아래에서 렌더. `pipeline/question_report.py` 신설, `run_scenario_for_event`/`build_scenario`에 `report_context` 파라미터 추가.
**맥락·이유**: 사용자 2026-07-30 — "분할정복으로 서브질문·프록시까지는 좋은데, 이 하위 질문들과 온톨로지 근거로 **지금 내놓을 수 있는 짧은 리포트**를 반환하면 좋겠다. 기록되고, /question/:id에 탭/섹션으로." + "파급 시나리오가 이미 질문에 붙어있으니(D-070) 결이 비슷 — **리포트를 뽑고 그걸 input으로 파급 시나리오도 하단에 바로**". → 시간 태세 상보: **리포트=현재 결산(근거 정박), 시나리오=그 위의 가정형 전방**. 리포트를 시나리오 출발 조건으로 체인하면 전망이 생판이 아니라 '지금 우리가 선 지점'에서 뻗는다. 실측: q2(서브6·관측48) 리포트(사용량 폭증은 사실·CAPEX가 매출 앞섬·마진 버티나 FCF 대가·밸류 선행 위험, 혼조 정직) → 시나리오가 그 결산을 출발조건으로 "가정하는 것: 갭이 상환 가능한 시간에 좁혀지는지, 아직 불확실:…"로 전개(에피스테믹 분리 유지), 160s. FE tsc 통과.
**기각한 대안**: ① 통합 리포트(D-041) opus 애널리스트팀 엔진 재사용 — 종목 앵커·무거움, 질문 앵커 **경량 결산**엔 과설계. ② 리포트·시나리오 별개(체인 안 함) — 사용자 명시 "리포트를 input으로 시나리오 바로", 체인이 전방을 현재 읽기에 정박. ③ 시나리오가 결산을 한 콜에 흡수 — **에피스테믹 분리**(결산=근거 정박·미판정 정직 / 시나리오=가정형 전방·ACH) 유지 위해 2단계 + 시나리오 프롬프트에 "미판정을 확정으로 다루지 말 것" 규율. ④ 페이지 진입 시 자동 생성 — opus 비용, 버튼 트리거(승인 게이트 정신)+캐시로 재열람 공짜. ⑤ scenarios에 report_id FK — 리포트 새로 생길 때만 시나리오 재생성하는 코드 게이트로 충분, 스키마 최소.
**참조**: backend/pipeline/question_report.py·scenario.py(build_scenario report_context)·questions.py(run_scenario_for_event)·routers/spine_questions.py(/synthesis·/synthesis/compute)·database.py(question_reports) · frontend components/knowledge/QuestionDetail.tsx(질문 종합 카드+체인) · SYSTEM.md §4-1·§5-1·§5-2·§6 · [[D-070]](질문=허브·시나리오 바인딩) [[D-067]][[D-068]](질문 트래커·2층 판정) [[D-073]](미래-확률 시간축) [[D-041]](통합 리포트 — 별개) · 대화 2026-07-30

## D-092 · 2026-07-30 · 미국 종목 디렉토리 = transcript_follow 재사용(KR 유니버스 확장 아님) + 도시에 여론 (feat/conviction-loop)
**결정**: 미국 기업 브라우징 목록(`/us` 인덱스, 팔로우 서브탭 '미국')을 **KR `유니버스`(industry_groups) 확장이 아니라 `transcript_follow` 재사용**으로 구현. transcript_follow가 이미 group_label(M7·하이퍼스케일러·AI DC·에너지·CPO·Web3·semicap…)로 큐레이션된 "미국 커버리지"이자 entity 연결·도시에 도달점이라, 새 데이터모델 0으로 US 유니버스가 성립. `GET /api/spine/us`(그룹별 + 캐시 렌즈 stance·4상한, LLM 0) → 카드 클릭 → `/us/:ticker`. + **도시에 여론 섹션** `GET /api/spine/us/{ticker}/mentions`(entity_links 경유 언급 문서, 소스 혼합) — 수집된 US-native 콘텐츠가 종목별로 surface. Phase 3(여론 소스 구독)는 이 여론/디렉토리를 소비처로 삼아 **기존 커넥터 재사용**(youtube US 채널·person US 인물)로 확충, 구독 자체는 편집 판단이라 사용자 승인 게이트.
**맥락·이유**: 사용자 2026-07-30 "기업 목록 보여주는 UI, 유니버스 활용?" — 개념(담당 커버리지)은 유니버스가 맞으나 **KR industry_groups는 기계 전체가 KR 전용**(멤버=6자리 코드·screen_beneficiaries 공동언급·RS·밸류 enrich 전부 KR)이라 US 티커 편입 시 반쪽. transcript_follow가 이미 US 유니버스 실체라 그걸 승격하는 게 재사용·정합. 실측: 15그룹 노출, NVDA 카드 value=강·trend=훼손·4상한=늦은 진입, 여론 5건(현재 blog·telegram=한국 소스 → 인식론적 비대칭 실증, Phase 3가 US-native로 채움).
**기각한 대안**: ① KR industry_groups에 US 멤버 추가 — 큐레이션 기계 KR 전용이라 오염·반쪽. ② 컨콜 좌 레일을 그대로 디렉토리로(별도 페이지 없이) — 사용자 "별도 /us 인덱스" 선택(1급 브라우징 면). ③ 여론을 /feed?q= 링크로만 — 종목별 inline surface가 "연결해서 활용"에 부합(엔티티 언급 직접). ④ US 소스 자동 대량 구독 — 편집 판단·수집 비용이라 승인 게이트(cost-conscious).
**참조**: backend/routers/spine_us.py(us_list·us_mentions)·models/us.py · frontend components/us/UsIndexPage.tsx·UsDossierPage.tsx(MentionsSection)·layout/ModeNavigation.tsx(팔로우 '미국' 서브탭) · SYSTEM.md §5-2·§6 · [[D-091]](US 도시에) [[D-075]](transcript 시드) [[D-037]](KR 유니버스 큐레이션) · 대화 2026-07-30

## D-091 · 2026-07-30 · 미국 종목 도시에 `/us/:ticker` + 투자 렌즈 US 확장 (feat/conviction-loop)
**결정**: 미국 티커에 **경량 통합 도시에**를 세우고 렌즈([[D-090]])를 US로 확장(Phase 1+2 동시). **(A) 데이터 레이어(yfinance)** — US는 DART·pykrx가 없으므로 `us_prices`(EOD OHLCV, 컬럼명 `stock_code`=티커로 stock_prices 호환 → technicals 재사용)·`us_fundamentals`(info·income·cashflow·**애널리스트 추정치** 24h 캐시) 2테이블 신설. **KR 도메인 테이블(stock_prices)에 US를 섞지 않는다**(6자리 가정 쿼리 오염 방지). `pipeline/us_data.py`(fetch_prices·get_fundamentals·resolve_us). 팔로우된 티커만(전체 시장 안 긁음). **(B) 렌즈 market 분기** — `compute_reading/peek(code, lens_type, market)`, `lens_readings.market`. US 기업은 이미 entity(transcript_follow ticker↔entity_id)라 인과·컨콜·피드는 그대로 흐름. 추세=완전(us_prices→technicals·매물대, `market_regime.get_regime().us` 게이트, RS는 **지수(SPY) 대비 3개월 초과수익**으로 대체[KR 유니버스 백분위 무의미]). **(C) 가치 렌즈 US = 완전체(partial 회피)** — yfinance 1.5.1의 `eps_revisions`(개정 방향)·`eps_trend`(90일 추이)·`earnings_estimate`(성장·목표가)·`analyst_price_targets`가 **무료로 KR consensus_estimates 시계열을 대체** → 리레이팅·EPS 개정 축까지 작동(현금의 질=cashflow Operating/FCF/CAPEX 직접). **(D) 페이지** `/us/:ticker`(spine_us — 헤더 yfinance + entity + 최근 컨콜 메타) + `LensView`(market='us') + 컨콜/언급 링크. 컨콜 상세 헤더에 '도시에 →' 진입점. technicals에 `table` 파라미터, LensPage→LensView 분리(재사용).
**맥락·이유**: 사용자 2026-07-30 브레인스토밍 축 1 — 미국 종목은 컨콜·인과로 월드모델엔 있으나 펼쳐볼 앞면이 없었다(`/analyze`=DART 한국 전용). 경량 통합(5탭 복제 금지)으로 시세·밸류·렌즈·컨콜·여론을 한 페이지에. 인식론적 비대칭([[D-036]]): US 종목에 대한 한국 여론은 시차·번역이라 US-native 1차 소스 직접이 고신호. **"가치 렌즈 US 컨센서스 시계열 부재" → 사용자 "무료 대체 소스 시도, 안 되면 partial" → 프로브 결과 yfinance가 EPS 개정·추정치·목표가 전부 무료 제공** → partial 불필요, 완전체. 실측: NVDA value=강(Fwd PER 14.8 vs +43% 성장·EPS 개정 42:1·FCF $96.7B·이익의 질 0.86 정직표기, 71s)·trend=훼손(이평 붕괴·SPY 대비 -13.4%p·매물대 $181 지지, 79s)·4상한="늦은 진입", FE tsc 통과.
**기각한 대안**: ① US를 stock_prices에 저장 — KR 6자리 가정 쿼리 오염, 별도 us_prices(컬럼 호환)로 technicals만 재사용. ② 가치 렌즈 US partial 수용 — yfinance 무료 추정치로 회피 가능해 불필요. ③ 미국 재무 풀 파이프라인(DART 동형) — 과설계, yfinance 스냅샷 충분. ④ /analyze 5탭 US 복제 — 경량 통합 원칙(렌즈+컨콜+여론). ⑤ US RS를 KR식 유니버스 백분위 — US 유니버스 미보유·무의미, 지수 대비가 정합. ⑥ Phase 1만 먼저 — 사용자 "1+2 한 번에", 렌즈가 차별점.
**참조**: docs/specs/us-dossier.md · backend/pipeline/us_data.py·investor_lens.py(market 분기·_gather_value_us·_us_rel_strength)·technicals.py(table)·routers/spine_us.py·spine_lens.py(market)·models/us.py·database.py(us_prices·us_fundamentals) · frontend components/us/UsDossierPage.tsx·lens/LensPage.tsx(LensView)·follow/TranscriptPage.tsx · SYSTEM.md §4·§5·§6 · [[D-090]](렌즈) [[D-061]](컨콜=entity) [[D-036]](말뭉치 편향 탈출) · 브레인스토밍 2026-07-30

## D-090 · 2026-07-30 · 투자 렌즈 — 원칙 원장 기반 가치/추세 관점 (feat/conviction-loop)
**결정**: 기업/산업 분석을 넘어 "그래서 좋은 주식인가"에 답하는 **투자자 관점 렌즈**를 신설한다. 대표 두 관점 — **가치투자(성장주도 펀더멘탈)**·**추세추종**. 핵심 설계 3가지. **(A) 투자관 = 원칙 원장(vault/principles/{value,trend}.md)** — 두 관점의 정의를 코드 상수가 아니라 사람이 소유·정교화하는 마크다운으로 둔다(소유권 분할 vault 규율). 렌즈는 그 **원칙 전문을 압축 없이 통째 주입**해 종목 재료 위에서 종합 — 원칙이 정교해질수록 렌즈가 정교해진다(품질=원칙의 함수). **(B) 렌즈=프레임, 판정 아님** — 출력은 "매수/매도" 오라클이 아니라 "이 관점이라면 무엇을 보고 이 종목이 그 기준에서 어떻게 읽히는가"(hypothesis·주황, 근거 역추적). ([[D-030]] 사실=그래프/프레임=렌즈 계승) **(C) 재사용 우선** — 새 무거운 파이프라인 금지, `stock_brief.gather_inputs`·`upside_model`·`technicals`·인과엣지·현금흐름(financial_statements CF)을 재료로 얇은 sonnet 종합 1회. 게으른 생성(principles_hash+material_hash 가드, 원칙 수정 시 자동 stale→재생성), append-only 히스토리(판단 변화 추적). **가치 렌즈 v3 무게중심**: 현재 장부가 아니라 **미래 이익·현금흐름이 극대화될 것이라는 확신의 설득력**(삼양식품형), 과거 장부는 현금의 질로 검증하는 준거, 밸류 상한=거부권. **불일치 4상한**은 `knowledge_state` salience×conviction을 가치확신×추세위치(초입·소외↔성숙·과열)에 재사용. **1차 구현**: DB `lens_readings`·`pipeline/investor_lens.py`·`routers/spine_lens.py`·`/analyze/:code/lens` 탭 — **가치 렌즈(KR)만**. 추세 렌즈·매물대·4상한은 후속(스펙 구현순서 3~4).
**맥락·이유**: 사용자 2026-07-30 브레인스토밍 — 수집·인과그래프·내러티브·프록시로 재료는 쌓였으나 "그래서 좋은 주식인가"에 답하려면 투자자 관점이 필요. 취향이 아니라 원칙이어야 하므로 두 대표 관점을 세운다. 사용자 지침 두 개가 설계를 결정: ① "프롬프트를 압축하지 마라 — 투자자 판단은 타이트한 원칙을 촘촘히 쌓아 승화시키고 계속 깎는 것"(→ 원칙 원장·비압축 주입). ② 가치는 "미래 이익·현금흐름 극대화 확신의 설득력"이 핵심, 과거 회계장부만 보는 건 현시대와 안 맞음(→ 가치 v3 forward 무게중심). 실측: 삼성전자 가치 렌즈 생성 검증 — 이익의 질 1.89배·Fwd PER·인과엣지·상승분해(멀티플 vs 이익)를 인용, stance=중을 하방 비대칭 근거로 정직하게 판정(판정 오라클 아님), 93s.
**기각한 대안**: ① **렌즈 정의를 lenses.py 상수로**(브레인스토밍 초안) — 사용자 "계속 깎아나가는 원칙"과 정반대라 **번복**, vault 마크다운 원장으로. ② rubric 몇 줄로 압축 — "본질이 흐려진다"(사용자), 전문 주입. ③ 판정("매수/매도") 출력 — [[D-030]]·정직 원칙 위반, 프레임으로. ④ 리포트 애널리스트 3역 통째 재사용(opus) — 과설계·비용, 브리프 재료 위 sonnet 1콜로 충분. ⑤ 4상한 새로 발명 — knowledge_state 4상한이 같은 인식론, 재사용. ⑥ 추세·매물대 동시 구현 — US 주가 데이터 의존(추세)·신규 계산(매물대)이라 가치(KR, 데이터 완비) 먼저 수직 슬라이스. ⑦ /us/:ticker 미국 도시에 먼저 — 렌즈는 KR에 먼저 서고 US는 별도 스펙(축 1)으로 후속.
**참조**: docs/specs/investor-lens.md · vault/principles/value.md·trend.md · backend/pipeline/investor_lens.py·routers/spine_lens.py·models/lens.py·database.py(lens_readings) · frontend components/lens/LensPage.tsx·api/spine.ts · SYSTEM.md §4-1·§5-1·§5-2·§6 · PHILOSOPHY §2·§3 · [[D-030]](프레임=렌즈) [[D-045]](렌즈 주입) [[D-035]](조건부 업사이드) [[D-046]](Fwd only) [[D-047]](append-only) [[D-079]](진자 4상한) · 브레인스토밍 대화 2026-07-30

## D-089 · 2026-07-30 · 컨콜 수집 즉시 온톨로지 편입 + 상세 노드·인과 딥링크 (feat/conviction-loop)
**결정**: 두 개선. **(A) 수집 즉시 인과 추출** — 컨콜(transcript)이 수집되면 cron(D-088, 최대 30분 대기)을 안 기다리고 **그 건에 대해 즉시** enrich+doc_causal 실행. enrich는 이미 `store_document`이 인라인 수행하므로, `_store_call`이 저장 직후 `doc_causal.extract_for_doc(doc_id)`를 바로 호출(status가 new/updated일 때만). 신규 `extract_for_doc`: 단일 문서 즉시 추출(enrich 완료·본문 1,200자+·미추출 전제, 멱등 causal_extracted_at, conf 상한 0.5 — 배치와 동일 규율). 실패는 수집을 막지 않고 무시(cron 배치가 후속 치유). **(B) 상세 온톨로지 연결** — 컨콜 상세(`GET /detail/{id}`)에 **언급 노드**(entity_links)와 **이 콜에서 추출된 인과 엣지**(entity_relations.source_doc_id) 반출, FE가 노드 칩으로 렌더 → 클릭 시 `/knowledge/ontology?focus=<id>` 딥링크(전역 그래프의 그 노드로 초점, 내러티브 노드칩과 동일 패턴). "이 컨콜이 그래프의 무엇으로 편입됐나"를 즉시 보고 탐색.
**맥락·이유**: 사용자 2026-07-30 — "컨콜 수집되면 그 건에 즉시 enrich·doc_causal, 그리고 어떤 노드인지 표시·리다이렉트". 컨콜은 경영진 1차 발언이라 고신호 인과원([[D-061]])이니 즉시 그래프화가 가치. 실측: enrich는 store_document 인라인(이미 즉시), 빠진 건 doc_causal뿐 → extract_for_doc 훅으로 해소. 상세 딥링크는 방금 만든 내러티브 노드→온톨로지 딥링크(0b51c25)를 컨콜로 확장 — 사용자가 "표시 및 리다이렉트"로 명시. 실측: META 컨콜 노드 9·인과 엣지 29 반출, focus 딥링크 정상.
**기각한 대안**: (A) ① collect 루프 끝에 배치로 — "즉시"(사용자) 미충족, 건별 훅이 정합. ② 상세 열람 시 lazy 추출(youtube digest 패턴) — 수집 시점이 사용자 의도, 컨콜은 소량이라 인라인 부담 낮음(AV 25/day). 단 1문서 ~111s라 대량 수집 시 느려질 수 있으나 락+저볼륨으로 관리, 실패 무시로 수집 안 막음. ③ enrich도 재호출 — 이미 store_document 인라인이라 불필요. (B) ① 언급 노드만/인과 엣지만 — 둘 다 유용(노드=무엇에 대한 콜, 엣지=주장한 인과), 병기. ② 상세에 미니 그래프 시각화 — 과설계, 칩+딥링크로 온톨로지 본 뷰 재사용이 경제적. ③ 모든 entity_links 무제한 — 30개 상한(노이즈 방지).
**참조**: backend/pipeline/doc_causal.py(extract_for_doc)·transcript.py(_store_call 훅)·routers/spine_transcript.py(_doc_graph·_build_detail·Detail.nodes/causal_edges) · frontend components/follow/TranscriptPage.tsx(OntoChip·온톨로지 연결 섹션) · SYSTEM.md §5-1·§5-2 · [[D-088]](doc_causal cron) [[D-061]](컨콜 고신호) [[D-023]](문서→그래프) · 0b51c25(내러티브 노드 딥링크 선례) · 대화 2026-07-30

## D-088 · 2026-07-30 · 문서 레벨 인과 추출 cron 편입 — 컨콜·feed 새 문서를 자동 엣지화 (D-028 보류 번복)
**결정**: `extract_doc_causal`(문서 레벨 인과 추출)을 30분 cron 체인에 편입한다 — `ingest→redigest_youtube→**extract_doc_causal**→compute_signals→compute_narratives→…` 순(회당 `--limit 10`). 이로써 **모든 소스(텔레그램·블로그·뉴스·유튜브 feed + 컨콜 transcript)**의 새 문서가 enrich 후 **인과 엣지로 자동 추출**된다(source_doc_id·narrative_id=NULL·confidence 상한 0.5, 제2 인과 공급원=교차검증 부트스트랩). 멱등(`enrichments.causal_extracted_at` 마커 — 시도 1회, 재실행 스킵), `run_job` 게이트(관리자 플래그 on/off·job_runs 로그, D-055). 체인 앞쪽(narratives 이전) 배치 — doc-causal 엣지가 내러티브 생성 전 그래프에 있어 노드 vocab 공유·교차검증 부트스트랩. **D-028이 "체인 런타임" 우려로 보류했던 것을 번복** — 런타임은 회당 limit(10)+chain 락(겹침 방지)+멱등으로 관리, 백로그는 점진 처리(또는 수동 `--limit 200` 1회).
**맥락·이유**: 사용자 2026-07-30 — "컨콜 인과 추출을 cron에 편입" + "feed 문서가 enrich·doc_causal까지 cron에 포함되지?" 확인 요청. 실측으로 갭 확인: **doc_causal은 어떤 소스도 cron에 없었다**(수동 배치) — feed·컨콜 모두 enrich·entity link·embed까지만 자동, 인과 엣지는 compute_narratives(토픽 트리거)로 *간접* 생성될 뿐. `extract_doc_causal`은 이미 소스 무관 전체 후보(enriched·본문 1,200자+·미시도)를 처리하므로 **한 번 cron 편입으로 컨콜+feed 둘 다 해결**. 이게 D-023의 "모든 문서가 인과 그래프에 기여" 비전과 정합 — 특히 컨콜(경영진 1차 발언)은 고신호 인과원. 실측: 1문서→9엣지, 111s(sonnet), job_runs ok 기록.
**기각한 대안**: ① 컨콜만 필터해 편입 — extract_doc_causal이 소스 무관이라 별도 필터가 오히려 인위적, feed도 원하던 바(사용자 Q2). 전체가 단순·정합. ② 계속 수동 유지 — 사용자 명시 요청·D-023 비전 미달, feed 문서 인과가 내러티브 뽑힐 때까지 누락. ③ limit 크게(20~) — 1문서 111s라 20이면 ~37분>30분 사이클, 락으로 무해하나 상시 초과는 비효율 → 10(보수적, ~18분 최악). ④ 별도 cron(체인 밖) — 체인 앞 배치가 narratives 교차검증 부트스트랩에 유리(D-028 원목적), 편입이 나음. ⑤ run_job 없이 raw — 관리자 게이트·로그 없어 비용 폭주 시 못 끔, run_job이 D-055 정합.
**참조**: scripts/run_chain.sh(체인)·scripts/extract_doc_causal.py(run_job 래핑)·backend/pipeline/doc_causal.py(멱등·conf_cap 0.5) · SYSTEM.md §2·§5-3 · [[D-028]](레버 3 — cron 보류, 여기서 번복) [[D-023]](문서→인과 그래프) [[D-055]](run_job 게이트) [[D-061]](컨콜 고신호 인과원) · 대화 2026-07-30

## D-087 · 2026-07-30 · 관측→엣지 환류 — 추적 질문의 실적 확증을 인과 그래프에 (#5, feat/conviction-loop)
**결정**: 컨빅션 루프의 마지막 열린 고리를 닫는다 — 추적 질문의 관측이 그래프로 **환류**한다. 질문의 `confirm_verdict`가 **leaning_yes + divergence=aligned**(선행 여론과 확정 실적이 같은 방향 = 실데이터 확증)에 도달하면, 그 질문이 딛고 선 내러티브의 인과 엣지(narrative_edge_evidence 경유 매핑)에 **관측 확증 주석**(`obs_confirmed_at`·`obs_confirmed_qid`)을 찍는다(`_confirm_edges`, LLM 0). **핵심 판단 — confidence에 안 섞고 별개 축으로**: 관측 확증은 `confidence`(이 인과가 참이라는 확신)와 직교하는 '실데이터로 확인됐나' 신호다. ①축 분리 철학([[D-022]] salience/conviction·[[D-065]] confidence/effect) 정합, ②질문↔엣지 매핑이 내러티브 단위라 **성기다**(질문은 서사의 thesis를 넓게 테스트, 특정 엣지 아님) → blunt한 confidence 수학은 무관 엣지 과대강화 위험, 가시 주석이 정직. 멱등: 질문에 `edge_confirmed` 플래그 — 확증 상태 **진입 시 1회** 발화, 이탈 시 리셋. rollup에 편승(새 배관 없음). FE: 내러티브 인과 구조 뷰 엣지에 '관측 확증' 배지(교차검증·승격 배지 옆).
**맥락·이유**: 브레인스토밍(2026-07-29) Top-5, 에픽의 최종 고리. 조사에서 프록시 판정이 질문 트리에 갇혀 그래프로 안 흐르는 게 확인됐다 — 정박 대상 그래프가 현실 관측으로부터 학습하지 못했다. 이걸 닫으면 **정박 → 추적(#2·#4) → 콕핏(#3) → 학습(#5) → 재정박**이 완결된다: 관측이 확인한 인과는 다음 내러티브·논지 감사가 딛고 설 때 '실데이터로 뒷받침된' 엣지로 드러난다. 관측(컨콜·코퍼스)은 내러티브 텍스트와 **독립 소스**라 에코챔버가 아니라 교차모달 확증(서사가 A→B 주장, 실수치가 B 예측대로 움직임 확인) — 정당한 그라운딩. 실측: 질문 3(narrative 68, 19엣지) 매핑·주석·causal_subgraph 노출 확인(테스트 흔적은 실제 판정 unknown이라 되돌림 — 실제 confirm 도달 시만 정당 발화).
**기각한 대안**: ① **confidence 직접 강화**(+bump 캡) — 브레인스토밍 원안이나, 질문↔엣지 매핑이 성겨 내러티브 전 엣지를 뭉뚱그려 강화 → 무관 엣지 과대평가 + 확신/관측 축 혼합([[D-022]] 위반). 별개 주석이 안전·정직. ② promote_causal_edges에 제3 독립 신호로 편입 — 원리적으로 좋으나 프록시↔엣지 배관 복잡, 주석이 최소 결정적 1보(후속으로 승격 게이트 편입 여지). ③ 매 rollup 재주석 — 상태 유지 중 타임스탬프 노이즈, edge_confirmed 진입 가드로 1회. ④ 질문 앵커 엔티티로 특정 엣지만 — 질문에 앵커 저장 없음(서브질문·프록시 라벨뿐), 매핑 신뢰도 낮아 내러티브 단위가 현실적. ⑤ user/thesis/digest 질문(narrative_id=NULL)도 — 그래프 앵커 없어 매핑 불가, 내러티브발 질문만(propose_from_narratives).
**참조**: backend/pipeline/questions.py(_confirm_edges·rollup 훅)·narrative.py(causal_subgraph obs_confirmed)·database.py(entity_relations.obs_confirmed_at·qid·questions.edge_confirmed) · frontend components/explore/NarrativePage.tsx(관측 확증 배지) · SYSTEM.md §4-1·§5-1 · [[D-022]](축 분리·§G) [[D-065]](confidence/effect 분리) [[D-068]](2층 판정·divergence) [[D-023]](내러티브 인과 그래프·narrative_edge_evidence) [[D-080]][[D-082]][[D-086]](컨빅션 루프) · 브레인스토밍 대화 2026-07-29·2026-07-30

## D-086 · 2026-07-30 · 다이제스트 언섬 — '새로운 시각'을 질문 제안 큐로 (#4, feat/conviction-loop)
**결정**: 종목 다이제스트의 `insights`('새로운 시각' — 이전 요약 대비 새 이슈·시각 전환·상충)가 지금까지 텍스트로만 남고 끝나던 것(조사에서 확인된 '완전한 섬')을, **질문 트래커 제안 큐로 흘려** 컨빅션 루프(D-080·D-082)와 잇는다. `propose_from_digests(budget)`: **워치리스트 기업**의 **1W/1M** 다이제스트(1D 제외) 중 insight가 있고 아직 제안 안 한 것(insight_proposed=0)을 골라, **haiku가 서술문 insight → 추적 가능한 의문형 핵심질문**으로 변환(`_insight_to_question`, 질문거리 아니면 null) → `questions(created_by='digest', status='proposed')` 적재. **승인 시에만 추적**(D-020 — approve→decompose). **범람 가드 3겹**: ①워치리스트 게이트(관심 기업만) ②1W/1M만(매일 1D 노이즈 제외) ③`insight_proposed` 플래그로 시도 1회 dedup(성패 무관 셋) + budget 상한(비용 천장, [[D-072]]). `refresh_questions` cron(일 1회)에 편승. FE: 제안 큐·원장에 '언급' 발(發) 배지. 격리: 질문은 독립 테이블(그래프 무변경).
**맥락·이유**: 브레인스토밍(2026-07-29) Top-4 '다이제스트 언섬' + 사용자 2026-07-30 "개편과 함께 #4도". 매일 종목별로 생성되던 발견(insight)이 버려지는 게 가장 큰 낭비였다 — 이걸 능동 추적(질문)으로 전환하면 "놓친 것 포착"이 자동화되고, #2(논지 승격)·#3(컨빅션 원장)이 채운 질문층에 네 번째 공급원이 붙는다. insight→질문 변환은 서술문↔의문형 간극이 있어 haiku 1콜이 필요하나, 게이트(워치리스트·1W/1M·budget)로 비용을 천장 고정. 실측: SK하이닉스 2026-07 1M insight → "AI 메모리 신규 사이클이 절대 이익률을 산업 16년 사이클 변동성 위로 유지시킬까?" 질문 생성·제안 큐 적재, 재실행 dedup 확인. 사용자 IA 선택 '팔로우 기업 1W/1M만'.
**기각한 대안**: ① 링크만(LLM 0, '이 논점 추적' 버튼) — 자동성 없어 매일 확인 부담 미해소(사용자가 자동 게이트 선택). ② 인과 추출까지(insight→extract_doc_causal 엣지) — 기업 요약발 엣지는 노이즈·자기참조 위험(같은 코퍼스가 내러티브 엣지도 생성), conf≤0.5라도 그래프 오염 대비 이득 불명확 → 질문층으로만(관측-설계라 그래프 안 건드림). ③ 전 종목 대상 — 안 보는 기업까지 haiku 낭비, 워치리스트 게이트가 관심 정합·비용의식([[D-072]]). ④ 1D도 포함 — 매일 노이즈로 큐 범람, 1W/1M(유의미 축적)만. ⑤ 즉시 분해(제안 없이) — 매 insight sonnet 12분, 제안 큐+승인이 D-020 정합. ⑥ dedup을 질문 텍스트로만 — 변환이 매번 미세히 달라 재제안 샘 → insight_proposed 플래그(원천 dedup).
**참조**: backend/pipeline/questions.py(propose_from_digests·_insight_to_question·refresh_all 훅)·database.py(entity_digests.insight_proposed) · frontend components/knowledge/QuestionsSection.tsx('언급' 배지·제안 큐 태그) · SYSTEM.md §4-1·§5-1 · [[D-085]](다이제스트 개편) [[D-080]](논지 승격 — 자매 공급원) [[D-082]](컨빅션 원장) [[D-067]](질문 트래커·제안 큐) [[D-020]](승인 뒤로) [[D-072]](비용 가드) · 브레인스토밍 대화 2026-07-29·2026-07-30

## D-085 · 2026-07-30 · 다이제스트 캘린더 개편 — 1D/1W/1M 비롤링 + 진입 시 소급 catch-up (feat/conviction-loop)
**결정**: 종목 다이제스트를 재설계. **(A) 주기 체계** 1D(당일)·롤링7D → **1D(오늘)·1W(월~일 한 주)·1M(한 달)**, 전부 **캘린더 기준(비롤링)**. 각 주기는 자기 캘린더 구간의 raw 문서를 **직접 요약**(`_compute_bucket` 공용) — 과거 구간엔 하위 1D/1W가 없어 롤링·계층 재요약이 불가하므로. period_start: 1d=당일·1w=그 주 월요일·1m=그 달 1일. **(B) 진입 시 자동 소급 catch-up** — 오래 밀린 기업에 매일 들어가 1D·7D를 수동으로 눌러야 하던 불편 제거. 종목 진입 시 프론트가 `POST /digests/catchup`을 백그라운드 자동 호출 → `catch_up(stock)`이 **과거 완결 월은 1M, 이번 달 주는 1W, 오늘은 1D**를 소급 생성. 3개월 밀렸으면 3×1M + 이번 달 주 1W들 + 오늘 1D. **멱등**(doc_ids_hash 가드)이라 재진입은 unchanged 스킵·무비용, 세션당 종목 1회만 발화. 상한 CATCHUP_MONTHS=3(cold-start 비용 가드). cron(compute_digests)은 최신만(오늘 1D + 이번 주 1W), 과거 월은 진입 catch_up이 담당. 구 `POST /compute?period` 폐지, GET period 패턴 `1d|1w|1m`.
**맥락·이유**: 사용자 2026-07-30 — "관심 기업에 매일 들어가 1D·7D를 눌러야 해서 불편. 오래 안 본 기업은 과거를 월 단위로, 이번 달은 주 단위로 소급해달라." 롤링7D는 '기준일마다 직전 7일'이라 아카이브가 중복·모호했고 수동 트리거라 갭이 쌓였다. 캘린더 기준이면 (월~일, 달력 월) 경계가 명확하고 소급이 자연스럽다. 트리거는 사용자 선택 '진입 시 자동(백그라운드)' — 멱등 가드가 있어 첫 catch-up만 비용, 이후 무비용이라 비용의식 설계([[D-072]])와 정합. cold-start 상한 3개월은 raw 문서 커버리지가 짧아 충분. 실측: SK하이닉스 2026-07 1M 생성(문서 90건 요약) + 재실행 unchanged 확인.
**기각한 대안**: ① 롤링7D 유지 — 기준일마다 중복 아카이브·경계 모호, 사용자가 주/월 캘린더 명시. ② 1M을 1W들의 재요약(계층) — 과거 달엔 1W가 없어 불가(진입 catch_up이 월부터 채우므로), raw 직접 요약이 일관. ③ 수동 버튼 유지(주기만 추가) — "매일 눌러야 함" 불편 미해소. ④ 무제한 소급 — cold-start 비용 폭발, 3개월 상한. ⑤ 백필 cron으로 전 종목 월간 — 안 보는 종목까지 비용, 진입 게이트(사용자 관심)가 비용의식 정합. ⑥ 구 7d 행 마이그레이션 — 롤링과 캘린더는 의미가 달라 재라벨 오류, period='7d' 행은 조회 안 됨(무해 방치).
**참조**: backend/pipeline/digests.py(_compute_bucket·compute_daily/weekly/monthly·catch_up)·routers/spine_digests.py(GET 1d|1w|1m·POST /catchup)·scripts/compute_digests.py(cron=1D+1W) · frontend components/analyze/DigestSection.tsx(진입 catchup·1D/1W/1M 블록) · SYSTEM.md §2·§4-1·§5-1·§5-2·§6 · [[D-072]](비용의식·활성 게이트) [[D-021]](시간 정박) · 대화 2026-07-30

## D-084 · 2026-07-30 · 컨콜 수집 회계분기 정합 — 캘린더 게이트 폐지 + 후보창 확장 + Q&A 상세 정리
**결정**: 컨콜 수집이 **AV가 회계분기(fiscal_year+fiscal_quarter)로 라벨링**한다는 사실과 어긋나 있던 것을 바로잡는다. **(A) D-081 캘린더 게이트 폐지** — 게이트가 `_quarter_start_iso`를 캘린더 분기로 계산해, 6월 결산 MSFT의 회계 Q4(AV 라벨 `2026Q4`, 실제 Apr–Jun 발표)를 '캘린더 Q4=미래'로 오인·차단했다. AV 라벨→실제 날짜 매핑이 없는 한 캘린더 기반 게이트는 회계연도 어긋난 종목(MSFT·NVDA·AAPL·MU 등 다수)을 false-skip → 제거. **(B) `_recent_quarters` 후보창 확장** — 기존 '캘린더 현재분기-1부터'는 `2026Q4`·`차년 Q1` 같은 회계 라벨을 **영영 생성 못 해** 신규 콜을 놓쳤다 → **차년 Q1부터** 생성(당해 Q4·선행 회계연도 커버). 과생성된 빈 라벨은 네거티브 캐시(D-081)가 억제. **(C) digest 프롬프트 Q&A 상세화** — 4개 요약 섹션은 간결 유지, `### Q&A 핵심`을 신설해 애널리스트 질문·경영진 답변(수치·뉘앙스·회피 여부)을 문답별로 빠짐없이.
**맥락·이유**: 사용자 "MSFT가 밤사이 미국서 실적했는데 컨콜이 왜 안 보이나". 진단: ① **AV가 신규 콜 전문을 지연 게시** — 직접 프로브 결과 MSFT `2026Q4` 현재 빈응답(콜 후 하루+ 지나야 게시, 실시간 아님) = 1차 원인(운영). ② 후보창이 `2026Q4` 라벨을 생성 못 함 ③ D-081 게이트가 그마저 차단 = AV가 게시해도 영영 수집 안 될 구조적 버그 2개. ②③은 D-081에서 "캘린더 게이트가 증명 가능 안전"이라 한 내 판단 오류(AV=회계분기 라벨이라는 전제를 놓침)의 정정.
**기각한 대안**: ① 게이트를 회계분기 인지로 수선 — AV 라벨→날짜 매핑에 per-ticker fiscal 캘린더 필요(비쌈), 지금은 넓은 후보창+네거티브 캐시로 안전하게 대체. ② 후보창 최소 확장(당해 Q4까지만) — NVDA류 차년 라벨 누락, 차년 Q1부터가 견고. ③ Q&A도 2~4불릿 유지 — 사용자가 상세 요청(문답이 고신호).
**남은 후속**: 후보창 정밀화(yfinance 실적일→AV 회계분기 라벨 매핑으로 blind 과생성 대체) — 네거티브 캐시가 낭비를 억제해 급하지 않음. 기존 저장분 digest는 새 Q&A 프롬프트로 재생성하려면 별도 recompute 필요(신규 수집분부터 자동 적용).
**참조**: backend/pipeline/transcript.py(_recent_quarters·collect_roundrobin 게이트 제거·_DIGEST_PROMPT) · scripts/collect_transcripts.py · SYSTEM.md §5-1 · [[D-081]](일부 번복: 캘린더 게이트) · [[D-061]] · 대화 2026-07-30

## D-083 · 2026-07-30 · 전망 UX 다듬기 — 프록시 디테일 모달 + 전망 탭 순서 재배치 (feat/conviction-loop)
**결정**: 두 UX 개선. **(A) 프록시 디테일 모달** — 질문 트리(QuestionsSection)의 프록시 행이 지금은 최신 관측 1건만 좁게 보여 읽기 불편. 프록시 행을 클릭하면 **모달**로 디테일 표시: 무엇을 측정하나(extract_hint)·'예'로 볼 방향(yes_direction, up=늘어남/down=줄어듦)·지켜보는 하위 질문·**전체 관측 시계열**(값·방향·날짜·**출처 문서 링크**[컨콜=raw_doc로 `/doc/{id}`, 코퍼스=라벨]). 신규 `GET /api/spine/questions/proxy/{id}`(LLM 0, `get_proxy_detail`) 1개 + FE Dialog. 질문 화면 문맥 유지(페이지 이탈 없음). **(B) 전망 탭 순서** [질문·리포트·논지 감사] → **[논지 감사·질문·리포트]** + 기본 랜딩 /questions→**/thesis**. '내 생각(논지) 입력 → 추적(질문) → 종합(리포트)' 좌→우 흐름. 논지 감사·질문이 인접(둘 다 가설-입력 도구, D-080 승격으로 실제 연결), 리포트(종합 산출물)는 끝. D-073의 랜딩·순서 조정(전망 축·집약 개념 유지, → D-073에 포인터).
**맥락·이유**: 사용자 2026-07-30 — (A) "프록시 내용 읽기 불편, 클릭 시 디테일로". 조사에서 트리는 최신 6건만 인라인(get_tree LIMIT 6)이라 전체 이력·측정 정의·출처가 안 보였음. 모달이 질문 문맥을 안 깨면서 전체를 보여주는 최적(사용자 선택: 모달 vs 인라인 vs 페이지). 실측: 프록시 "토큰 처리량 증가율"(numeric, up) 관측 8건·MSFT 2026Q3 인용까지 정상 반환. (B) "논지 감사가 질문·리포트 뒤에 온 게 이상". 시간축(D-073)상 논지 감사도 미래-가설 도구인데 종합물(리포트) 뒤에 배치돼 어색 — 입력→추적→종합 순이 직관적(사용자 선택).
**기각한 대안**: (A) ① 인라인 펼치기 — 질문→하위→프록시로 이미 3중 중첩이라 4중은 깊음. ② 컨콜 ProxyDashboard 재사용 — 거긴 레거시 고아 프록시까지 섞이고 컨콜 스코프라 질문 프록시 디테일로 부적합. ③ get_tree에 전체 관측 인라인 — 트리 payload 비대, 모달 온디맨드가 가벼움. (B) ① 질문 랜딩 유지(순서만 재배치) — 첫 탭≠랜딩이 되어 비일관. ② 질문·논지 감사·리포트(질문 랜딩) — 입력→추적 흐름과 어긋남, 사용자가 논지 감사 우선 선택.
**참조**: backend/pipeline/questions.py(get_proxy_detail)·routers/spine_questions.py(GET /proxy/{id}) · frontend components/knowledge/QuestionsSection.tsx(ProxyRow·ProxyDetailBody·ObsRow)·components/explore/OutlookSubNav.tsx(순서)·layout/ModeNavigation.tsx(outlook 랜딩) · SYSTEM.md §5-2·§6 · [[D-073]](전망 축·랜딩 — 조정) [[D-067]](프록시·관측) [[D-080]](논지→질문 승격) · 대화 2026-07-30

## D-082 · 2026-07-29 · 컨빅션 원장 — 질문 목록을 의사결정 렌즈로 (새 표면 없이, feat/conviction-loop)
**결정**: 살아있는 가설(질문 트래커의 tracking 질문 = 콘솔 주입 + 논지 승격 D-080이 이제 한 테이블에 모임)을 **의사결정 렌즈로 재정렬한 컨빅션 원장**을 신설하되, **새 페이지·서브탭을 만들지 않고 기존 전망→질문 목록(QuestionsSection)을 강화**한다(사용자 IA 선택 2026-07-29, D-070 "생성 표면 난립 경계" 정합). 3요소: **(A) 정렬 토글** 최근(updated_at)↔**원장**(괴리[divergence=lead_ahead/confirm_ahead] 우선 → 확신[conviction] 내림차순, 클라이언트 정렬 LLM 0), 기본=원장. **(B) 요약 스트립** 괴리 N·고확신 M(conviction≥0.5)·논지발 K. **(C) 논지발 배지** — 논지 감사서 승격된 질문을 구별. 이를 위해 `POST /questions`가 `created_by`(user|thesis 화이트리스트)를 받게 하고, 승격 버튼(D-080)이 `created_by='thesis'`를 보낸다(D-080이 예고한 "역추적 #3서 필요하면 추가"의 실현). 백엔드는 이 파라미터 1개만 추가 — `list_questions`는 이미 `q.*`로 conviction·created_by를 반환하고 있었다. **홈 델타 넛지(판정 바뀐 질문 알림)는 후속**(verdict_changed_at 스키마 선결, 사용자 "원장부터" 선택).
**맥락·이유**: 브레인스토밍(2026-07-29) Top-3, "의사결정 콕핏". 조사에서 질문 목록이 최근순이라 정작 의사결정상 중요한 것(선행 vs 확정 괴리 = 조기 경보, 고확신)이 묻히는 게 확인됐다. #1(진자)·#2(승격)이 채운 데이터 위에 서는 신규 역량 — 특히 #2로 논지 주장이 질문이 되면서 "내 thesis + 능동 질문"이 한 곳에 모였고, 원장은 그걸 "확신 대비 그래프가 배신하는 곳" 순으로 세운다. IA는 D-070(표면 난립)·D-073(전망 구조)를 존중해 기존 질문 목록 강화로 — 원장은 본질적으로 같은 데이터의 재정렬·재프레임이라 새 표면이 불필요. created_by 화이트리스트는 임의값 주입 차단.
**기각한 대안**: ① 전망 하위 새 '원장' 서브탭 — 질문과 같은 데이터라 표면 중복(D-070), 토글이 경제적. ② 독립 /ledger 대시보드 — IA 분산 최대, 기각. ③ 논지발 구별을 위해 questions에 thesis_audit_id 컬럼 신설 — 역추적(어느 감사서 왔나)엔 좋으나 원장 배지엔 created_by='thesis' 한 값으로 충분, 스키마 최소. 감사↔질문 완전 역링크는 필요 시 후속. ④ 원장 정렬을 백엔드 param으로 — 규모 작아 클라이언트 정렬로 충분, API 표면 안 늘림. ⑤ 델타 넛지까지 이번에 — verdict_changed_at 스키마·rollup·홈 배선이라 별도 증분(사용자 "원장부터").
**참조**: frontend components/knowledge/QuestionsSection.tsx(LedgerBar·ledgerSort·논지 badge)·components/thesis/ThesisAuditPage.tsx(promote created_by='thesis') · backend/routers/spine_questions.py(AskRequest.created_by 화이트리스트) · SYSTEM.md §5-2·§6 · [[D-080]](논지 승격) [[D-067]](질문 트래커) [[D-068]](2층 판정·divergence) [[D-070]](표면 난립 경계) [[D-022]](conviction) · 브레인스토밍 대화 2026-07-29

## D-081 · 2026-07-29 · 컨콜 수집 예산 낭비 차단 — 빈응답 네거티브 캐시 + yfinance 캘린더 게이트 + AV 미커버 active=0
**결정**: Alpha Vantage 컨콜 수집(25/day)의 예산 낭비를 3겹으로 막는다. **(A) 빈응답 네거티브 캐시**(`transcript_probe`) — AV는 dates 엔드포인트가 없어 분기를 blind probe하는데, 빈응답(커버리지 공백·미보고)을 기억해 cooldown(45일) 동안 재요청 안 함. **(B) yfinance 발표일 캘린더 게이트**(`transcript_calendar`, `refresh_calendar`) — 무료(AV 예산 무관)로 최근/차기 실적 발표일을 캐시하고, **분기 시작일 > 최근 발표일**인 분기(=보고 이후 시작 → 아직 안 나옴)는 probe 안 함. **(C) AV 미커버 종목 active=0** — ASML·TSM(해외 발행사 ADR)은 AV에 트랜스크립트가 없어 매 회차 빈응답만 내므로 수집 대상에서 내림(팔로우 기록은 유지). + `collect_roundrobin`에 `--dry-run`(예산 없이 요청 계획만).
**맥락·이유**: 직전 수집 라운드에서 22요청 중 **15가 빈응답**(ASML·TSM 해외 미커버 + CRWV·AMD 등 AI 종목 커버리지 공백/미보고). 기존 코드는 저장분만 스킵하고 빈응답은 기억 안 해 매 회차 같은 낭비 반복. 사용자가 "캘린더/가용성을 먼저 수집하면 낫나?" 제안 → 갈라 분석: 캘린더가 고치는 건 '미보고 분기'뿐이고, 이번 낭비의 다수는 'AV가 아예 없는 종목'이라 **네거티브 캐시가 주 레버**, 캘린더는 안전 가드+메타데이터로 정리.
**기각한 대안**: ① **분기 말** 기준 캘린더 게이트 — 회계연도 어긋난 종목(AMAT·MU·NVDA 등, 실제로 직전 라운드에 AMAT 2026Q2 수집됨)의 **수집 가능 분기를 false-skip**(데이터 손실 > 예산 낭비) → **분기 시작 기준**으로 교체(증명 가능 안전: 보고 이후 시작된 분기는 AV에 있을 수 없음). ② 캘린더 소스로 AV EARNINGS 엔드포인트 — 25/day 예산을 갉아먹음 → yfinance 무료. ③ ASML·TSM 팔로우 유지(계속 빈응답) — 예산 낭비 → active=0(유료 소스 붙이면 재활성). ④ 캘린더 게이트만(네거티브 캐시 없이) — 캘린더는 미보고만 고쳐 커버리지 공백 낭비 방치.
**남은 후속**: 캘린더 게이트는 현재 **near-no-op**(`_recent_quarters`가 현재 분기를 생성 안 해 미래 분기 후보가 없음) — 현 분기 probe 도입 시 활성. ASML·TSM은 FMP 유료 등 해외 커버리지 소스 필요. 네거티브 캐시는 회차를 거치며 채워져 점진적으로 효과(첫 회차엔 여전히 1회 probe 후 기록).
**참조**: backend/pipeline/transcript.py(refresh_calendar·_quarter_start_iso·_record_empty·collect_roundrobin 게이트)·database.py(transcript_probe·transcript_calendar)·scripts/collect_transcripts.py(--dry-run) · SYSTEM.md §4-1·§5-1 · [[D-061]](컨콜 팔로우) · [[D-075]](컨콜 확대) · 대화 2026-07-29
→ **캘린더 게이트는 D-084에서 폐지**(AV가 회계분기로 라벨링해 회계연도 어긋난 종목을 false-skip). 네거티브 캐시·active=0은 유지.

## D-080 · 2026-07-29 · 논지→추적 승격 — 감사된 주장을 살아있는 질문으로 (일회성→추적, feat/conviction-loop)
**결정**: 논지 감사(D-078) 결과의 각 주장에 **"추적 시작"**을 달아, 클릭 한 번으로 기존 `decompose_question`(D-067) 파이프라인에 태워 **추적 질문으로 승격**한다. 승격된 주장은 서브질문(반증조건 보유)·프록시(numeric/sentiment)·2층 판정(lead/confirm/divergence)·반증 감시를 공짜로 얻는다 — 일회성 감사가 **앞으로 추적되는 살아있는 가설**이 된다. 구현은 **백엔드 무변경**: 프론트에서 주장 텍스트를 기존 `POST /api/spine/questions`(`{text}`, created_by='user')로 보내고 반환된 질문 id로 `/question/{id}` 허브 이동 — `SourceDeepDive`(Q5)의 검증된 픽 패턴을 그대로 미러. **격리 불변식 유지**: 질문은 독립 테이블(D-067 "결합하되 융합 안 함")이라 그래프에 노드·엣지가 안 써진다; created_by='user'가 격리 태그. 이로써 감사 스펙(docs/specs/thesis-audit.md) **stage 4의 승격 절반**(반증조건+프록시 배선→추적 질문 스폰)이 구현된다.
**맥락·이유**: 브레인스토밍(2026-07-29) Top-2, 에픽의 구조적 키스톤. 논지 감사와 질문 트래커는 둘 다 전망(Outlook) 탭·둘 다 사용자의 미래-가설을 sonnet으로 분해([[D-073]]) — 거의 같은 모양인데 승격 고리가 없어 감사가 정적 스냅샷에 머물렀다(조사에서 확인된 분절). D-078의 킬러 데모("네가 합의라 한 주장이 코퍼스는 반박")의 자연스러운 다음 행동이 "그럼 추적하자"인데, 그 기계(decompose_question)가 이미 있었다. `decompose_question`이 이미 falsifier·proxy를 생성하므로 신규 엔진 0 — thesis 전용 반증 생성기를 따로 안 만들고 질문 분해로 흡수(온톨로지 "질문=지식의 미결 버전" [[D-067]]과 정합). 승격 후보는 특히 contested/challenged/novel(그래프 불확실) + hidden_edge 진자(믿지만 시장은 모름)이나, 판단은 사용자에 맡겨 전 주장에 버튼 노출.
**기각한 대안**: ① thesis 전용 추적 테이블 신설 — 질문 트래커와 중복, 어휘·판정 로직 이중화. 질문으로 흡수가 [[D-067]] "Q5는 ②의 흡수" 선례와 정합. ② 승격 시 그래프에 주장 엣지 등재 — 자기확증 에코챔버([[D-078]] 격리 규율 위반), 질문은 관측-설계라 그래프 오염 없이 추적 가능. ③ 백엔드 승격 엔드포인트 신설(audit_id·claim_index) — 감사↔질문 역추적엔 좋으나 MVP 과설계, 기존 `POST /questions` 재사용이 단순(CLAUDE.md). 역추적(어느 감사서 왔나)은 #3 컨빅션 원장서 필요하면 추가. ④ 주장을 질문형으로 LLM 재작성 후 승격 — decompose_question의 sonnet이 이미 재해석, 불필요한 콜.
**참조**: frontend components/thesis/ThesisAuditPage.tsx(PromoteButton) · backend/pipeline/questions.py(decompose_question 재사용, 무변경)·routers/spine_questions.py(기존 POST) · docs/specs/thesis-audit.md(stage 4 승격 절반) · SYSTEM.md §5-1 · [[D-078]](논지 감사) [[D-067]](질문 트래커·흡수) [[D-073]](전망 축) · 브레인스토밍 대화 2026-07-29

## D-079 · 2026-07-29 · 논지 감사 진자(stage 3) — 선반영을 verdict가 아닌 salience×conviction 직교 축으로 (feat/conviction-loop)
**결정**: 논지 감사(D-078)에 **진자(stage 3)**를 배선한다. 핵심 판단 — **"선반영(priced-in)"은 verdict의 5번째 값이 아니라 별개의 직교 축**이다. verdict(aligned/contested/challenged/novel)는 "그래프가 이 주장에 **동의하나**"를 묻고, 진자는 "그 주장이 **이미 시장에 반영됐나(엣지 소진) vs 아직 소외됐나(기회)**"를 묻는다 — 그래프가 지지(aligned)해도 이미 선반영이면 매매 엣지가 없고, 소외면 기회다. 이 갭 자체가 알파(설계 §G, [[D-022]]). 구현 = `knowledge_state.py`(salience×conviction, LLM 0)를 **그대로 재사용**: salience=앵커 엔티티 최근 14일 언급량, conviction=정박 강도(support 엣지의 corroborated_by 독립 내러티브 수·소스 채널 다양성·앵커의 가장 느린 pace 층 가중 − contradict 반례). 4상한: `hidden_edge`(소외 기회, 주목↓확신↑) · `priced_in`(선반영, 주목↑확신↑) · `overhyped`(과열, 주목↑확신↓) · `noise`. 주장마다 `pendulum` 필드로 result_json에 저장(기존 감사엔 없어 FE에서 optional). 격리 불변식 유지(read-only, 그래프 무변경).
**맥락·이유**: 브레인스토밍(2026-07-29, brainstorm-ideas-existing)에서 "의사결정 품질" 최우선 성과로 뽑힌 Top-1. 감사가 "그래프가 동의한다"에서 멈추면 *행동가능성*(이미 늦었나/아직 기회인가)을 못 준다 — 이게 매매 판단의 실제 축. 신규 엔진 0(캘리브레이션된 knowledge_state 재사용)이라 최소 노력·최대 임팩트. 실측: AI/반도체/데이터센터 주장 → salience 1.0 × conviction 0.822 = **priced_in**("잘 확립됐고 많이 회자됨 = 남은 엣지 적음") 정확 판정. verdict와 축을 분리한 것은 온톨로지 "사실/가설·주목/확신 안 섞기"([[D-022]]) 규율의 연장.
**기각한 대안**: ① 선반영을 verdict 5번째 값으로 — 그래프 일치(인식)와 시장 반영(주목)은 다른 축인데 뭉개면 "aligned인데 선반영"을 표현 못 함(정보 손실). ② conviction을 thesis 전용 로직으로 새로 작성 — knowledge_state가 이미 같은 축을 캘리브레이션(§G), 재사용이 정합·재현. ③ pendulum을 opus로 판정 — salience/conviction은 결정적 계량이라 LLM 불필요(비용·재현성, signals·technicals 철학). ④ 기존 감사에 소급 백필 — result_json 스냅샷은 그때의 그래프 상태라 재계산은 감사 정체성 훼손, optional 필드로 신규 감사부터.
**참조**: backend/pipeline/thesis.py(pendulum_for_claim·_slowest_layer)·knowledge_state.py(재사용) · frontend components/thesis/ThesisAuditPage.tsx(PendulumRow)·types/index.ts(ThesisPendulum) · docs/specs/thesis-audit.md(stage 3) · SYSTEM.md §5-1 · [[D-078]](논지 감사) [[D-022]](salience×conviction 직교 축·§G) · 브레인스토밍 대화 2026-07-29

## D-078 · 2026-07-28 · 저장됨(Saved) — 산출물 북마크 원시타입 신설 (docs/specs/saved-items.md)
**결정**: 기업 디테일·문서·내러티브·리포트를 저장해 언제든 다시 볼 수 있는 **북마크 원시타입**을 신설한다. 앱에 "특정 산출물을 다시-찾기"하는 층이 비어 있었다(팔로우는 *엔티티 흐름 구독*, 워치리스트는 종목, 리서치노트는 메모 — 아티팩트 핀 아님). 4결정(사용자 2026-07-28): **(A) 배치** = 헤더 상시 북마크 아이콘(Sheet 빠른 열람, ApprovalsInbox 패턴 미러) + 팔로우 '저장됨' 서브탭(`/follow/saved` 전체 목록) 둘 다 + 4개 페이지에 북마크 토글. **(B) 메타** = 메모 한 줄만(MVP — 폴더·태그 없음, kind 필터 + 역순으로 충분). **(C) 버전** = 버전 있는 내러티브·리포트는 **보던 그 버전 고정**(topic이 아니라 version 행 PK를 ref로) — 재방문 시 그때 본 그대로. 이를 위해 리포트에 `?v=` URL 파라미터를 신설(ReportView `initialVersionId`), 내러티브는 기존 `/narrative/history?topic=&v=` 버전 뷰로 링크. **(D) 모델** = `saved_items(kind, ref, url, title/subtitle 스냅샷, note)` + `UNIQUE(kind, ref)`로 토글 멱등. GET 목록 하나로 헤더 배지·페이지 토글 상태·리스트 전부 서빙(별도 status 엔드포인트 없음 — ApprovalsInbox 패턴).
**맥락·이유**: 사용자 "특정 기업·문서·내러티브·리포트 url을 저장해놓고 다시 보게." 팔로우와의 중복 우려를 "팔로우=흐름 구독 / 저장됨=아티팩트 핀"으로 명확히 분리(성격 다름, 병존). 버전 고정은 리포트가 append-only 히스토리(D-047)·내러티브가 버전 보존(D-060)이라 "그때 본 그 버전"이 의미 있는 자산이기 때문 — 최신으로 흘려보내면 저장의 의도(그 판단 스냅샷)가 사라진다.
**기각한 대안**: ① URL-only 모델(kind·ref 없이 url 문자열만) — 단순하나 타입별 렌더·버전 식별·중복제거 불가, 타입 있는 ref가 앱의 typed 철학과 정합. ② 항상 최신(topic) 저장 — 재방문 편하나 버전 고정 의도(B의 스냅샷 자산) 상실, 사용자가 명시적으로 버전 고정 선택. ③ 태그·폴더 — MVP 과설계(CLAUDE.md 단순성), kind 필터로 충분. ④ 제목 재-resolve/liveness 체크 — MVP 스냅샷으로 충분, 사라진 원본은 각 페이지 자체 Empty가 처리.
**남은 후속**: 원본 삭제 감지(dead-link 배지) · 정렬/검색 · 옴니바에서 저장 · watchlist(종목)와의 관계 정리(중복 진입점 여부).
**참조**: docs/specs/saved-items.md · backend/routers/spine_saved.py·database.py(saved_items) · frontend `hooks/useSaved`·`shared/SaveButton`·`follow/SavedList`·`SavedPage`·`layout/Header`(SavedInbox)·`layout/ModeNavigation`(서브탭)·`explore/ReportView`(?v=) · SYSTEM.md §4-1·§5-2·§6 · [[D-047]](리포트 히스토리) · [[D-060]](내러티브 버전) · 대화 2026-07-28

## D-078 · 2026-07-28 · 논지 감사 — 내 thesis를 인과그래프에 대질하는 read-only 감사 (docs/specs/thesis-audit.md)
**결정**: 사용자가 자유서술 투자 thesis를 주입하면, 시스템이 그것을 **축적된 인과그래프에 대질**해 주장별 델타(일치/충돌/반박/신규)를 돌려주는 **read-only 감사** 기능 신설. **핵심 규율 — 감사지 등재가 아니다**: 사용자 주장은 `thesis_audits`에 저장될 뿐 인과그래프(온톨로지)에 안 써진다(격리). moat는 추론(다중 에이전트 토론)이 아니라 **정박** — 모든 판정이 코퍼스 근거(엣지·corroborated_by 독립 소스 수·effect_direction·created_at 시간급증·내러티브 버전)를 가리킨다. 파이프라인: `decompose_thesis`(자유서술→원자 주장+역할+**그래프 vocab 앵커**, sonnet) → `ground_claim`(앵커 해소→인과엣지·내러티브·시간 후보검색, LLM 0) → `filter_edges`(주장 관련성+입장 support/contradict, haiku) → `audit_thesis`(주장별 델타). Phase 1·2(정박+분해+필터+API+UI) 구현, Phase 3(종합 opus·진자·반증/프록시)은 후속. IA: 전망 서브탭 [질문·리포트·**논지 감사**].
**맥락·이유**: 사용자 요구(2026-07-28) — "내 고차원 thesis를 그대로 넣어 리포트/질문 퀄로 검토받을 수 있나?" + 반문 "안 그러면 ChatGPT와 다를 바 없잖아". 정직한 분석: **다중 에이전트 토론은 프런티어 LLM이 이미 하므로 moat가 아니다.** 이 시스템의 우위는 축적된·출처달린·시간찍힌·교차검증된 그래프에 **정박**시키는 것. 실측 프로브로 de-risk: 예시 thesis(AI 인프라)의 각 주장이 이미 그래프에 있었다 — `OpenAI→상장 연기`(2독립), `OpenAI→모델레이어 수익성 논쟁`(effect_direction=negative), 내러티브 `AI v8·9`, OpenAI 언급 2026-07 6배 급증("최근 본격화" 시간검증). Phase 2 실측: 6주장 전부 정박, 사용자가 '합의(consensus)'라 한 주장이 코퍼스 반대엣지로 **충돌** 판정 = "가정된 합의 vs 축적된 증거" 감사(ChatGPT는 전제를 되받아 확증할 뿐).
**기각한 대안**: ① **thesis→다중 에이전트 토론(bull/bear)** — ChatGPT 재현 가능, moat 미활용. 토론은 종합(stage 5)의 얇은 층으로 격하. ② **주장을 그래프에 자동 등재** — 자기확증 에코챔버('내 주입→시스템이 확증'), PHILOSOPHY §0 '믿는 오라클' 거부. 등재는 선택·격리(hypothesis·conf≤0.5·자기교차검증 제외·승인 게이트, scenario D-028·K3 선례). ③ **anchor를 LLM 자유생성** — 실측서 그럴듯하나 그래프에 없는 이름('GPU'·'컴퓨팅 자본') 지어내 정박 0 → enrich 패턴(vocab 주입)으로 해소. ④ **roleplay 프롬프트** — claude-code 엔진이 에이전트로 새 코드 실행 시도(권한 요청) → 명령형·"JSON만" 제약 프롬프트로 완성 모드 유지(enrich 패턴).
**참조**: docs/specs/thesis-audit.md · backend/pipeline/thesis.py · routers/spine_thesis.py · [[D-067]](질문 트래커 — 미래-확률 형제) · [[D-028]](scenario 격리 물질화) · [[D-023]](인과그래프) · [[D-073]](전망 축) · 대화 2026-07-28

## D-077 · 2026-07-28 · 섹터:내러티브 N:M 복원 — 관련도 필터를 지배 섹터 랭크로 교체 (docs/specs/sector-aggregation.md)
**결정**: 섹터 집약(D-074)의 내러티브 매핑 필터를 교체한다. 구: `관련도 = co_g / **내러티브 전체 문서수** ≥ 0.3`. 신: **지배 섹터 랭크 2겹** — ① 지배 랭크(내러티브별 그룹 공동언급 co 랭킹에서 지배도 `co_g/최대섹터 co ≥ 0.15` & 상위 `top_k=4`섹터) + ② 섹터명 홈 필터(`is_other_home` — topic이 다른 유니버스 그룹 이름이면 자기 홈 뷰로만). 카테고리 렌즈(산업/기술) 필터 유지.
**맥락·이유**: 사용자 지적(2026-07-28) — "AI 같은 내러티브는 거의 모든 섹터에 연결될 수 있는데 지금은 1:N처럼 보인다". 실측이 정확히 확인: **AI(2019문서)가 반도체 1곳에만**(관련도 0.33) 뜨고, 인터넷(공동언급 162건)·자동차(122건)에선 배제 — 관련도의 분모(내러티브 전체 문서)가 커서 **광역 내러티브일수록 어느 섹터서도 0.3 미달 → 1:N으로 눌리는 역설**. 코드 주석도 자백("relevance는 broad theme와 spillover를 못 가름"). 이는 PHILOSOPHY "섹터=소유 아닌 뷰(N:M)"·"말뭉치 편향 탈출"과 정면 충돌. 교체 후 실측: AI→반도체·자동차·인터넷(N:M), HBM→반도체(좁게 유지), 2+섹터 등장 topic 1→5개. co 절대값 지배 랭크는 '광역이라 분모가 큰' 페널티가 없어 N:M을 복원한다.
**기각한 대안**: ① **관련도 임계 하향(0.3→0.2)** — spillover(비교언급)와 broad theme를 여전히 못 가름, AI는 더 낮춰도 secondary 섹터 미달. ② **섹터측 정규화(co_g/|섹터 문서|)** — 이론상 편재 대형주 강등에 좋으나 실측서 **작은 섹터(원전·전력) 과대평가로 AI가 본진 반도체에서 밀려남**(소표본 고점유율 노이즈) + 섹터명 내러티브 상호오염(반도체 narrative가 바이오 뷰에)은 여전. 지배 랭크+홈 필터가 둘 다 해결. ③ **is_other_home 제거** — 섹터명 내러티브(바이오·반도체·방산)가 편재 대형주 공동언급으로 남의 섹터 뷰에 오르는 상호오염 발생(실측 '바이오' 내러티브가 바이오 93건<반도체 133건이라 반도체 뷰 1.0). 복원 필요.
**참조**: backend/pipeline/sector.py · docs/specs/sector-aggregation.md · [[D-074]](섹터 집약 원형) · [[D-035]](관련도 필터 — 이 축이 교체됨) · [[D-036]](말뭉치 편향 탈출) · 대화 2026-07-28

## D-076 · 2026-07-28 · 시장 국면 — 홈 리스크 포스처 층 신설 (매크로/포트폴리오 축, docs/specs/market-regime.md)
**결정**: 앱에 통째로 비어 있던 **포트폴리오 리스크 포스처(매크로 층)**를 홈에 신설한다. 태린이 아빠 유튜브 착안 — 3중 필터(**감성 오실레이터 × 그 오실레이터의 20일 EMA 추세 게이트 × 변동성**)를 하나의 **비중 포스처**(🟢 확대구간 / 🟡 보류·과열경계 / 🔴 축소)로 **결정적 결합(LLM 0)**. **20 EMA는 가격이 아니라 오실레이터 자체의 이평**(US=F&G+F&G의 EMA, KR=RSI14+RSI14의 EMA) — 오실레이터가 바닥서 반등해도 EMA 우하향이면 '보류'(반등 속임수 경계). 이 점은 사용자 정정(2026-07-28)으로 명확화 — 초안이 가격 EMA(KOSPI/S&P)로 잘못 구현했다 오실레이터 EMA로 수정. 범위 3결정(사용자 2026-07-28): **(A) 배치** = 미니 추이 차트 품은 홈 섹션(`MarketRegime.tsx`), 홈=delta 규율은 "레짐 전환 강조"로 타협(delta-aware). **(B) 범위** = 미국(F&G·VIX·S&P=글로벌 리스크 날씨) + 국장(VKOSPI/실현변동성·KOSPI 20EMA=매매 본판) 둘 다, 무게중심은 국장. **(C) 오피니언** = 결합 포스처 + 근거 한 줄, **지표=fact / 결합 규율=frame**(귀속 배지는 안 넣음). 저장: 새 `market_indicators` 일별 스냅샷 테이블(EOD 배치, 축적=해자·스파크라인 히스토리). API `GET /api/spine/market-regime`.
**맥락·이유**: "매일 아침 여는 터미널"인데 "오늘 얼마나 실어도 되나"를 말해주는 층이 없었다 — 전 기능이 bottom-up 엔티티/내러티브 축이라 매크로 리스크가 사각. 핵심 긴장 3개를 설계로 해소: ①오라클 회피 → 지표는 fact, 규율은 frame(§2 사실=그래프·프레임=렌즈), 포스처는 결정적 규칙이라 hypothesis 아님. ②홈=delta → 상시 게이지 대신 레짐 전환 강조. ③비용 → LLM 0(signals.py·technicals.py 철학, cost-conscious-design). feasibility 실측 완료: VIX/KOSPI(yfinance, KOSPI는 RSI14 입력)·F&G(CNN, 브라우저 UA로 418 우회 확인)·VKOSPI(naver 엔드포인트 생존, 폴백=KOSPI 실현변동성).
**기각한 대안**: ① 개별 지표만 나열 — 어느 증권사 앱에도 있음, 태린이 아빠의 알맹이(결합 규율)를 놓침. ② 상단 텍스트 스트립만 — 사용자가 "간단한 추이 그래프" 요구, 스트립은 차트 못 담음. ③ 디테일 페이지+홈은 전환 알림만 — 홈=delta 최엄격이나 "아침마다 포스처 본다" 요구와 충돌. ④ 포스처를 인과 그래프 엣지/지식으로 승격 — 매크로 readout이지 인과 주장 아님, 반증 규율과 무관. ⑤ 장중 실시간 — 일 단위 규율이라 EOD 충분·비용. ⑥ F&G 자체 근사 재계산 — 거짓 정밀(§3), 차단 시 숨김.
**남은 후속**: VKOSPI naver 정확한 심볼 확정(폴백 보장). CNN 비공식 API 안정성 모니터. 포스처 임계값(F&G 25/75·VIX 20/30·EMA flat ε)은 초기값, 사용 후 튜닝. EOD 배치를 ingest_prices 편승 vs 별도 cron 결정.
**참조**: docs/specs/market-regime.md · backend/routers/index_data.py(기존 yfinance 지수 패턴) · services/krx_service.py · [[D-001]](무료 데이터 스택) · SYSTEM.md(구현 시 §4·§5 갱신) · 대화 2026-07-28

## D-075 · 2026-07-27 · 유니버스 섹터 확대·정합성 정리 + 컨콜 수집 대상 확대 + 유니버스 정본 시드 git 고정
**결정**: 두 커버리지 확대를 함께 집행. **(A) 유니버스 7→11섹터** — 신규 4섹터(자동차·전장 / 로봇·자동화 / 인터넷·게임·엔터 / 화장품·소비재) 추가 + 기존 7섹터 **누락 대장주 보강·카테고리 정리**(예: 전력기기에 HD현대일렉트릭 추가 + '기타' → 변압기/전선/배전 세분, 방산에 LIG넥스원[079550], 바이오에 셀트리온 + 신약/시밀러/CDMO/진단 세분, 조선에 기자재 카테고리 신설, 반도체 이수페타시스 소재→기판·리노공업 소재→후공정·테스트 재분류). 총 119종. **(B) 유니버스 정본 시드 `scripts/seed_universe.py` 신설** — 그간 유니버스는 API/프론트로만 큐레이션돼 **DB에만 존재(git 부재, 재현 불가)**. 이 스크립트가 단일 진실원천이 되어 git으로 고정. 멱등(그룹 이름 UNIQUE INSERT OR IGNORE, 멤버 (group_id,stock_code) INSERT OR REPLACE로 category·sort_order 갱신) + **비파괴**(여기 안 적힌 UI 추가분은 삭제 안 함). stock_code는 companies 테이블로 전수 검증(존재하는 코드만 — 이름·주가 resolve 보장). **(C) 컨콜 21→35종** — `transcript.py::DEFAULT_FOLLOWS`에 14종 추가: 사용자 명시(MU·ASML·TSM, CoreWeave는 기존 포함) + AI 반도체 공급망(semicap AMAT·LRCX·KLAC, networking ANET·MRVL, server DELL·SMCI) + AI DC 물리인프라(VRT·ETN·GEV) + SW(PLTR).
**맥락·이유**: 사용자 2026-07-27 지시("유니버스 섹터 확대 및 섹터별 종목 목록 적합성 점검" + "컨콜 수집 대상 확대 — 최소 MU·ASML·TSMC·CoreWeave"). 범위는 3문항 확인(신규 섹터 4개 전부 / 기존 보강+카테고리 정리 / 컨콜 넓게). 정합성 점검서 드러난 명백한 갭(전력기기 HD현대일렉트릭 누락 + 카테고리 미설정, 방산 LIG넥스원 누락, 바이오 셀트리온 누락·섹터 대비 과소, 조선 '기자재' 설명뿐 종목 0)을 보강. 유니버스가 git에 없어 재현 불가였던 문제를 이번 확대 기회에 정본 시드로 해소(D-003 "단일 진실원천" 정신을 유니버스에도). 컨콜은 앱의 지배 서사(AI/DC/반도체/전력)와 정합하게 공급망 상·하류를 채움 — 특히 VRT·ETN·GEV는 신규 국내 전력기기 섹터의 미국 미러라 교차참조 가치.
**기각한 대안**: ① 직접 SQL INSERT만(시드 스크립트 없이) — 빠르나 재현·문서화 실패, DB-only 문제 지속. ② 기존 stale `seed_industries.py` 재활용 — 실험용 단일 '반도체 밸류체인' 그룹 + `# wrong`/`# fix` 주석 난립, 라이브 7그룹과 이름 불일치라 실행 시 중복 그룹 생성. 새 정본으로 대체(구 파일은 미삭제, 사용 안 함). ③ 컨콜 최소 4종만 — 사용자가 "넓게" 선택. ④ ASML·TSM 제외(해외 발행사) — 사용자 명시 요청으로 포함(전공정 앵커), 단 Alpha Vantage 해외 커버리지 제한 가능성은 수집 후 확인 과제로 남김.
**남은 후속**: 컨콜 25 req/day 상한 → 신규 14종은 라운드로빈 백필로 며칠 걸쳐 채워짐(즉시 아님). ASML/TSM transcript 실제 수집 가능 여부 확인. 프록시 시드(PROXY_SEED)는 이번 범위 밖 — 필요 시 메모리 가격(MU)·파운드리 가동률(TSM) 등 공급측 프록시 추가 검토. 신규 섹터·보강 종목의 sector_narratives 집약(D-074)은 문서 공동언급 축적 후 자동 반영.
**참조**: scripts/seed_universe.py(신설) · backend/pipeline/transcript.py(DEFAULT_FOLLOWS 확대) · SYSTEM.md §4-1·§5-2·§5-3 · [[D-037]](유니버스 큐레이션) · [[D-074]](섹터 집약) · [[D-061]](컨콜 팔로우) · [[D-003]](단일 진실원천) · 대화 2026-07-27

## D-074 · 2026-07-27 · 섹터 집약 — 유니버스 그룹을 커버리지 단위로 (설계 정박, docs/specs/sector-aggregation.md)
**결정**: `topic → 1:1 내러티브 → 1:1 리포트` 파편화를 **유니버스 그룹(D-037)을 섹터 커버리지 단위로 승격**해 봉합한다. 핵심 4원칙: **(A) 섹터 = 유니버스 그룹** — `sector` 엔티티(402, vocab 파편)도 잔 topic도 아니라 사람이 큐레이션한 6그룹(반도체·2차전지·바이오·방산·원전·조선)이 단위. **(B) 섹터는 소유가 아니라 집약 뷰(N:M)** — 내러티브를 한 섹터에 배정 안 함(narratives에 sector_id 컬럼 없음); `AI`는 반도체 뷰·전력 뷰에 동시 등장(멤버 종목이 어느 그룹 소속인가로 매핑, entity_links/entity_relations→industry_members join, 관련도 ≥0.3 필터). **(C) 다축 공존** — 섹터(수직·단일 도메인)와 메가 내러티브(수평·cross-sector 슈퍼사이클, D-032) 역할 분리, 매크로·event는 세계관/질문 축. **(D) 리포트 앵커 topic→그룹** — 반도체 리포트 1개가 AI·HBM·소부장 종합, Top-pick은 그룹 소속 중, 기존 report 엔진(analyst·debate·Top-pick·유니버스 크로스체크)의 gather만 그룹 스코프로. **IA**: `/follow/universe` 증강(그룹마다 내러티브 목록+섹터 리포트 링크, 본문은 월드모델로 링크 — 섹터는 팔로우×월드모델 cross-cutting 앵커). Phase 1(집약 뷰 API+유니버스 노출, LLM 0)→2(섹터 리포트)→3(편입 고리).
**맥락·이유**: 사용자 2026-07-26~27 토론. 실측이 파편화 확인(반도체=AI·HBM·소부장·CAPEX 4내러티브) + 결정적 사실(유니버스 그룹 6개가 이미 깔끔한 커버리지 단위). 지난 토론서 내가 건 3경계(①섹터 유일축 금지 ②topic→섹터 매핑 fuzzy ③메가 중복)를 **"섹터=뷰(소유 아님)"** 재프레임이 한 번에 해소 — N:M 뷰라 매핑 강제가 없고, 매크로/event는 안 담고, 메가와 축이 달라 공존. 리포트는 이미 앵커+related_narratives+유니버스 크로스체크를 하니 앵커를 그룹으로 바꾸는 자연 진화.
**기각한 대안**: ① 섹터=KSIC 대분류 18 — 안정하나 커버리지 의도 아님·미커버 자동생성 소음, 유니버스 그룹이 담당 커버리지라 정합. ② 내러티브에 sector_id로 소유 배정(N:1) — cross-sector 내러티브 정보손실(AI를 반도체에만 넣으면 전력 맥락 상실). ③ 섹터 뷰 신규 페이지 /sector/:id — 유니버스·산업맵과 중복, 기존 유니버스 증강이 경제적. ④ 메가와 섹터 통합 — 수평/수직 다른 축, 통합 시 둘 다 흐려짐.
**참조**: docs/specs/sector-aggregation.md · [[D-037]](유니버스 큐레이션) · [[D-032]](메가 내러티브) · [[D-036]](유니버스 크로스체크) · [[D-041]][[D-047]][[D-049]](리포트 엔진) · [[D-035]](관련도 필터) · SYSTEM.md(구현 시 갱신) · 대화 2026-07-27

## D-073 · 2026-07-27 · 월드모델 L2를 인식론적 시간축으로 — 전망(미래·확률) 상위 탭 신설
**결정**: 월드모델 L2 탭을 **인식론적 시간축**(과거·현재·미래)으로 재편한다. **내러티브(현재·서사) · 전망(미래·확률) · 지식(과거·검증)**. **전망 상위 탭 신설** — 서브탭 [질문·리포트](`OutlookSubNav`, 지식↔온톨로지와 동형), 기본 랜딩 `/questions`. 질문을 D-071에서 내러티브 하위에 뒀던 것을 **전망 하위로 이동**(D-071 미세 번복), 리포트도 별도 형제 탭에서 전망 하위로 편입. 내러티브는 단일 탭으로(서브탭 없음, NarrativeSubNav 폐기). 라우팅: `/question*`·`/report`→'전망(outlook)' L2 활성. 규율: **시간축은 무게중심이지 칸막이 아님** — 내러티브(현재+미래 겸), 리포트(과거+현재+미래 종합)의 겹침은 라벨로 못 박지 않고 링크로 해소.
**맥락·이유**: 사용자 2026-07-27 — 시스템을 인식론적 시간축으로 보면 지식=과거·검증, 내러티브=현재라 backward-leaning인데, **가설·시나리오·전망·투자 thesis(미래·확률)가 내러티브·리포트 곳곳에 흩어져** 파편화가 느껴진다는 진단. 질문 트래커가 그 미래-확률의 1급 객체이므로, 미래-확률(질문·리포트)을 '전망' 한 상위 탭으로 집약하면 파편화가 봉합된다. D-071에서 질문을 내러티브 하위에 둔 건 지식↔온톨로지 패턴 모방이었으나, 시간축으로 보면 미래(질문)를 현재(내러티브) 밑에 넣은 category mix라 전망으로 옮기는 게 더 정합. PHILOSOPHY §2에 "세 개의 인식론적 시간대" 원칙으로 물질화(질문→지식 승격, 전망 정박 방향 포함).
**기각한 대안**: ① 질문 내러티브 하위 유지(D-071) — 시간축과 어긋남, 미래-확률 파편화 미해소. ② 질문을 독립 L2 형제(4탭) — 질문·리포트가 같은 미래-가족인데 안 묶여 집약 효과 감소, 상위 탭 수만 늘어. ③ 시간축을 물리적 칸막이로 강제(내러티브 전망 섹션까지 이동) — 내러티브가 현재+미래 겸하는 현실과 충돌, 온톨로지·리포트 오분류. 무게중심+링크로. ④ 전면 IA 개편 — 사용자가 점진 개선 명시.
**남은 후속**(BACKLOG): 내러티브 전망 섹션·리포트 thesis·시나리오를 질문 판정에 **정박**(전망→질문 링크, 미래 활용 방향 — 데이터 축적 후) · **섹터 단위 집약**(topic→내러티브→리포트 1:1:1 파편화를 섹터 커버리지 단위로, 유니버스 접합 — 별도 설계 필요).
**참조**: frontend `components/explore/OutlookSubNav`(신설, NarrativeSubNav 대체)·QuestionsPage·ReportsPage·NarrativePage(랜딩 subnav 제거)·layout/ModeNavigation(WORLDMODEL_TABS·서브탭 판정) · docs/PHILOSOPHY.md §2(세 시간대)·SYSTEM.md §6 · [[D-071]] [[D-067]] [[D-052]] [[D-023]] · 대화 2026-07-27
→ 기본 랜딩·서브탭 순서 D-083에서 조정(랜딩 /questions→/thesis, 순서 [논지 감사·질문·리포트]; 전망 축·집약 개념은 유지)

## D-072 · 2026-07-26 · 질문 관측 비용 가드 — sentiment 예산·라운드로빈 + 활성 질문 게이트
**결정**: 일 1회 cron(`refresh_all`)이 모든 tracking 질문의 sentiment 프록시를 매일 관측하던 것(프록시당 haiku 1, **상한 없음** → 질문 누적 시 일일 비용 선형 증가)에 가드를 건다. **(A) 회당 예산 + 라운드로빈** — `extract_sentiment_proxies(budget=20)`: 회당 최대 20개, `MAX(observed_at) ASC`(가장 오래 안 본·미관측 우선)로 선별 → **일일 비용이 질문 수와 무관하게 천장 고정**(numeric의 `limit=40` 패턴을 sentiment에 이식). **(B) 활성 질문 게이트** — cron 경로는 `COALESCE(last_viewed_at, created_at) >= now-14일`인 질문만 관측. `last_viewed_at`은 질문 상세(`GET /questions/{id}`) 조회 시 갱신 → 안 보는 dormant 질문은 관측 일시정지(질문은 보존, 다시 열면 재개). 초기 분해(question_id 지정) 경로는 게이트·예산 없이 전부(사용자 행위라 즉시 채움).
**맥락·이유**: 사용자 2026-07-26 — "질문이 늘수록 관측 대상이 너무 많아지고 토큰 비용 문제." 진단: numeric은 이미 회당 40 상한 + 멱등(새 컨콜 시만)이라 bounded, rollup은 결정적(LLM 0), propose는 LLM 0 — 그러나 **sentiment만 상한 없이 매일 전 프록시** 관측이라 선형 시한폭탄(질문 10개≈40 haiku/일, 30개≈120/일, 영구). 사용자 선택: 레버 1(예산+라운드로빈)+2(활성 게이트). 예산 상한이 핵심(질문 수 무관 천장), 활성 게이트가 낭비 제거. cadence 차등(레버 3)은 라운드로빈이 사실상 흡수(오래된 것부터라 활성 프록시가 자연히 더 자주)라 보류.
**기각한 대안**: ① 상한 없이 유지 — 시한폭탄, 사용자 지적. ② updated_at을 활성 신호로 — rollup이 매일 bump해 무의미, 조회 전용 last_viewed_at 신설이 맞음. ③ 전 레버(cadence 최소간격까지) — 라운드로빈이 흡수, 추가 복잡도 불필요. ④ numeric도 활성 게이트 — 이미 상한(40)+멱등으로 bounded, extract_proxies는 시드 프록시(리포트용)도 서빙해 게이트가 침습적, 보류.
**참조**: pipeline/questions.py(extract_sentiment_proxies budget·round-robin·active-gate)·routers/spine_questions.py(detail→last_viewed_at)·database.py(questions.last_viewed_at) · SYSTEM.md §4-1·§5-1 · [[D-068]] [[D-069]] · 대화 2026-07-26

## D-071 · 2026-07-26 · 질문을 내러티브와 같은 레이어로 — 내러티브 상위 탭 + [내러티브·질문] 서브탭
**결정**: 질문(미결 트래커)을 지식 탭 안(QuestionsSection)에서 빼내 **내러티브와 같은 L2 레이어**로 올린다. 지식이 상위 탭이고 그 안에 [지식·온톨로지] 서브탭을 갖는 것(D-052)과 **동형 구조**로, **내러티브를 상위 탭**으로 삼고 그 안에 **[내러티브·질문] 서브탭**을 둔다(`NarrativeSubNav` 토글, KnowledgeSubNav 복제). 신규 라우트 `/questions`(QuestionsPage=NarrativeSubNav+QuestionsSection), 질문 상세는 기존 `/question/:id` 허브(D-070). ModeNavigation: `/question*`도 worldmodel 모드 + '내러티브' L2 탭 활성. KnowledgePage에서 QuestionsSection 제거.
**맥락·이유**: 사용자 2026-07-26 — "질문을 별도 탭으로, 내러티브와 같은 레이어에. 지식 하위에 지식·온톨로지가 있듯 내러티브·질문을 상위 탭+서브탭으로." 층위 논리: 질문(무엇을 확인해야 하나)과 내러티브(지금 무슨 이야기인가)는 둘 다 **주제/이슈 레벨의 사고 산출물**이라 같은 레이어가 맞다. 질문이 지식(검증된 느린 층) 탭에 얹혀 있던 건 "질문=지식의 미결 버전"(D-067)이라는 개념적 인접성 때문이었으나, 실사용 IA로는 내러티브와 병렬이 자연스럽다(둘 다 topic 단위, delta 성격). 상위 탭 이름은 지식 선례(parent=primary child 이름)를 따라 '내러티브' 유지.
**기각한 대안**: ① 질문을 독립 L2 탭으로(내러티브와 형제, 서브탭 묶음 없이) — 사용자가 명시적으로 "통합 상위 탭+서브탭" 요청(지식 패턴). ② 상위 탭 새 이름(예 '탐구') — 지식 선례와 불일치, 사용자가 이름 언급 안 함, 필요 시 후속. ③ 지식 탭 잔류 — 사용자 요청과 배치.
**참조**: frontend `components/explore/NarrativeSubNav`(신설)·`components/knowledge/QuestionsPage`(신설)·NarrativePage(랜딩 subnav)·KnowledgePage(QuestionsSection 제거)·QuestionDetail(back→/questions)·layout/ModeNavigation(라우팅)·App.tsx(라우트) · SYSTEM.md §6 · [[D-070]] [[D-067]] [[D-052]](지식↔온톨로지 선례) · 대화 2026-07-26

## D-070 · 2026-07-26 · 산출물 교통정리 — 질문=소스발 산출물의 허브 + Home 피드=알림 전용
**결정**: 생성 표면(내러티브·시나리오·질문·리포트…)이 늘며 "어디서 무슨 조건으로 생성된 정보를 어디서 보나"가 난립. 두 원칙으로 정리. **(A) 각 산출물은 정식 열람 화면 하나** — Home AI 피드는 "생겼다" 알림일 뿐, 클릭은 정식 화면으로 정확히 라우팅. **(B) 한 소스/질문의 산출물은 한 자리** — 질문을 허브로. 구체: **① 시나리오를 질문에 묶음** — `scenarios.question_id` 신설, Q5 시나리오는 `POST /questions/{id}/scenario`로 질문에 귀속(내러티브발은 question_id=NULL 유지). **② 질문 허브 전용 라우트** `/question/:id`(QuestionDetail) — 2층 판정 + 분할정복 트리 + 파급 시나리오 + 소스 문서를 한 화면. `get_tree`가 묶인 시나리오·소스 포함. **③ Q5 모달 단순화** — 소스→질문 도출→픽→추적 시작→허브로 이동. 시나리오 생성은 허브 페이지에서(모달 인라인 제거). **④ 시나리오 topic 라벨 교정** — Q5 시나리오가 event 문장 통째를 topic으로 써 Home 피드에서 내러티브로 오인되던 것을, 질문 텍스트 앞부분(짧은 라벨)으로. **⑤ Home 피드 scenario 라우팅** — question_id 있으면 `/question/:id`, 없으면 `/narrative?topic=`(내러티브발). 기존 SK하이퍼 시나리오는 q6에 소급 연결.
**맥락·이유**: 사용자 2026-07-26 Q5 라이브 테스트 중 — 생성한 파급 시나리오가 Home 피드에 긴 문장 제목으로 떠 "내러티브가 생긴 것 같다"고 오인, 클릭하면 빈 내러티브 페이지(열람 화면 부재). 진단: (1) 시나리오 열람 이원화(내러티브발은 상세 안, Q5발은 화면 없음) (2) topic 명명 불일치 (3) 한 소스(SK하이퍼)의 질문(지식탭)·시나리오(피드)가 흩어짐 (4) 피드 scenario 링크 깨짐. 사용자 선택: "질문=허브", "Home 피드=알림 전용". 질문을 허브로 삼으면 소스발 산출물이 한 화면에 수렴 — "한 소스의 두 렌즈(무엇을 볼지=트리 / 무슨 일이 벌어질지=시나리오)"가 실제로 한 자리.
**기각한 대안**: ① 시나리오 전용 라우트(/scenario?topic=) 신설 — 질문과 또 갈라져 난립 유지, 허브 통합이 나음. ② 시나리오를 모달 인라인으로만 — 닫으면 못 봄(원 문제). ③ Home 피드에서 Q5 시나리오 제외 — 알림 가치 상실, 라우팅만 고치면 됨. ④ 질문 async 생성(fire-and-forget)까지 이번에 — 별도 스코프(BACKLOG), 교통정리는 IA 수렴에 한정.
**남긴 후속**(BACKLOG): 질문 분해 fire-and-forget(모달 12분 대기 제거) · 한국종목 numeric 프록시=재무·컨센서스 추출기(Phase 1.5).
**참조**: docs/specs/question-proxy.md · database.py(scenarios.question_id) · pipeline/questions.py(run_scenario_for_event·get_tree) · routers/spine_questions.py(/{id}/scenario)·spine_home.py(피드 라우팅) · frontend knowledge/QuestionDetail(신설)·QuestionsSection(export·카드 링크)·doc/SourceDeepDive·home/HomePage(actLink) · SYSTEM.md §4-1·§5-2·§6 · [[D-067]] [[D-069]] [[D-057]](피드·IA) · 대화 2026-07-26

## D-069 · 2026-07-26 · 질문 트래커 Phase 2 — sentiment=코퍼스 haiku · observations 가동 · 자동도출 제안 큐 (D-067 구현)
**결정**: D-067 Phase 2 구현의 세 비자명 선택. **(A) sentiment 프록시 = 게으른 haiku 코퍼스 스캔** — 신호(theme_surge 등) 재사용 대신 프록시 주제로 하이브리드 검색(FTS+벡터)→최근 문서 발췌→haiku가 여론 방향(up/down/flat) 판정→proxy_observations(source_type='corpus', source_id=KST 날짜, 하루 1회 멱등). numeric(컨콜 추출)과 대칭. 이걸로 `lead`(선행층)이 처음 살아남. **(B) observations 테이블 가동** — numeric 프록시 관측을 `observations(entity_id·metric·value, source='proxy:transcript')`에 배치 투영(`project_numeric_observations`, transcript_id→ticker→transcript_follow.entity_id 경유, 멱등). 전제로 `transcript_follow.entity_id`를 **정확 이름 매칭**으로 백필(company_name=entities.name, type=company — Meta→MetaMask 오매칭 회피, 15/21 매핑). 스키마만 있던 observations의 최초 실사용. **(C) 자동도출 = 제안 큐** — `propose_from_narratives`가 지배 내러티브(인과엣지 수 랭킹)의 질문형 title을 status='proposed'로 적재(분해 안 함), `approve_question` 승인 시에만 sonnet 분해(비싼 노동 뒤로, D-020). FE는 지식 탭 QuestionsSection의 제안 큐 + 내러티브 상세 미러링.
**맥락·이유**: 사용자 선택(2026-07-26) — sentiment 추출 갈림길에서 "게으른 haiku 코퍼스 스캔"·"Phase 2 전부(2a~2d)". (A)는 sentiment 프록시가 분해 LLM이 만든 자유 표현이라 신호 매핑보다 코퍼스 직접 판정이 정직. (B)는 D-067 "결합하되 융합 안 함"의 접점 — 노드 신규 생성 없이 관측만 엔티티에 투영해 그래프 결합 + 잠자던 테이블 활용. 검증: AI capex 질문(id=2)에서 lead unknown→mixed(여론 신뢰 심리 하락 포착), confirm=leaning_yes 유지 → divergence=confirm_ahead("실적 강세 vs 여론 회의 시작") 조기 경보 시차 실측. observations 13행 투영, 자동도출 3건 제안 확인. stance modality는 Phase 3(person 감성 시계열 선결, BACKLOG).
**기각한 대안**: ① sentiment 신호 재사용(LLM 0) — theme_surge는 "엔티티 언급 급증"이라 "버블 우려 심리" 같은 자유 질문 매핑이 어색. ② observations 투영 없이 질문 층 완전 분리 — 수치 프록시가 엔티티·밸류와 단절, 잠자는 테이블 방치(D-067서 이미 기각). ③ ticker→entity를 LIKE 매칭 — Meta→MetaMask/Metaplanet 오매칭(실측), 정확 매칭으로. ④ 자동도출을 즉시 분해 — 매 내러티브마다 sonnet 12분 태움, 제안 큐로 승인 뒤 분해가 D-020 정합.
**참조**: docs/specs/question-proxy.md · pipeline/questions.py(extract_sentiment_proxies·propose_from_narratives·approve_question)·transcript.py(project_numeric_observations)·database.py(entity_id 백필) · routers/spine_questions.py(/propose·/approve·필터) · frontend QuestionsSection(ProposedQueue)·NarrativePage(NarrativeQuestions) · [[D-067]] [[D-068]] [[D-020]] · 대화 2026-07-26

## D-068 · 2026-07-26 · 질문 판정 — pace layer 2층(선행/확정) + event-driven Tracking (D-067 후속)
**결정**: D-067의 판정 롤업을 구체화한다. **(A) verdict를 pace layer 2층으로 분리** — 질문 하나 안에 두 속도가 공존한다(sentiment·stance=fast·매일, numeric=slow·분기). 단일 점수로 뭉치면 fast 여론이 slow 실적을 압도해 verdict가 출렁인다(온톨로지 §fact/hypothesis 안 섞기 위반). 그래서 프록시 modality를 pace layer로 갈라: `lead_verdict`(선행, sentiment·stance 롤업)·`confirm_verdict`(확정, numeric 롤업)·`divergence`(둘의 괴리, `quadrant_gap`의 질문 버전 — 시차를 뭉개지 않고 신호로). `questions.verdict` 단일 컬럼 → 3컬럼. **(B) Tracking = event-driven 편승** — "주기적 추적"을 관측 추출과 판정 롤업 둘로 갈라 본다. 관측 추출은 소스별 event-driven(numeric=컨콜/재무/컨센서스 도착, sentiment=30분 cron 편승, stance=발언 문서 enrich 후) — **고정 폴러/스케줄러 신설 금지**. 판정 롤업은 관측 갱신에 편승·재료 없으면 no-op(D-059·digests doc_ids_hash 가드 동형), 결정적 스코어는 관측마다·LLM 서술은 판정 변화 시만.
**맥락·이유**: D-067 커밋 직후 미결 4개 중 "판정 주기 트리거"를 먼저 토론(Phase 1 스키마를 가르므로). fast/slow 경계 분석에서 프록시가 pace layer가 다름이 드러남 — numeric은 분기 event, sentiment는 30분 cron 편승. 이 속도차를 verdict에서 어떻게 다루냐가 핵심: 뭉치면 오염(Q3 수급 fast-layer 경고와 동형 함정), 나누면 시차가 정보. PHILOSOPHY의 pace layer를 판정에 적용. Tracking도 event-driven이 자연스럽다(numeric은 분기마다만 바뀌니 매일 재추출 낭비, sentiment는 이미 도는 cron에 얹음) — 새 배관 없이 기존 이벤트 훅.
**기각한 대안**: ① 단일 verdict — fast 여론이 slow 실적 압도해 출렁, 시차 정보 상실. ② 2층 분리를 서브질문 단위로도 — 서브질문은 대체로 modality 동질(C=stance, E=numeric)이라 질문 레벨 2층이면 충분, 서브질문은 단일 verdict 유지. ③ 고정 cron 재판정(매일/매주) — 관측 안 바뀌어도 재계산, 낭비(D-059가 이미 기각한 패턴). ④ 고정 폴러로 관측 추출 — numeric은 분기마다만 갱신되는데 매일 폴링은 API 예산·소음 낭비.
**참조**: docs/specs/question-proxy.md(판정 롤업·판정 주기 섹션·questions 스키마) · [[D-067]] [[D-059]](재료 없으면 no-op) · SYSTEM.md §5-1 signals(quadrant_gap) · PHILOSOPHY.md(pace layer) · 대화 2026-07-26

## D-067 · 2026-07-26 · 핵심질문 ↔ 프록시 — 분할정복 질문 트래커 (Q2·Q6·프록시 고도화·Q5 수렴)
**결정**: 리포트의 핵심 질문(D-049)과 transcript 프록시(D-061) 사이의 끊긴 고리를 **분할정복 구조**로 잇는다. **(A) 질문을 1급 객체로** — `questions` 테이블 신설. 질문 = "아직 답 안 난 hypothesis, 단 프록시 기반 판정 메커니즘을 가진" 것 = knowledge(검증 명제)의 **미결 버전**. 판정되면 지식 승격(knowledge_state·falsifier·consolidation 재사용). **(B) 2단 분할정복** — 핵심질문 → `sub_questions`(논리적 분할, 각 반증조건 보유) → 프록시(관측 대상, 서브질문당 1:N). **(C) 프록시 다양식(modality)** — numeric(CapEx·ARR·OPM/FCF, 컨콜·재무·컨센서스)·sentiment(투자자 여론, signals 래핑)·stance(수장 태세, person 감성). 프록시 = 기존 관측 스트림 위의 typed adapter. `proxy_observations.transcript_id` → 범용 `source_ref(source_type, source_id)`로 열어 다소스화. **(D) 생성자 2개, 다운스트림 공유** — ① 자동 도출(Q2): `_narrative_power` 지배서사 → 질문 emit + narrative_id, **제안 큐**(승인 시 추적). ② 사용자 주입(Q6): 질문 콘솔 입력 → 자동분해 → **사용자 트리 편집** → 즉시 추적. Q5(단일 소스 딥다이브)는 ②의 source_doc_id가 단일 문서인 경우로 **흡수**. **(E) 판정 = 하이브리드** — 결정적 방향 스코어(프록시 관측 카운트·반증 꺾임 강조, LLM 0) → 서브질문 → 핵심질문 종합 + 게으른 LLM 한 줄 서술(verdict_summary, 판정 변할 때만 haiku). **(F) 그래프 결합하되 융합 안 함** — 질문 층은 독립 테이블(노드 신규 생성 없음, 어휘 파편화 D-033 회피), 단 numeric 프록시 관측을 잠자던 `observations`(entity_id·metric·value)에 투영(엔티티 노드에 붙음, **observations 첫 가동**) + 질문은 narrative_id로 내러티브(=인과 서브그래프)에 앵커. **(G) Phase 스코프**: AI capex 질문("사용량이 capex를 감당할 매출·마진으로 전환되는가?") 하나로 end-to-end 증명 후 확장(D-004).
**맥락·이유**: 사용자 2026-07-26 — "컨콜·수출입 온톨로지 편입 현황"에서 출발한 설계 문답. 실측 확인: `proxy_registry.narrative_id`가 두 시드 모두 비어(프록시가 어느 질문에 매달렸는지 시스템이 모름), 관측 7건이 쌓였으나 아무도 질문으로 재판정 안 함 — 루프가 **양 끝(질문 결합·관측 피드백)에서 끊김**. 사용자가 divide & conquer 프레임과 서브질문 층(내 1레벨 그림을 2레벨로 교정)·다양식 프록시(수장 태세·여론은 수치가 아님) 통찰을 제공. 핵심 통찰: 질문은 지식과 **쌍둥이지만 판정 메커니즘이 다르다** — 지식=수동적 말뭉치 축적, 질문=능동적 관측 설계(볼 것을 미리 지정하고 추적). 이 능동성이 Q5의 "누적 전 선제 상상 불가"(corpus 최신편향) 한계를 정면으로 뒤집는다. AI capex 예시로 검증: 현 시드 프록시 2개는 질문의 **투입·수요 절반만** 덮고 핵심인 "전환"(매출·마진)은 프록시 공백 — "프록시 고도화"의 실제 내용이 이 공백 채우기임이 드러남.
**기각한 대안**: ① 프록시를 내러티브에 직접 앵커(서브질문 층 없이) — "전환되는가" 같은 복합 조건이 뭉개짐, 사용자가 2레벨로 교정. ② 서브질문·프록시를 인과 그래프 노드/엣지로 완전 융합 — 그래프 일관성은 오르나 어휘 파편화(D-033) 위험 + 태세·여론처럼 노드 아닌 관측 수용 불가. ③ 질문 층을 그래프와 완전 분리(observations 투영 없이) — 수치 프록시가 엔티티·밸류에이션과 단절, 잠자는 observations 미활용. ④ 판정을 순 LLM 종합 — 비용·지연 + 반증우선이 흐려짐. ⑤ 판정을 순 결정적 스코어 — 미묘한 맥락(왜 미판정인가) 놓침. ⑥ 두 생성자를 별도 기능으로 — Q2·Q6이 하나의 객체·두 생성자임을 놓쳐 중복. ⑦ 사용자 주입도 제안 큐 — 이미 의도를 표현한 능동 행위에 승인 벽은 마찰, 편집으로 in-the-loop면 충분.
**참조**: docs/specs/question-proxy.md(전체 설계·데이터 모델·Phase) · SYSTEM.md §4-1(proxy_registry·proxy_observations·observations) · [[D-049]](핵심질문=지배 내러티브 도출) [[D-061]](transcript·프록시 레지스트리) [[D-048]](관찰 프록시 후속) [[D-004]](렌즈 1개 end-to-end) [[D-020]](비싼 노동 승인 뒤로) [[D-033]](어휘 파편화) [[D-065]](confidence 분리·독립성 한계) · 대화 2026-07-26

---

## D-066 · 2026-07-25 · effect_strength 5→3단계 축소 + 판정 모델 sonnet 확정 (모델 A/B 근거)
**결정**: D-065의 effect_strength 범주를 5단계(unknown/weak/moderate/strong/dominant)에서 **3단계(weak/moderate/strong) + unknown**으로 축소(`dominant` 폐기). 백필 판정 모델은 **sonnet 확정**(opus 불채택). effect_direction(positive/negative/mixed)은 견고해 그대로. 프롬프트에 "경계 애매하면 낮은 쪽"(과대평가 억제) 규율 추가.
**맥락·이유**: 백필 dry-run을 sonnet·opus로 **같은 60개 엣지 A/B** 실측 — effect_direction 일치율 **93%**(견고)인데 effect_strength는 **62%(38% 뒤집힘)**. 불일치는 거의 전부 인접 버킷(weak↔moderate↔strong↔dominant), 2단계 점프 1건뿐 = 두 프런티어 모델이 대략 크기는 동의하나 5단계 경계에서 갈린다 = **버킷 입도의 거짓 정밀**(float 거부 논리 §3를 버킷에도 적용). opus 편차가 한 방향이 아니라(위로 13·아래로 10) 체계적 우위가 아닌 과제 내재 노이즈 → 모델 티어로 해결 불가, 비싼 opus 불필요. 안정 신호는 3단계+방향. unknown은 두 모델 다 0건(무지 인정 지시 안 먹힘)이나 3단계로 거칠어져 완화.
**기각한 대안**: ① 5단계 유지 — 38% 모델 불일치를 정밀 사실로 노출, 거짓 정밀. ② opus 채택 — 노이즈 성격 동일·비용만 증가. ③ 저장은 5단계 두고 랭킹에서만 ±1버킷 동률 처리 — 표기 혼란 남음, 근본 축소가 단순.
**참조**: scripts/backfill_effect_strength.py(`--model` 플래그로 A/B) · logs/effect_backfill_plan{,_opus}.json · pipeline/narrative.py(EFFECT_STRENGTHS) · SYSTEM.md §4-1 · PHILOSOPHY.md §1 · [[D-065]]

## D-065 · 2026-07-25 · confidence 의미 분리 — 인과 강도(effect_strength)/방향을 확신에서 떼어냄 (Phase 1)
**결정**: `entity_relations.confidence`가 "인과의 강도·확실성"을 한 숫자에 겸하던 것을(PHILOSOPHY §1 원문) 분리한다. **(A) confidence = 확신만** — "이 인과 주장이 참이라는 믿음"으로 의미 한정. **(B) effect_strength 신설(범주형)** — unknown/weak/moderate/strong/dominant. 0~1 float 금지(거짓 정밀, 철학 §3). 내부 랭킹 필요 시에만 임시 매핑(weak .25~dominant 1.0)하되 이는 효과 추정값이 아니라 탐색 휴리스틱. **(C) effect_direction 신설** — positive/negative/mixed(지금 CAUSES/BENEFITS_FROM 관계타입에 암묵적이던 부호를 명시). **(D) 순회 점수 개명** — narrative_graph.py의 "confidence 곱"을 `path_confidence`로 개명하고 UI에서 "영향도"가 아니라 **"경로 신뢰도"**로 표기(가장 잦은 오독 = epistemic reliability를 causal impact로 읽는 것 차단). **(E) 마이그레이션 = 재-enrich 아닌 백필 1패스** — 문서/임베딩/내러티브 본문 불변, `entity_relations`(2,760엣지)만 sonnet 배치로 effect_strength/direction 채우고 confidence 재산출(backfill_pace_layer·backfill_temporal와 동일 경제성). forward 경로(narrative·scenario·canon 프롬프트)는 처음부터 쪼개 태어나게. **(F) applicability는 저장하지 않는다** — geo_scope×reference_period×conditions×target_exposure의 **쿼리 시점 매칭 함수**(edge, target, context, as_of). 못 재는 성분은 1.0이 아니라 unknown으로 노출. min/게이팅(약연결 지배)이지 가중합 아님.
**맥락·이유**: docs/specs/0725-graph-improvement-plan.md 검토의 채택분. 단일 confidence=0.7이 "약하지만 확실"과 "강하지만 불확실"을 구분 못 하고, 그 곱이 사실상 multi-hop 대표점수로 쓰여 "가장 믿을 만한 경로"와 "가장 중요한 경로"가 섞인다 — 진단 타당. 메타원칙 #1 "분리해서 쌓는다"의 미적용 구멍(confidence 내부)을 메운다. **Phase 1로 스코프 한정**: 개념적 청결함만으로 5-Phase 재설계를 열지 않는다(D-004 "렌즈 1개 end-to-end 먼저"). effect_strength/direction 분리 + path_confidence 개명은 저비용·명백 정답이라 즉시, 나머지는 관찰된 실패가 동기가 될 때만.
**인지된 미해결 과제(이번 스코프 밖, 참조만)**: ① **한계 4 — BENEFITS_FROM이 CAUSES와 같은 곱셈 단위로 순회됨**. BENEFITS_FROM은 "제품 판매·가격 전가·원가 불변·물량 비상쇄·EPS 연결·미반영" 등 숨은 전제를 압축 → EXPOSED_TO 분해는 그래프 폭발·어휘 파편화 비용이 커 보류. ② **한계 5 — 재적재/내러티브 반복 ≠ 독립 근거**(말뭉치 복제편향: 보도자료 1 → 기사 10 → 블로그 20이 corroborated_by를 부풀림). relation_evidence 원장+independence_group이 해법이나, **독립성 탐지(어느 문서가 한 원천 계보인가)** 자체가 미해결이라 빈 테이블부터 만들지 않는다. ③ **target_exposure 데이터**(company_exposures) — applicability·수혜주 정밀도의 병목이나 지역/제품별 매출노출은 DART 사업부문이 얇음(데이터 획득 과제).
**기각한 대안**: ① 전체 재-enrich — 축 하나 추가에 내러티브 opus 재생성·버전·드리프트·승격 전부 재발화, surgical 위반. ② effect_strength를 0~1 float — 거짓 정밀(철학 §3), 문서 스스로 §7에서 금함. ③ lag_min/max_days(일 단위 수치) — confidence보다 더 심한 거짓 정밀(§3-2가 §7과 자기모순), 넣으려면 서수(즉시/분기/수년)로 후속. ④ applicability를 엣지 컬럼 저장 — geo_scope와 중복·"누구 기준" 애매, 쿼리 함수여야. ⑤ 5축 벡터(belief·impact·applicability·activation·fragility)를 지금 도입 — 데이터 없어 3축이 unknown/medium인 "정교하지만 빈" trace 위험, 실채움 2축(confidence·effect_strength)부터. ⑥ 기존 순회 즉시 폐기 — 내러티브·메르·세계관 뷰가 연결됨, path_confidence 개명 후 병렬 확장.
**참조**: docs/specs/0725-graph-improvement-plan.md(원 제안·Phase 2~5 상세) · PHILOSOPHY.md §1(같은 커밋 갱신) · SYSTEM.md §4-1 entity_relations · pipeline/narrative.py·scenario.py·narrative_graph.py·ingest_canon · 대화 2026-07-24~25 · [[D-005]] [[D-021]] [[D-034]] [[D-036]] [[D-004]]
→ D-066에서 effect_strength 5→3단계 축소(모델 A/B 근거).

## D-064 · 2026-07-24 · 수출입(무역) 팔로우 — 관세청 품목별 통계 추이 + 관련 종목(파급 논리)
**결정**: 수출입 무역통계를 transcript(D-061)와 같은 골격(팔로우 탭 + 전용 페이지)으로. **(A) 관심 품목 팔로우**: 전체 HS를 긁지 않고 핵심 품목 구독(시드 11종). **(B) HS 6단위 위주**: 관세청 API로 검증한 6단위(메모리 854232·시스템반도체 854231·EV전지 850760·스마트폰 851713)를 투자 서사 직결처에, 세분이 흐리는 광범위 카테고리는 2·4단위(철강 72·선박 89·플라스틱 39·석유 2710·디스플레이 8524·자동차 8703). **(C) 관련 종목 = LLM 파급 논리 지목**(D-036 계승): 문서 공동언급이 아니라 "이 품목 수출↑/↓ → 수혜/피해 종목"을 sonnet이 인과로 지목 → resolve_and_enrich(종목코드·RS·밸류·유니버스 태그). trade_beneficiaries 캐시. 유니버스 밖은 '신규 후보'(편입 고리 D-037). **(D) 국가 차원 후속**(MVP는 품목 총계). **(E) 데이터 소스**: 공공데이터포털 관세청_품목별 수출입실적, End Point `/1220000/Itemtrade/getItemtradeList`(XML·무료·개발계정 1만/일), `.env` DATA_GO_KR_KEY.
**맥락·이유**: BACKLOG "게이트 대기: 무역 커넥터 ← 관세청 API 키" 해제. observations(범용 시계열, D-004에서 비워둠) 대신 전용 trade_stats — 수출/수입/중량/무역수지가 한 행에 묶이고 HS품목이 entity 아니라 별도 축. **함정 2개**(구현 중 실측 해결): ① 승인 오픈API End Point가 `Itemtrade`(대문자, `nitemtrade` 아님)라 403 → 수정. ② 조회기간 최대 1년(code 99)이라 넓은 범위가 조용히 빈 결과 → resultCode 검사 + 연 단위 분할. 4·6단위 조회 시 10단위 세부행 반환 → 기간별 합산. 검증: 메모리반도체 관련 종목 LLM 지목 = SK하이닉스·삼성전자·한미반도체(HBM 장비)·심텍(기판)·원익IPS(증착) 수혜, LG전자(메모리 원가) 피해.
**기각한 대안**: ① 전체 HS 자동 수집 — 관심 밖 소음. ② 관련 종목을 산업맵/공동언급 재사용 — 이미 회자된 것만, 논리상 수혜 놓침(D-036). ③ observations 재사용 — 무역 구조와 부자연. ④ 모든 품목 6단위 강제 — 광범위 카테고리에선 거짓 정밀(철학 §3). ⑤ 국가 차원 즉시 포함 — 데이터·UI 복잡, 후속.
**참조**: docs/specs/trade-follow.md · 커밋 ff8a531·60a3484 계열 · SYSTEM.md §4-1·§5-1 · pipeline/trade.py·routers/spine_trade.py·TradePage.tsx · [[D-036]] [[D-061]] [[D-037]] [[D-004]]

## D-063 · 2026-07-24 · 노드 통합에 event(사건) 타입 편입 — 사건용 same 판정 규율

**결정**: D-062 후속 순차 2차. `MERGE_TYPES`에 `event` 추가(theme·macro·sector·event)하고, `judge_pairs`
프롬프트에 **사건 전용 규율**을 넣는다: "사건은 특정 발생이다 — 같은 발생을 표현·구체성만 달리하면 same
(예: 'SK하이닉스 ADR 상장'='SK하이닉스 나스닥 ADR 상장', 나스닥은 상장 장소 특정), 다른 시점·주체·상위/하위
사건이거나 방향 반대면 different(예: '공급 부족'≠'공급 완화', '반도체 종목 급락'≠'반도체 대장주 급락')."
intro의 대상 타입 명시도 theme·macro→theme·macro·sector·event로 일반화.

**맥락·이유**: D-062에서 event는 "시점·인과 특정성 때문에 theme용 프롬프트로는 과병합 위험"이라 프롬프트
튜닝 후로 미뤘다. 사건은 theme(개념)과 달리 개별 발생을 지칭해, "같은 발생인가"라는 판정축이 추가로 필요.
활성화 후 스캔 1회 검증: event 제안 3건(`미·이란`/`미-이란` 부호, ADR 상장 나스닥 특정, 페이팔 인수 제안/추진)
모두 정합 — theme용 규율만으로도 보수적이었으나 사건축을 명시해 정밀도 확인. 같은 세션에서 sector 5건은
사용자 승인→실제 병합 완료(`메모리 반도체 섹터`→`메모리 반도체` 등), 승인 큐 전 흐름(scan→제안→승인→
merge_entities→entity_merges) 검증됨.

**기각한 대안**: ① event를 프롬프트 튜닝 없이 활성화 — 사건 과병합(다른 발생 뭉갬) 위험, D-062에서 이미 기각
② 타입별 별도 프롬프트 함수 분리 — 현재 한 프롬프트에 타입 라벨(type=)이 있어 규율 한 줄 추가로 충분, 분리는 과설계.

**참조**: pipeline/vocab.py(MERGE_TYPES·_build_judge_prompt) · D-062·D-050 · 대화 2026-07-24

---

## D-062 · 2026-07-24 · 노드 통합 스캔에 sector 편입 + 타입별 cap + 실패 노출(silent-0 수정)

**결정**: 자동 노드 통합(D-050 `vocab_merge`)을 세 방향으로 고친다. **(A) 대상 타입 확장**: `MERGE_TYPES`에
`sector` 추가(theme·macro·sector). 실측 파편화가 sector(`메모리 반도체`=`메모리 반도체 섹터`, `보험`=`보험업`,
`전력 인프라`=`전력인프라`)·event에 몰려 있는데 기존 스캔은 theme·macro만 봐서 방치됐다. **(B) cap을 전역→타입별**:
`VOCAB_MERGE_CAP`을 15(전역)에서 30(**타입별**)로. 코사인 최상위는 theme의 '어간 vs 어간+방향' 벽(`나스닥`≠`나스닥
급락` — 항상 different)이 독식해, 전역 상한이면 sector·macro의 진짜 동의어가 판정조차 안 됐다. 타입별 상위 N쌍씩
판정해 각 타입에 예산 보장. **(C) 실패 노출**: `scan_vocab_merges`의 바깥 `except→return 0`을 제거하고 실패
(fastembed·판정 엔진 미가용)를 raise → `run_all`이 job_runs에 `error`로 기록. 예전엔 실패가 '제안 0건 ok'로
둔갑해 관리자 페이지에서 안 보였다(D-055 가시성 취지 위배). **(D) 관리자 표시**: admin 잡 행에 job 키·실제
진입점(scripts/…) 표기.

**맥락·이유**: 사용자 2026-07-23~24 — admin의 '노드 통합' 잡이 배선 후 실행 기록 0·제안 0이라 점검. 진단 결과
"엔진·로직은 정상, 0건도 규율상 옳음(top-15가 전부 진짜 different)"이었으나, 스크린샷으로 sector·event 실제
파편이 드러나 **원인은 cap이 아니라 스캔 타입 범위**로 재정의. dry-run 실측: sector 후보 201쌍 중 상위 30 판정
same 6(정밀도 양호 — 전공정/후공정·도매/소매는 정확히 different), event 171쌍 중 same 3. sector 먼저(안전·고수익,
위험 낮음)·event는 사건용 프롬프트 튜닝 후 2차로 **순차** 결정. 활성화 직후 스캔 1회 → sector 동의어 5건 제안 큐 적재 확인.

**기각한 대안**: ① cap만 상향 — 최상위 different 벽을 매주 더 비싸게 재기각할 뿐, sector는 여전히 미스캔 ②
크로스 타입 병합(theme `ADR 프리미엄` × event `ADR 프리미엄 확대`) — 온톨로지상 역할이 다른 노드 병합이라
의미론적으로 위험, 후보 생성도 타입 내로 한정 유지 ③ event 동시 활성화 — 사건은 시점·인과 특정성이 있어 theme용
프롬프트로는 과병합 위험, 프롬프트 튜닝 후로 미룸 ④ 기각 이력 메모이제이션(재판정 회피) — 효율 개선이나 별도
스코프, 이번 미포함.

**남긴 후속**: event 타입 활성화(사건용 same 판정 프롬프트) · 일요일 cron 미발화 원인 추적(agent_proposals job_run 0) ·
기각 쌍 메모이제이션으로 주간 재판정 낭비 제거.

**참조**: pipeline/vocab.py(MERGE_TYPES)·agent_proposals.py(scan_vocab_merges 타입별 cap·raise·run_all error 기록)·
ops.py+spine_admin.py+AdminPage.tsx(진입점 표시)·scripts/consolidate_vocab.py(기본 타입) · D-050·D-055·D-020 · 대화 2026-07-23~24

---

## D-061 · 2026-07-23 · Transcript 팔로우 — 미국 기업 실적 컨콜을 raw_documents로 흡수(Alpha Vantage 무료)
**결정**: **(A)** 미국 기업 실적 발표·컨콜 transcript를 **기업 단위 팔로우**로 수집 — 리포트 핵심질문(D-049)의 "관찰 프록시(미정)"를 실데이터로 채우는 1차 소스. **(B) 사일로 금지**: 전문을 `raw_documents(source_type='transcript')`로 넣어 기존 enrich→doc_causal(온톨로지)→digests(LLM 정리)→doc_vec가 자동 인수. `transcripts` 테이블은 팔로우/프록시 UI용 얇은 인덱스(raw_doc_id FK)일 뿐, 전문 중복 저장 안 함. 컨콜=경영진 1차 발언이라 doc_causal 인과 추출 품질이 높은 고신호원. **(C) provider-추상**: `TRANSCRIPT_PROVIDER` env로 어댑터 스위치. **Alpha Vantage 무료(25 req/day, EARNINGS_CALL_TRANSCRIPT, 화자 세그먼트+감성) 채택** — FMP transcript는 유료 전용(실측 402)이라 폴백. **(D) 화면 IA**: 전용 **2분할 브라우저**(좌 기업 그룹 리스트=구독 관리, 우 LLM 정리→프록시 델타→원문) 본진 + 피드 '컨콜' 소스 탭 보조. 기업 페이지 탭은 `/analyze`가 DART 기반 **한국 종목 전용**이라 보류(→ US 도시에 백로그 P1로 승격). **(E) 기본 세트 21종**(M7·ORCL·AVGO·AMD·AI DC[CRWV·IREN·NBIS]·RKLB·에너지[VST·CEG]·CPO[COHR·LITE]·SNOW·Web3[COIN·HOOD]) — 비상장(OpenAI·Anthropic·SpaceX·Databricks·Securitize)은 컨콜 부재로 제외(상장 시 편입·그전엔 canon/feed 추적), 전력반도체·바이오는 이번 세트 제외. **stage 1(적재)만 구현** — 전용 페이지·피드 탭·프록시 추출은 후속.
**맥락·이유**: 초기 리서치가 "FMP 무료 250 req/day"만 보고 transcript도 무료라 단정 → 무료 키로 402(유료 전용) 실측 후 Alpha Vantage로 전환(무료 demo 키로 IBM 실데이터·화자 37세그먼트 확인). provider-추상 덕에 어댑터만 교체. 검증: NVDA FY2026 Q3 컨콜 51KB 적재→enrich(haiku)→entity_links 12개 확인(온톨로지 엔티티 연결). 인과 엣지는 doc_causal cron이 후속 생성.
**기각한 대안**: ① FMP 유료 업그레이드(월 ~$29) — 무료 우선, 필요 시 어댑터로 승격 ② 기업 페이지에서 풀기 — 미국 도시에 부재(한국 전용), 신설은 큰 범위 ③ 피드에서만 — 실적시즌 훑기엔 소음에 묻힘 ④ 별도 사일로 테이블에 전문 저장 — 온톨로지·RAG 단절(초안의 실수, 교정) ⑤ API Ninjas — "상업용 불가"·무료 이력 제한 ⑥ 짧은 애널리스트 피드式 노출 — 홈 AI 피드와 중복(BACKLOG 보류).
**참조**: docs/specs/transcript-follow.md · 커밋 22882fc·c196a40 · SYSTEM.md §4-1·§5-1 · BACKLOG "리포트·액션 씨어리 후속 트랙" P0 · [[D-048]] [[D-049]]

## D-058 · 2026-07-23 · 메가 '세계관 서사'를 지식 탭으로 + 노드 통합을 관리자 독립 작업으로

**결정**: (1) 내러티브 랜딩에 있던 **메가 내러티브('세계관 서사', D-032)**를 지식 탭(지식 뷰) 상단으로 이관 —
온톨로지(전체 인과 그래프, D-052)의 '읽기'에 해당하므로 지식/온톨로지와 한 자리(세계관 서사·온톨로지 그래프·
검증 지식이 모두 월드모델 최상위 층). `MegaNarrativeSection` 컴포넌트 추출. (2) **노드 통합(vocab_merge, D-050)**을
관리자 페이지에 **독립 작업**으로 분리 — 기존엔 agent_proposals(run_all) 안에 묶여 안 보였음. ops.JOBS에 등록 +
run_all에서 자체 flag_enabled('vocab_merge') 게이트·record_run → 관리자에서 별도 on/off·실행 로그.

**맥락·이유**: (1) '세계관'이 내러티브 랜딩에 있어 층위가 어긋났다(사용자 2026-07-23) — 세계관 서사는 개별
내러티브보다 상위라 지식/온톨로지와 함께 두는 게 맞다. (2) "온톨로지 교통정리(유사 노드 통합) 작업이 관리자에
안 보인다"는 지적 — agent_proposals에 번들돼 있어서. 비용(sonnet)·파괴적 병합이라 독립 가시성·토글이 필요.

**참조**: frontend knowledge/MegaNarrativeSection(신규)·KnowledgePage·explore/NarrativePage(제거) ·
pipeline/ops.py(JOBS)·agent_proposals.py(vocab_merge 게이트) · D-032·D-050·D-052·D-055 · 대화 2026-07-23

---

## D-059 · 2026-07-23 · 내러티브 자동 재생성 24h 제한 + 새로고침 + 이력 타임라인 인라인 이동

**결정**: 내러티브 상세에 세 가지. **(A) 자동 재생성 24h 제한**: 진입 시 stale(새 문서 있음)이면 무조건 자동 compute하던 것을, **최근 갱신이 24h 이내면 자동 발화 금지**로 바꿈(프론트 `autoStale = stale && ageHours>=24`). created_at은 UTC라 파싱 시 `Z` 부착. **(B) 강제 새로고침**: 우상단 새로고침 버튼(`refreshNonce`)으로 24h 무관하게 compute 강제 트리거 — 단 백엔드 doc_ids_hash 가드로 새 재료가 없으면 no-op(status=cached), 이 경우 "새로 반영할 재료가 없어 갱신하지 않았습니다" 토스트. 성공(fresh) 시 "갱신했습니다" + 캐시·버전목록 무효화. **최근 갱신 시각** 헤더 표시. **(C) 이력 진입 이동**: 지난 D-060의 헤더 '이력' 버튼을 폐기하고, 재생성 이력 타임라인을 **본문 아래·파급 시나리오 위 인라인**으로 배치(도트 클릭 시 `/narrative/history?topic=&v=id` 디테일 페이지에서 본문 열람). 타임라인을 재사용 컴포넌트 `NarrativeTimeline`(인라인/상세 공용)으로 추출. 단발 diff만 보이던 `DriftBadge`는 타임라인이 전 구간 diff를 포함하므로 폐기.

**맥락·이유**: 자동 재생성이 진입마다 opus를 태워 비용·지연이 컸고, 하루에도 여러 번 여는 주제는 매번 재생성될 소지가 있었다. "새 재료가 있어도 하루 1회면 충분, 급하면 수동" 원칙으로 전환. 이력은 헤더 버튼보다 본문 흐름(서사→어떻게 바뀌어왔나→파급) 안에 두는 게 읽기 맥락에 맞다는 사용자 판단.

**기각한 대안**: ① 백엔드에 24h 게이트 — created_at 비교는 프론트에서 충분하고, 수동 강제(refresh)와 자동을 프론트에서 구분하는 게 단순. compute의 doc_ids_hash 가드는 그대로 재료-없음 방어. ② `/compute`에 force 파라미터 신설 — 불필요(해시 가드가 이미 재료 없으면 no-op). ③ DriftBadge 존치 — 타임라인과 중복.

**참조**: frontend `components/explore/NarrativePage.tsx`·`components/explore/NarrativeHistory.tsx`(NarrativeTimeline export) · SYSTEM.md §6 · [[D-060]](히스토리 타임라인 최초 도입)

## D-060 · 2026-07-23 · 내러티브 히스토리 타임라인 — 재생성 이력을 x축 도트로 열람

**결정**: 내러티브가 재생성될 때마다 덮어써지는 게 아니라 이미 버전별 행으로 보존되고 있음(supersede는 `superseded_at`만 찍고 body 미삭제, 새 버전은 새 row INSERT)을 활용해, **재생성 이력 타임라인 공간**(`/narrative/history?topic=X`, `NarrativeHistory.tsx`)을 만든다. x축에 생성 시점 도트(버전+날짜+제목), 도트 클릭 시 해당 버전 본문, 인접 도트 사이에 직전 버전 대비 인과 diff(기존 `/{id}/diff` 재사용)를 표시. 진입: 내러티브 상세 헤더의 '이력' 버튼(v2+일 때). 유일한 신규 백엔드는 `GET /api/spine/narrative/version?id=`(버전 본문 by id, 리포트 `/version?id=`와 동형, LLM 0).

**맥락·이유**: "재생성될 때마다 덮어써지는 것 같은데 이력을 보고 싶다"는 요청에서 출발했으나, 확인 결과 데이터는 이미 온전히 남아 있었다(D-023 버전 보존). 즉 신규 저장 구조가 아니라 **보존돼 있던 데이터를 드러내는 뷰**의 문제. 기존에 상세 페이지의 '지난 버전 대비 달라진 것'(DriftBadge)은 직전 1스텝만 보여줬는데, 이를 전체 이력으로 확장해 주제가 시간에 따라 어떻게 리프레이밍됐는지 한눈에 본다.

**기각한 대안**: ① 세로 타임라인 — 제목·diff 가독성은 더 낫지만 사용자가 x축 도트를 명시 요청. 가로 스트립으로 하되 도트 제목은 line-clamp, diff는 도트 사이 칩(클릭 시 상세 펼침)으로 해소. ② 월드모델 L2에 '히스토리' 탭 신설 — 히스토리는 주제별이라 전역 L2 탭과 안 맞음, 상세에서 진입하는 라우트가 맞음. ③ 버전 본문을 versions 목록에 미리 포함 — 목록이 무거워지고 대부분 최신만 보므로 도트 클릭 시 lazy 조회.

**참조**: frontend `components/explore/NarrativeHistory.tsx`(신설)·`components/explore/NarrativePage.tsx`(이력 진입)·`App.tsx`(라우트) · backend `routers/spine_narrative.py`(`/version?id=`) · SYSTEM.md §5-2·§6 · [[D-023]](버전 보존)

## D-057 · 2026-07-23 · 탐색 모드 해체 — 신호는 Home으로, 커버리지는 팔로우로, 리서치 제안은 승인 큐로

**결정**: D-056에 이어 **탐색(L1) 모드를 완전히 해체**한다. L1이 `Home ┃ 팔로우 → 피드 → 월드모델 ┃ 대화`(4개)로 줄고, 흐름은 입력→원천→종합으로 더 단순해진다. 세부: **(A) 신호 요약 → Home**: 탐색 랜딩의 언급 모멘텀·주목 주제·인과 그래프 활동을 Home 신호 대시보드로 이관(`components/home/HomeSignals.tsx` 신설), Home의 기존 '핵심 신호'(market_highlights 카드)는 중복이라 제거. **(B) 커버리지 → 팔로우**: 산업 맵(/map)·인물(/people)·기업활동(/actions)을 팔로우 서브탭으로 이동 — 전부 '내가 커버하는 대상'이라 팔로우(내가 따라가는 것)와 성격 일치. **(C) 리서치 제안 → 승인 큐**: 탐색의 ResearchProposalSection을 폐기하고 research_candidates를 `/api/spine/approvals` 집계에 편입(kind='research_candidate') — ApprovalsCard가 승인(→opus 심층 리서치)/기각을 처리, 헤더 인박스에서 다른 제안들과 함께 결정. **(D) 잔여물**: 신호 상세 목록(소외·52주신고가·컨센서스극단·거래량·괴리)은 `/explore?list=` 도시에로 유지(pill 없음, ExplorePage는 목록+유형 인덱스만), 백테스트(신호 성적표)는 보관함(ArchivePage)으로. 내러티브 티저는 Home 월드모델 델타와 중복이라 제거.

**맥락·이유**: 사용자 문답 — "홈에서 핵심 신호 빼고 탐색의 언급모멘텀·주목주제·인과그래프를 넣으면? 그럼 탐색>신호가 필요 없어지나?"에서 출발. 분석 결과 탐색의 신호 랜딩은 두 층(요약/상세)인데 요약이 Home으로 가고 커버리지(산업맵·인물·기업활동)가 팔로우로 가면 탐색에 남는 건 상세목록+백테스트뿐이라 L1 pill을 유지할 무게가 안 됐다. Home이 신호 대시보드까지 흡수하면서 "아침에 여는 델타 코크핏"이라는 실제 사용 습관과 정확히 맞춰진다(D-056의 연장). 리서치 제안을 인박스로 모은 건 '결정할 것'을 한 곳에 수렴시키는 D-056 승인 배지의 자연스러운 귀결.

**기각한 대안**: ① 탐색을 얇게 유지(신호 상세+백테스트만) — pill 하나가 거의 빈 모드를 가리켜 흐름을 흐림. ② 신호 상세목록까지 Home으로 — Home이 과밀해지고, 자주 안 보는 상세는 도시에가 맞음. ③ 백테스트 Home 잔류 — 자기검증 도구라 매일 안 봐서 보관함이 적절. ④ bare /explore를 /home으로 리다이렉트 — 신호 상세 유형(neglect·52w 등) 진입점이 사라져, 얇은 유형 인덱스로 남김.

**참조**: frontend `components/layout/ModeNavigation.tsx`·`components/home/HomePage.tsx`·`components/home/HomeSignals.tsx`(신설)·`components/home/ApprovalsCard.tsx`·`components/explore/ExplorePage.tsx`·`components/archive/ArchivePage.tsx`·`hooks/useWatchlist.ts`(타입 수정) · backend `routers/spine_approvals.py`(research_candidate 집계) · SYSTEM.md §6 IA · [[D-056]]

## D-056 · 2026-07-23 · 메뉴 재편 — L1을 파이프라인 흐름으로 + Home=아침 브리핑 + 승인 헤더 배지

**결정**: 메뉴의 1차 목적을 "판단 루프 은유"에서 **"데이터 흐름을 드러내기"**로 바꾼다. **(A) L1 재배치**: `오늘·팔로우·탐색·월드모델·피드·대화` → `Home ┃ 팔로우 → 피드 → 탐색 → 월드모델 ┃ 대화`. 가운데 4개가 파이프라인(입력→원천→감지→종합)을 좌→우로 그대로 보여준다 — 유일한 실질 이동은 **피드를 탐색·월드모델 앞으로**(기존엔 월드모델 뒤라 "원천→종합" 인과가 역행). Home·대화는 흐름에서 구분선으로 격리(Home=아침 요약 진입, 대화=횡단 도구), 월드모델은 매일 여는 종착점이라 약한 강조. **(B) '오늘'→'Home' 개명 + 아침 브리핑 재건축**: 죽은 4블록(승인/캘린더/하이라이트/업데이트) 중 캘린더·업데이트 제거, 시장 하이라이트→핵심 신호로 흡수, **월드모델 델타(변한/급증 내러티브 + 최근 리포트)를 진입 요약의 중심으로** 신설(사용자가 매일 여는 것). 기계의 3줄 브리핑은 유지. **(C) 승인 대기→헤더 상시 배지**: 홈에 묻혀 안 보이던 승인 인박스를 헤더 Inbox 배지(카운트)로 격상, 클릭 시 Sheet에 ApprovalsCard 재활용. 백엔드 무변경(narrative/list·report/list·approvals 기존 엔드포인트 재사용).

**맥락·이유**: 사용자 실사용 관찰 — 아침에 delta 요약(홈)을 보는 게 아니라 곧장 월드모델·신호로 간다. 즉 홈은 흐름의 진입점이 아니라 흐름과 경쟁하다 밀려난 잉여 페이지였고, `홈=delta`(비타협 원칙)의 실행이 습관과 충돌해 진 것. 캘린더·내 종목 업데이트는 "아예 안 봄", 하이라이트는 신호 탭과 중복, 승인만 가치 있는데 묻혀 있었다. 제품 한 줄 정의("매일 아침 여는 개인 리서치 터미널")는 유지 — "아침에 여는 곳"이 틀린 게 아니라 그 자리 내용물이 틀렸을 뿐이라, 실제 여는 것(월드모델 델타)으로 채웠다.

**기각한 대안**: ① 오늘 탭 완전 삭제 후 월드모델로 랜딩 — 아침 요약의 가치(기계 3줄·승인 카운트·신호 티저)를 버림. ② 홈 응답 확장으로 "변한 내러티브" 필드 추가 — narrative/list·report/list가 이미 급증·최신 플래그를 주므로 백엔드 변경 불필요. ③ 승인을 지식 페이지로만 통합 — 횡단 가시성(어느 화면에서든)을 잃음. ④ 팔로우 업데이트 스트림을 팔로우 페이지로 이관 — FollowPage(528줄)가 이미 종목별 업데이트를 StockRow에 담고 있어 집계 스트림 신설은 별도 작업, 후속으로 보류.

**참조**: frontend `components/layout/ModeNavigation.tsx`·`components/layout/Header.tsx`·`components/home/HomePage.tsx`·`components/home/ApprovalsCard.tsx`(hideHeader 옵션) · SYSTEM.md §6 IA · D-031(월드모델 분리)·D-023

## D-055 · 2026-07-23 · 운영 관리자 페이지 — cron 작업 on/off + 실행 로그

**결정**: 자동화(생성 cron)가 늘어나 비용·가시성 통제가 필요 → **관리자 페이지(/admin)** 신설. `feature_flags`
(작업 on/off) + `job_runs`(실행 로그: 상태·요약·소요시간·시각) 테이블 + `pipeline/ops.py`(flag_enabled·set_flag·
record_run·recent_runs·**run_job(name, fn) 래퍼**). 생성 스크립트 5종(compute_narratives·compute_digests·
scan_actions·agent_proposals·promote_knowledge) main을 run_job으로 감싸 ①플래그 off면 skip ②실행 기록.
API `/api/spine/admin`(jobs·runs·flag), 헤더 ⚙ 링크. 관리자는 작업별 스위치로 끄고 최근 실행·변경을 본다.

**맥락·이유**: 파급·리포트·통합·다이제스트 등 LLM 생성이 늘며 "무거워지지 않게 관리할 판"이 필요하다는
사용자 요청(2026-07-23). 개인 도구라 전용 스케줄러·워커 대신 SQLite 플래그 + 스크립트 진입점 게이트로
충분. run_job 래퍼로 스크립트당 1~2줄 편입, 실행마다 요약·소요시간 기록 → "뭐가 언제 돌았고 뭐가 바뀌었나".

**기각한 대안**: ① run_chain.sh(bash)에서 게이트 — 파이썬 요약/기록이 어려움 ② 전 스크립트 게이트 —
plumbing(ingest·signals·vault)은 저비용이라 생성 5종 우선(나머지는 후속) ③ 외부 스케줄러 도입 — 개인 도구엔 과함.

**참조**: pipeline/ops.py · database.py(feature_flags·job_runs) · routers/spine_admin.py · main.py ·
scripts/{compute_narratives,compute_digests,scan_actions,scan_agent_proposals,promote_knowledge}(run_job) ·
frontend admin/AdminPage·layout/Header(⚙) · 대화 2026-07-23

---

## D-054 · 2026-07-23 · 홈 브리핑(기계의 3줄) → 인박스 '공지'로 이관

**결정**: 홈 최상단 BriefingSection(소스 경고·가설 확인/충돌·공시 3줄)을 홈에서 제거하고 헤더 **인박스 Sheet의
'공지' 섹션**으로 이관. 인박스는 이제 [공지(기계가 포착한 변화) + 승인 대기(결정 필요)] 2단, 제목 '인박스'.
홈 상단은 AI 자동생성 피드(D-053)만 남아 깔끔.

**맥락·이유**: 브리핑 공간도 애매·무가치하다는 지적(사용자 2026-07-23, D-053 연장). 공지성 알림은 상시 진입점인
인박스에 모으는 게 맞다(승인 대기와 성격은 다르나 둘 다 '기계가 사람에게 전하는 것'). 브리핑 렌더는 BriefingList로
추출해 공유. 인박스 본문은 Sheet 열릴 때만 마운트(홈 payload 지연 로드).

**참조**: frontend home/BriefingList(신규)·HomePage(BriefingSection 제거)·layout/Header(InboxBody 공지+승인) · D-053 · 대화 2026-07-23

---

## D-053 · 2026-07-23 · 홈 최상단 'AI 자동생성 피드' — 무쓸모 승인 배너 대체

**결정**: 홈 최상단의 `ApprovalsBanner`(우상단 인박스로 유도만 하던 배너 — 무쓸모)를 **'AI가 최근 만든 것'
피드**로 대체. `GET /api/spine/home/ai-activity`(지난 7일 내러티브·리포트·파급·다이제스트를 created_at
최신순 통합, LLM 0) → 홈 `AiActivityFeed`(ProposalPanel 내부 스크롤, 유형 배지+제목+시각+링크). 승인 대기
건수는 피드 헤더 칩으로 통합("승인 대기 N · 우상단 인박스"). 자동화가 늘수록 "AI가 뭘 만들었나"를 홈에서
바로 보게 하는 진입점.

**맥락·이유**: 상단 배너가 헤더 인박스 배지와 중복이라 가치가 없었다(사용자 2026-07-23). 자동생성물(내러티브·
파급·리포트)이 쌓이는데 홈에서 최신 활동을 볼 곳이 없었음 → 연대순 활동 피드가 그 자리를 채운다. 승인
대기는 별도 배너 대신 피드 헤더 칩으로 흡수. **미해소 중복**: 기존 NarrativeDeltaCard(급증 주제)·
RecentReportsCard(최근 리포트)와 피드가 리포트에서 겹침 — 델타 카드는 '큐레이션'이라 일단 병존, 추가 통합은
후속(사용자 판단).

**기각한 대안**: ① 배너 유지 — 무쓸모 ② 델타 카드 즉시 제거 — 스코프 초과(요청은 배너 통합), 병존 후 판단.

**참조**: routers/spine_home.py(ai_activity)·frontend HomePage.tsx(AiActivityFeed, ApprovalsBanner 제거) · 대화 2026-07-23

---

## D-052 · 2026-07-23 · 세계관을 지식 탭으로 통합 + '세계관 뷰' → '온톨로지' 리네임

**결정**: 월드모델 서브탭에서 별도였던 **세계관(인과 그래프)을 지식 탭으로 통합** — 지식 안에서
**지식(검증 핵심) ↔ 온톨로지(전체 그래프)** 토글(`KnowledgeSubNav`). 월드모델 탭 3개로 축소:
내러티브·리포트·지식. 구 '세계관 뷰' 라벨은 **'온톨로지'**로 리네임. 라우트: 그래프는 `/knowledge/ontology`,
`/narrative/worldview`는 리다이렉트(레거시). 지식=`/knowledge`(기본).

**맥락·이유**: 세계관 ⊃ 지식(전체 인과 지도 vs 그중 검증돼 승격된 핵심, D-050)이라 둘이 겹쳐 보였고
R&R이 모호했다(사용자 2026-07-23). 한 탭에서 '전체 지도 ↔ 검증 핵심'을 오가는 게 개념적으로 맞고 탭도
간결해진다. '세계관'은 은유적이라, '월드모델'(상단 모드명과 중복)보다 **'온톨로지'**가 정확(사용자 선택).

**기각한 대안**: ① 세계관·지식 별도 유지 — 겹침·모호 지속 ② '월드모델'로 리네임 — 상단 모드명과 중복 혼란.

**참조**: frontend ModeNavigation(WORLDMODEL_TABS 3개)·App.tsx(/knowledge/ontology·worldview 리다이렉트)·
KnowledgeSubNav(신규)·KnowledgePage·WorldviewPage(h1 '온톨로지') · D-050 · 대화 2026-07-23

---

## D-051 · 2026-07-23 · 리포트 생성은 자동이 아니라 '승인 후' — report_suggest 제안 + 백그라운드 생성

**결정**: 리포트 자동 사전생성 대신, 재료(파급 시나리오 + 공유 내러티브)가 쌓인 주제를 감지해
**"통합 리포트를 생성할까요?" 제안(agent_proposals kind='report_suggest')**을 큐잉하고, 사람이 승인하면
생성한다. 승인 액션은 opus 연쇄(수 분)라 HTTP 응답을 막지 않게 **백그라운드 스레드**로 build_report 실행
(`_bg_build_report`), 승인 즉시 "생성 시작 — 리포트 탭에서 확인" 반환. 감지: `scenarios`에 파급이 있는데
아직 (최신) 리포트가 없는 주제(narrative_version별 dedup, cap 5). scan_report_suggestions는 LLM 0.

**맥락·이유**: 리포트는 다중 에이전트 opus 연쇄라 비용·시간이 크다(사용자 2026-07-23) — 자동 생성은
낭비·폭주 위험. 반면 파급 시나리오는 이미 그 주제가 주목할 가치가 있다는 신호이므로, "재료 쌓임"을
감지해 사람에게 물어보는 게 맞다(기계 제안·사람 승인, D-020). 승인의 무거운 액션을 동기 실행하면 요청이
타임아웃되므로 백그라운드 스레드(단일 사용자 개인 도구라 수용 가능; 결과는 append-only reports로 안착).

**남긴 후속(사용자 로드맵 순서)**: ② 홈 최상단 '지난 7일 AI 자동생성' 피드(기존 무쓸모 상단 알림 통합)
③ cron 관리자 페이지(작업·변경 내역·on/off) ④ 리포트 차트/짧은 애널리스트 피드. + 스캐너 파급 자동 예열은
팔로우·유니버스·신호 좋은 신규 종목으로 한정(리포트만 승인).

**기각한 대안**: ① 리포트 자동 생성 — 비용 폭주 ② 승인 시 동기 생성 — 15분 요청 타임아웃 ③ 큐 테이블+
전용 워커 — 개인 도구엔 과함, 데몬 스레드로 충분.

**참조**: pipeline/agent_proposals.py(scan_report_suggestions·_bg_build_report·approve report_suggest) ·
frontend ApprovalsCard(report_suggest) · pipeline/report.py(build_report) · D-020·D-043·D-047 · 대화 2026-07-23

---

## D-050 · 2026-07-23 · 노드 통합을 승인 큐로 주기화(cron 편입) + 세계관/지식 R&R 명확화

**결정**: (1) 비슷하지만 별개인 노드의 주기적 통합을 **승인 큐(agent_proposals kind='vocab_merge')**로 자동화.
주간 배치(run_all, include_llm)가 `find_merge_candidates`(fastembed ≥0.90, 상위 15) → `judge_pairs`(sonnet
same 판정) → same 쌍을 병합 제안으로 큐잉. 사람이 홈 승인 카드에서 승인하면 `merge_entities`(FK 재배선)
실행. 파괴적 병합이라 자동 적용 대신 사람 승인(D-020) — 기존 `--apply` 수동 흐름을 큐 흐름으로 승격.
비용 통제: 후보 상한 15·주 1회. (2) 세계관 vs 지식 **R&R 명확화**(UI 부제): 세계관=전체 인과 지도(가설
포함, 내러티브 갱신마다 상시), 지식=그중 반복·독립 관측으로 검증돼 승격된 핵심(주 1회). 세계관 ⊃ 지식.

**맥락·이유**: 통합 메커니즘(D-033)은 있었으나 cron 미편입이라 방치돼 파편 노드가 쌓였다(사용자 2026-07-23).
자동 적용은 위험(FK 대량 재배선)하므로 시스템의 승인 큐 패턴에 얹는 게 정합적. 세계관/지식은 둘 다
'인과'라 역할이 겹쳐 보였는데, 실제로는 빠른 전체 지도(가설) vs 느린 검증 핵심(승격)의 상하 관계 — UI에
갱신 시점·역할을 명시해 혼동 해소.

**남긴 후속(사용자 로드맵)**: 자동 사전생성(팔로우·유니버스 + 신호 좋은 신규 리서치 종목 선제) · **홈 최상단
'지난 7일 AI 자동생성' 최신순 피드** · **cron 관리자 페이지**(최근 작업·변경 내역·기능 on/off — 자동화가
늘수록 비용·가시성 관리 필요). 리포트 차트/짧은 애널리스트 피드(#5).

**기각한 대안**: ① 자동 병합 — FK 재배선 파괴적, 오판 위험 ② dry-run 파일만 주기 생성 — 사람이 안 봄
(승인 큐라야 행동) ③ 세계관/지식 통합 — 층(속도·검증 수준)이 달라 분리 유지가 맞음.

**참조**: pipeline/agent_proposals.py(scan_vocab_merges·approve vocab_merge)·vocab.py · frontend
ApprovalsCard(vocab_merge)·WorldviewPage·KnowledgePage(R&R 부제) · D-020·D-033 · 대화 2026-07-23

---

## D-049 · 2026-07-23 · 핵심 질문 = 지배 내러티브에서 도출 + 결론(상방/하방) 최상단 BLUF

**결정**: (a) 핵심 질문을 리드의 임의 판단이 아니라 **가장 강력한 지배 내러티브**에서 도출한다 —
`_narrative_power`가 구성원 내러티브별 인과엣지 수·앵커와의 공유노드 수를 리드에 신호로 넘겨, 리드가
지배 서사를 판별하고 그 서사가 던지는 질문을 핵심 질문으로 뽑는다. (b) 리포트 최상단을 **결론
헤드라인(BLUF)**으로 — Top-pick·레이팅·**상방 +X%/하방 -Y%**를 맨 앞에 못박고, 핵심 질문, 그 아래를
근거(산업·기업·시점·기술)로. 섹션 순서: 결론 → 핵심 질문 → 투자 포인트 요약 → 산업/기업/투자포인트/투자전략.

**맥락·이유**: 사용자 2026-07-23 — "핵심 질문은 곧 '가장 중요·강력한 내러티브가 무엇인가'를 가르는 것"
이고, "보고서의 핵심은 결국 upside 몇%·downside 몇%이며 나머지는 뒷받침 근거". 내러티브에 이미 재료
(공유노드·corroboration·엣지)가 있으니 지배 서사 판별을 신호로 정박할 수 있다. 결론을 앞세우면(BLUF)
PM이 원하는 "숫자 먼저" 구조가 되고 나머지 섹션의 역할(근거)이 분명해진다. 고정 목차(D-044)는 유지하되
결론·핵심 질문을 그 위 출발 프레임으로 얹어 긴장 해소(D-048 연장).

**기각한 대안**: ① 핵심 질문 LLM 자유 생성(D-048) — 지배 서사에 정박이 더 견고 ② 결론을 맨 뒤 유지 —
근거→결론 순서라 핵심(숫자)이 묻힘 ③ 내러티브 영향력 단일 점수화 — 엣지·공유노드를 신호로 주고 판단은
리드에 위임(과잉 정량화 회피).

**남긴 후속**: 관찰 프록시 = 사람이 초기 세팅(테마마다 다름) → 이후 자동 트래킹. transcript 커넥터와 함께
착수 예정(D-048 후속). 프록시 레지스트리(큐레이션) + 트래커.

**참조**: pipeline/report.py(_narrative_power·_lead[power_block]·body BLUF 헤드라인) · D-044·D-048 · 대화 2026-07-23

---

## D-048 · 2026-07-23 · 리포트 레이팅 = 상승여력(비대칭) + 핵심 질문·관찰 프록시로 논리 출발

**결정**: (1) 레이팅의 % 숫자는 **상승여력(upside, 상방)이지 포트폴리오 비중이 아님**을 명시 —
LLM이 'Buy·비중 25%'로 오해서술하던 것 교정. 투자 판단을 **하방(펀더 지지선 대비 -X%) 대비 상방(+Y%)의
비대칭**으로 전개(레이팅에 `downside_pct` 추가, 저장 업사이드 모델의 downside를 앵커로 주입, FE 배지도
'상방 +25% / 하방 -22%'로 명시). (2) 리포트 논리를 **핵심 질문(key_question) + 관찰 프록시(proxies,
선행지표)**에서 출발 — 리드가 "지금 가장 중요한 질문은 무엇이고, 현명한 투자자는 무엇을 프록시로
관찰하나"(예: 하이퍼스케일러 CAPEX 가이던스, AI기업 ARR, 자금조달, DC 착공)를 먼저 정해 리포트 최상단 +
투자 전략 감시 조건에 반영.

**맥락·이유**: (1) 사용자가 'Buy 25%'를 비중으로 오해할 소지 확인 — 투자 보고서의 본질은 하방 대비 상방
비교이므로 상방·하방을 함께 못박아야 한다. (2) 좋은 리포트는 "무엇을 관찰할 것인가(프록시)"라는 질문에서
출발한다(사용자 2026-07-23). 이는 고정 목차(D-044)와 긴장이 있으나, 목차는 유지하되 그 위에 '핵심 질문·
프록시'를 논리의 출발 프레임으로 얹어 해소(구조 vs 출발점은 층이 다름). 프록시 설정은 투자자 인사이트가
개입하는 영역이라 시스템은 후보를 제안하고 사람이 큐레이션(기계 제안·사람 승인)하는 게 장기적으로 맞다.

**남긴 후속(별도 인프라)**: **transcript(실적 발표·컨퍼런스콜) 수집 커넥터** — 하이퍼스케일러 CAPEX·ARR·
자금조달 같은 프록시의 1차 소스라 매우 중요. 새 소스 커넥터(수집→enrich→그래프)로 별도 구축 필요. ·
프록시를 유니버스처럼 사용자 큐레이션 대상으로 승격.

**기각한 대안**: ① 레이팅 %를 비중으로 유지 — 투자 논리의 본질(비대칭) 왜곡 ② 핵심 질문을 고정 목차의
한 섹션으로 — 출발 프레임이라 최상단·전 섹션 관통이 맞음 ③ 프록시 자동 확정 — 인사이트 영역이라 제안+큐레이션.

**참조**: pipeline/report.py(RATING_RUBRIC·_lead[key_question·proxies·downside_pct]·_cached_upside·ratings_line·
body 헤더) · frontend ReportView.tsx(상방/하방 배지) · D-044·D-047 · 대화 2026-07-23

---

## D-047 · 2026-07-22 · 리포트 — Top-pick 집중 + append-only 히스토리 + 다우이론 + 시점 규율

**결정**: 리포트에 4가지를 더한다. **(A) Top-pick 집중**: 여러 종목을 얕게 다루는 대신 리드가 최고 수혜
종목 1개(top_pick)를 골라 기업분석·투자포인트·투자전략을 그 종목 중심으로 심화하고 피어는 비교로만
(다른 종목 심층은 요청 시). **(B) append-only 히스토리**: `reports`를 anchor_topic PK 덮어쓰기 →
id PK 버전 누적으로 전환(구 표는 재생성 가능 캐시라 폐기). 최신=id DESC, `/history`·`/version` 엔드포인트로
과거 리포트 열람. **(C1) 다우 이론**: 기술 애널리스트가 고저 구조(HH/HL vs LH/LL)·거래량 확인·3국면
(축적/대중참여/분산)으로 추세 규정(_signals에 60일 고저·거래량 추세 추가). **(C2) 시점 규율**: 현재 분기
기준으로 2H·차년·차차년 수요/공급 경로를 구체화하고, **구체화 못 하면 명시 + "실적이 아니라 멀티플로
당겨온 기대"로 판정**(그만큼 조건부·리스크).

**맥락·이유**: (A) 하나에 집중해야 확신의 깊이가 나온다(브리프가 좋았던 이유와 동형) — 다만 교차비교
상실을 막으려 산업맥락+피어비교 유지. (B) 덮어쓰기는 과거 콜을 잃는다; 리서치는 시점별 판단 기록이
자산(revision_call처럼 실제 변화와 대조 가능). (C1) 다우는 RS/이평의 국면 해석을 추세 구조로 정박.
(C2) 사용자 통찰 — 시점을 못 박으면 아직 투자 부적합일 수 있고, 꿈만 크고 설득력 있으면 그게 멀티플
선반영의 정체다. 시점 구체화 능력이 곧 '실적 기반이냐 기대 기반이냐'를 가른다(2026-07-22).

**기각한 대안**: ① 별도 '종목 심층 리포트' 모드 — 현 리포트 진화가 '지금과 유사하지만'에 부합(사용자 선택)
② reports 덮어쓰기 유지 — 히스토리 상실 ③ 다우 스윙 고저 정밀 검출 — 60일 창 고저 근사로 비용 절감
④ 시점 자유서술 — 규율 없으면 모델이 시점을 뭉갬.

**참조**: pipeline/report.py(top_pick 선정·_timeline_rule·_signals[다우 고저·거래량]·technical 프롬프트) ·
database.py(reports append-only 마이그레이션·top_pick) · routers/spine_report.py(history·version) ·
frontend ReportView.tsx(히스토리·Top-pick 배지) · D-043~046 · 대화 2026-07-22

---

## D-046 · 2026-07-22 · 리포트 밸류는 12M Fwd PER 추이로만 — trailing PER 배제

**결정**: 리포트 로직에서 **trailing PER을 완전히 배제**하고, 밸류는 **12M Fwd PER + 그 변화 추이
(리레이팅/디레이팅) + 추정 EPS 개정**으로만 논한다. `_anchor_line`에서 trailing PER 필드 제거,
`_consensus`가 `consensus_estimates` 히스토리(동일 fiscal_year)에서 Fwd PER 최신 vs 과거를 비교해
'▲리레이팅/▼디레이팅 + 추정EPS 상향/하향'을 산출. 프롬프트(rubric·애널리스트·리서처·섹션) 전부
"후행 PER은 시장이 참고하지 않으니 쓰지 마라"로 통일. → D-045의 '후행 명시' 방침 번복.

**맥락·이유**: trailing PER은 시장이 실제 참고하지 않는 지표이고(사용자 2026-07-22), 특히 이익이 급변하는
국면(메모리 등)에선 오도한다. 시장이 보는 건 **선행 멀티플이 어디로 움직이는가** — Fwd PER 상승=리레이팅
(기대 확장), 하락=디레이팅(기대 축소 또는 가격 조정), 추정 EPS 개정=순수 기대 변화(가격 무관). 검증:
SK하이닉스 Fwd PER 6.84→5.83(▼디레이팅)·삼성 6.11→5.55 — 펀더 견고한데 선행 멀티플이 싸진 국면이
막스 진자(공포)·비대칭 기회 논지와 정량적으로 맞물린다. trailing(수십 배)로는 이 그림이 안 보였다.

**기각한 대안**: ① trailing·forward 병기(D-045) — trailing이 오히려 노이즈·오도 ② Fwd PER 절대값만 —
'지금 어디로 가는가'(추이)가 절대 레벨보다 신호가 강함 ③ Fwd PER만, EPS개정 무시 — 개정은 가격과 분리된
순수 기대 변화라 함께 봐야 리레이팅 원인(가격↓ vs 이익↑)을 구분.

**참조**: pipeline/report.py(_anchor_line[trailing 제거]·_consensus[Fwd PER 추이·EPS개정]·프롬프트) ·
consensus_estimates(fwd_per/fwd_eps 히스토리) · D-045 번복 · 대화 2026-07-22

---

## D-045 · 2026-07-22 · 리포트가 브리프 위에 선다 + 렌즈 모듈 주입(하워드 막스 사이클 추가)

**결정**: (1) 통합 리포트가 종목 분석을 밑바닥부터 재발명하지 않고, 각 종목의 **AI 브리프**(`compute_brief`,
게으른 캐시)를 재사용해 그 정합적 종합 + 정량(컨센서스·수급·상승분해·기술·PER밴드)을 컨텍스트로
주입한다. (2) `lenses.py`(사고 프레임 모듈)를 리포트 애널리스트별로 주입 — 펀더=LENS_INDUSTRY·
기술=LENS_PATTERN·수급=**LENS_CYCLE**(신규, 하워드 막스 사이클·진자). (3) 멀티플은 선행(12M Fwd,
consensus_estimates) 우선·후행 명시, 섹션 분량 제한 해제·`###` 소제목 허용.

**맥락·이유**: SK하이닉스 브리프의 디테일·정합성이 뛰어났던 원인은 '데이터 양'만이 아니라 **결정적 숫자
+ 계층적 사전 요약(문서→다이제스트→브리프)** 위에서 opus가 종합만 하기 때문(대화 2026-07-22). 리포트도
그 피라미드를 재사용해야 같은 정합성이 나온다 — 브리프는 종목 페이지와 공유되는 캐시 자산이라 비용도
상각된다. 또한 좋은 사고틀(lenses)이 narrative·rag·scenario·brief엔 쓰였지만 **정작 리포트엔 안 쓰이던
파편화**를 해소. 막스 사이클/진자는 수급·심리·밸류의 '지금 어디쯤인가'를 읽는 렌즈로, 하이닉스式 "공포로
간 비대칭 기회" 판정에 정확히 대응.

**기각한 대안**: ① 리포트가 종목 분석 자체 생성(현행) — 브리프보다 얕고 LLM 홉마다 숫자 흐려짐 ②
브리프 텍스트만 주입 — 정합성 유실 방지 위해 밑단 정량도 함께 ③ 렌즈 전량(3종) 무차별 주입 — 프롬프트
비대, 역할별 관련 렌즈만.

**검토 남김(사용자 요청 '검토만')**: 프레임워크 파편화 — lenses.py는 모듈 레지스트리지만 임계점 트리·
상승분해·비대칭 4분면 등은 stock_brief.py에 하드코딩돼 재사용 불가. 공용 사고틀을 lenses류로 모아
소비지점이 관련분만 불러쓰는 방향은 타당하나, 과잉 중앙화는 프롬프트 비대·결합도 상승 위험 → 점진 이관 권장.

**참조**: pipeline/report.py(compute_brief 재사용·_analyst 렌즈)·lenses.py(LENS_CYCLE) · stock_brief.py ·
D-043·D-044 · 대화 2026-07-22

---

## D-044 · 2026-07-22 · 리포트 목차 규격화 — 고정 템플릿(Top-down/Bottom-up) + 두괄식 (자유 목차 폐기)

**결정**: 리드 애널리스트가 매번 섹션 목차를 자유 생성하던 것(D-043)을 **고정 템플릿**으로 바꾼다. 리드는
**리포트 유형만 선택**(top_down/bottom_up), 섹션은 규격 고정:
- **Top-down**(산업 주도, 예: 반도체): 산업 분석 → 기업 분석 → 투자 포인트 → 투자 전략
- **Bottom-up**(기업 주도, 예: 소비재·화장품): 기업 분석 → 시장 분석 → 투자 포인트 → 투자 전략
각 섹션 브리프도 고정(산업 분석=세계관→내러티브→catalyst; 기업 분석=사업부별 매출·재무 건전성; 투자
포인트=이익/멀티플 재평가 이유; 투자 전략=매크로·밸류·기술적 국면). **두괄식 문단 규칙**(첫 문장 핵심,
이후 숫자·논리·맥락) 전 섹션 공통. 사업 분석엔 `business_segments`(사업부별 비중) best-effort 주입.

**맥락·이유**: 자유 목차가 (1) 같은 섹션 제목을 중복 생성하고(HBM 검증서 '강세 논거' 2회), (2) 리드
opus의 JSON(outline 포함)이 커져 파싱 실패 시 목차가 통째로 비어 리포트가 빈 채로 실패했다(822초 실패
사례). 목차를 코드 고정하면 리드는 유형·레이팅만 판단하면 되어 JSON이 작아지고, **리드가 실패해도 기본
top_down으로 섹션을 쓸 수 있어 견고**해진다. 규격은 사용자가 제시한 애널리스트 리포트 표준(2026-07-22)을
따름 — 예측 가능한 구조가 읽는 사람의 설득에도 유리.

**기각한 대안**: ① 자유 목차 유지(D-043) — 중복·빈 리포트 실패 ② 단일 고정 목차 — 산업주도/기업주도
리포트의 성격이 달라(반도체 vs 삼양식품) 유형 분기가 필요 ③ 유형도 규칙으로 자동 — 판단이 미묘해 리드에 위임.

**참조**: pipeline/report.py(SECTION_SPECS·PARA_RULE·_segments·_lead[report_type]·_write_section) ·
docs/specs/report-v2-agents.md · D-043(다중 에이전트) · 대화 2026-07-22

---

## D-043 · 2026-07-21 · 리포트 엔진 v2 — 다중 에이전트(애널리스트 팀·Bull/Bear debate·리드 판정·섹션 작성)

**결정**: 통합 리포트를 단선 종합(D-041/042)에서 **다중 에이전트 리서치 파이프라인**으로 재설계
(TradingAgents 착안, 자동매매 대신 리서치 리포트로 앉힘). 연쇄 LLM(pipeline 순차, 오케스트레이션 도구 아님):
① 애널리스트 팀(sonnet ×3 — 펀더·기술·수급) → ② 리서처 debate(sonnet ×2 — Bull vs Bear, Bear가 Bull
반박) → ③ 리드 애널리스트(opus ×1 — debate 판정 → 종목별 레이팅 + 섹션 목차) → ④ 섹션 작성(sonnet ×N)
→ 조립(A4 2~3p). **레이팅은 리드가 맥락 종합으로 부여** — D-042의 기계적 `warning→Sell` 오버라이드
**폐기**. 검증 산출물(analyst·bull·bear·ratings)은 `reports.debate_json`에 보존해 서비스에서 열람
(사용자 요건 "검증한 것 버리지 말고 DB 적재"). 기술 지표 확장: RS + 이동평균(20/60/120) + 볼린저%B →
기술 애널리스트가 **국면**(신고가 돌파·과열·건강한 조정·바닥)으로 해석. 스펙: docs/specs/report-v2-agents.md.

**맥락·이유**: 단선 opus 종합은 뷰가 충돌하며 벼려지지 않아 빈약했고, `RS 낮음→Sell` 같은 기계적 규칙은
**맥락맹**이었다(사용자 2026-07-21). 하이닉스 반례: 펀더 견고 + 쏠림 해소로 RS만 급락 = Sell이 아니라
재진입 여지일 수 있다 → 레이팅은 임계가 아니라 판단의 산물이어야 한다. 또한 좋은 투자는 **확률론+리스크
관리+타율 높은 상상력**이므로, 미래 상상(업계 리더 방향성 등)을 허용하되 **반드시 약세 반론(Bear)과
함께** 제시해 균형을 강제한다(debate). 비용(콜 ~11개, 리포트당 10분+)은 opus를 리드 1콜로 제한하고
나머지 sonnet, 종목 M=4로 통제 + members_hash 캐시로 재진입 0. 검증은 백그라운드 실행→DB 적재(중간
타임아웃 방지·산출물 보존).

**기각한 대안**: ① 단선 종합 유지(D-041) — 충돌 검증 없어 빈약 ② 기계적 레이팅 임계(D-042) — 맥락맹,
하이닉스 반례에서 오답 ③ 상상 전면 금지 — 로봇式 신산업 영원히 '판단 불가', 타율 높은 상상을 debate로
관리하는 게 낫다 ④ 멀티에이전트 오케스트레이션 도구 — 제품 파이프라인이라 report.py 내 순차 호출로 구현.

**참조**: pipeline/report.py(v2 전면 재작성 — _signals[MA·볼린저]·_analyst·_researcher·_lead·_write_section) ·
database.py(reports.debate_json) · routers/spine_report.py(debate) · frontend ReportView.tsx(논쟁·분석 디스클로저) ·
docs/specs/report-v2-agents.md · TradingAgents(TauricResearch) · D-041·D-042 · 대화 2026-07-21

---

## D-042 · 2026-07-21 · 리포트 설득 구조 + 종목 레이팅(콜 스코어) — 매수 일변도 금지

**결정**: 통합 리포트(D-041)를 (1) **설득형 Top-down 구조**로 확장하고 (2) 종목별 **레이팅**을 부여한다.
구조: `## 투자 포인트`(핵심 명제 1개) → `## 산업 내러티브`(설명) → `## Numbers`(정량 뒷받침) →
`## 종목`(레이팅·상승여력) → `## 리스크·무효화`, 2000~2600자. 레이팅 임계(사용자 정의 2026-07-21):
**상승여력 ≥50% Strong Buy · ≥15% Buy · 이하 Hold · 불안 신호(추세 붕괴·논지 훼손·과열) Sell**(`_rating`,
결정적). 상승여력·불안신호는 종목별 재분석(`_synth_stock`, sonnet)이 **펀더+심리+기술을 종합한 콜**(③,
워크플로 ④)로 산출 — 펀더=캐시된 업사이드 모델(①, `_cached_upside_pct`)·심리=최근 언급 모멘텀·
기술=RS·52주(`_signals`). 파급 없는 구성 내러티브는 리포트 생성 시 상한 2개까지 scenario 자동 보강(②).

**맥락·이유**: v1 리포트가 너무 짧아 논지를 설득하지 못했고(사용자 지적), 투자 리포트는 **매수 일변도가
아니어야** 한다. 그래서 (a) 하나의 투자 포인트를 세우고 산업 내러티브+Numbers로 설득한 뒤 종목으로
내려오는 애널리스트式 구조를 강제하고, (b) 상승여력 임계로 레이팅을 결정적으로 매기되 **불안 신호는
상승여력을 무시하고 Sell**로 오버라이드(펀더가 좋아도 타이밍·추세가 깨지면 사지 않는다 — "좋은 기업 ≠
좋은 종목", D-035 연장). 검증(HBM): 산업 논리는 강하나 RS 부진·레버리지 청산으로 전 종목 Sell — 매수
일변도가 아님을 실증. 레이팅은 결정적 함수라 LLM이 임의로 못 바꾼다(상승여력·warning만 LLM, 등급은 코드).

**기각한 대안**: ① LLM이 레이팅 직접 결정 — 임계 일관성·감사 불가 ② 상승여력만으로 레이팅(Sell 없음) —
매수 일변도, 위험 신호 무시 ③ scenario 전량 보강 — opus 폭주(내러티브 수만큼), 상한 2로 비용 통제.

**참조**: pipeline/report.py(_rating·_signals·_cached_upside_pct·_synth_stock·_synth_report·AUGMENT_CAP) ·
frontend ReportView.tsx(RATING_CLS 배지) · D-035(업사이드·좋은기업≠좋은종목)·D-041(통합 리포트) · 대화 2026-07-21

---

## D-041 · 2026-07-21 · 통합 리포트 — 공유 인과 내러티브 취합 → 종목 다각도 재분석 → Top-down (연쇄 LLM)

**결정**: 공유 인과로 엮인 내러티브들을 애널리스트 참고자료로 취합해 하나의 **Top-down 투자 리포트**
(산업 분석→기업 분석→투자 포인트·전략)를 생성한다. 앵커=주제 시드+공유 이웃(`related_narratives`),
깊이=종목 분석까지. 핵심: **같은 종목도 내러티브마다 파급이 다르므로**, 종목별로 각 내러티브의 파급을
다 모은 뒤(캐시된 scenario.beneficiaries) 그 다각도를 반영해 **다시** 분석한다. `pipeline/report.py`:
취합(LLM 0) → 종목별 재분석 ×M(sonnet, 연쇄) → 리포트 종합 ×1(opus). `reports` 캐시(members_hash
멱등, D-038 철학). `GET/POST /api/spine/report`. 스펙: docs/specs/integrated-report.md.

**맥락·이유**: 내러티브 각각이 이미 파급 시나리오·인과 구조·공유 내러티브를 낸다 — 이를 애널리스트가 여러
자료를 종합하듯 하나로 엮으면 산업→기업 리포트가 된다(사용자 2026-07-21). 선례 mega_narrative는 공유
노드 내러티브를 세계관 *서사*로 꿰지만 기업 분석·투자 전략이 없어 리포트가 아니었다 — 이걸 투자 리포트로
확장. 연쇄 LLM인 이유: 종목 재분석이 '여러 내러티브의 다각도 파급'을 입력으로 받아야 해서 취합→종목
종합→리포트 종합이 순차 의존(멀티에이전트 오케스트레이션 도구가 아니라 scenario/mega처럼 pipeline
순차 호출). 비용 통제: 리포트는 **캐시된 scenario·앵커·업사이드를 재사용**하고 새 scenario를 강제
생성하지 않는다(scenario 없는 내러티브는 body만); 전체는 members_hash로 캐시해 재진입 시 opus 0.

**기각한 대안**: ① mega_narrative 확장으로 처리 — 그건 서사지 리포트(기업 분석·전략 없음) ② 종목 재분석
없이 scenario 나열 — '같은 종목 다각도 종합'이라는 핵심을 놓침 ③ 멀티에이전트 워크플로 도구 — 사용자
명시 opt-in 없음, 순차 파이프라인으로 충분 ④ 리포트가 새 정량 창작 — 거짓 정밀, 캐시된 앵커만 사용.

**참조**: pipeline/report.py · routers/spine_report.py · database.py(reports) · main.py ·
narrative.related_narratives · scenario(캐시 beneficiaries)·upside_model._anchor · mega_narrative(선례) ·
frontend NarrativePage.tsx(ReportSection) · docs/specs/integrated-report.md · D-032·D-034·D-036·D-038·D-040 · 대화 2026-07-21

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
→ 레버 ③(문서 레벨 인과 추출)의 cron 보류는 D-088에서 번복 — 체인 편입(회당 10·멱등·run_job 게이트)

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
