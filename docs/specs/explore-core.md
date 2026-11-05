# 탐색 핵심 — 종목 발견 · 신호 · 컨콜 · 산업·섹터 (P6a)

- 상태: 구현 계약 (2026-10-16). 셸: [app-shell](app-shell.md) 탐색 L2. 위젯: [home-widgets](home-widgets.md) §2 계약.
- 세부 기능 계약은 각 담당 spec에 있다: 발견 워크스페이스 [technical-reading](technical-reading.md)·[market-strategies](market-strategies.md), 컨콜 [transcript-follow](transcript-follow.md)·[transcript-momentum](transcript-momentum.md), 섹터 서사 [sector-aggregation](sector-aggregation.md). 이 문서는 탐색 탭 4개의 화면 묶음과 위젯만 정한다.
- URL은 바꾸지 않았다. 옛 경로는 리다이렉트한다.

## 1. 종목 발견 `/discover`

워크스페이스는 그대로다. **추천 조건 묶음은 한 목록**이다.

| 항목 | 내용 |
|---|---|
| 정본 | `pipeline/market_analysis/discovery_service.PRESETS` (24개) |
| 필드 | `id` · `scenario`(rising 상승 후보 · recovery 반등·전환 · other 방향 미정) · `group`(라이브러리 묶음) · `name` · `tag` · `purpose` · `misses`(상황 렌즈가 못 보는 것) · `phrase`(문장으로 찾기에 덧붙일 조건 문장) · `conditions` |
| 읽는 곳 | 좌측 '빠른 시작'(scenario로 거름) · 라이브러리 '검색 제안' · 문장으로 찾기 '조건 추가' · 후보의 역방향 추천 |
| 규칙 | 방향 없는 관찰(스퀴즈·거래량 급증·52주 신저가)은 `rising`에 넣지 않는다. `?intent=<id>` 옛 링크는 그 묶음의 scenario로 범위를 복원한다(other → 모든 상황) |

예전의 FE 상수(`DISCOVERY_SCENARIOS` 12) · `LENSES` 8 · 인라인 templates 16은 삭제했다.

## 2. 오늘의 신호 `/discover#signals` (옛 신호 탭 `/explore`, 2026-11-05 개편 4c)

- 종목 발견 첫 화면(실행이 없을 때) 맨 위 블록(`analysis/TodaySignals`). 유형 8개 카드(언급 급증·주목 주제·소외·52주 신고가·거래량 급증·가격-관측 괴리·컨센서스 극단·**실적 발언 모멘텀**). 카드 = 이름 · 최신일 건수 · 정의 · 기준일 · 상위 3 칩(이름 중복 제거) · '이 신호로 찾기'. 유형 최신일이 전체 기준일보다 2일 넘게 뒤처지면 날짜를 주의 색으로. 모바일은 2열(이름 · 건수 · 상위 이름 두 줄 · 기준일).
- 원천: `GET /api/spine/signals/summary?days=7` — 유형별 `latest_date`·`count_latest`·`count_window`·`top[3]`(유형별 세기 순: 언급 수·점유율 변화·시총·돌파율·거래량 배수·|3개월 수익|·쏠림 비율·점수). `as_of` = 신호 최신일. 읽기 전용.
- **이 신호로 찾기**: `GET /api/spine/signals?type=&days=`에서 최신일의 국내 6자리 종목만 모아(`discoveryDraft.signalUniverse`) 조건 스택 초안의 검색 범위(`universe`)로 넣는다 → 검색 요청 `spec.universe_codes`. 스택 위 '검색 범위 · 52주 신고가 11/04 · 9종목 · 지우기'. 국내 종목이 없는 신호(주제·미국)는 목록 시트를 연다.
- 목록 시트 `?signal=<type>`(옛 `?list=`): 카드 목록, 기간 30일·주목 주제 14일·실적 발언 모멘텀 90일, 12개씩 더 보기, 국내 종목이면 '최신일 n종목으로 찾기'.
- 리다이렉트: `/explore` → `/discover#signals`, `/explore?list=X` → `/discover?signal=X#signals`, `/discover/signals` → `/discover#signals`. 위젯 `explore.signals` 전체 보기도 이 주소.
- 칩 목적지: 국내 종목 → `/analyze/:code/summary`, 미국(`payload.ticker`) → `/us/:ticker`, 그 외 → `/feed?q=`.
- 5-state: Skeleton 8칸 · 블록 ErrorState(아래 워크스페이스는 살림) · 신호 0건 한 줄 · 유형 하나 없음 → 카드에 '신호 없음' · 묵은 유형 → 주의 색 날짜.

## 3. 컨콜 `/follow/transcripts`

- 하위 탭(`TranscriptTabs`): 컨콜 · 실적 시즌(`?view=season`, 섹터 상세 `&sector=`; 옛 `?view=momentum`은 시즌으로, 2026-10-30 [실적 시즌](earnings-season.md)) . 옛 프록시(`?view=proxies`)는 2026-11-05(개편 4f) Thesis › 내 판단 '지표 보드'(`/questions?view=proxies`)로 옮기고 리다이렉트. 옛 미국 기업 목록 `/us`는 2026-11-05(개편 4d) 컨콜로 리다이렉트 — 기업 목록은 컨콜 보기 왼쪽 목록과 ⌘K.
- 컨콜 보기(`?t=` 없음 = 기업 목록) 맨 위에 **모멘텀 띠**: 이번 시즌 이름 · 발표 분석 수 · 새 모멘텀 수 · 상위 3 티커(점수) · 자세히.
- **실적 캘린더 '곧 발표'**: `transcript_calendar`(yfinance). 조회 실패한 종목은 쓰지 않는다(기존 발표일·`checked_at` 유지 → 다음 실행이 다시 묻는다). 연속 5회 실패면 네트워크 장애로 보고 중단. 비었을 때 '발표일을 아는 기업 k/N · 마지막 확인 M/D'를 보인다(`/follow` 행의 `calendar_checked_at`).
- `GET /transcript/momentum` 응답에 `as_of`(마지막 판정 시각, `call_momentum.computed_at` 최대, UTC).

## 4. 산업·섹터 `/map`

| `?view=` | 화면 | 원천 |
|---|---|---|
| (없음, 기본) | 섹터 상대강도 + Peer 그룹(2026-11-05 개편 4b, 아래) | `sector_map` · `sector_rs` · `/api/peers/runtime` · `/api/spine/sector-map/peers`(`sector_peer_map`) |
| `map` | 산업 맵 — 18 대분류 RS 사분면·구성표·밸류체인·소속 종목 | `sector_map` · `sector_rs` |
| `universe` | 유니버스 — 커버리지 큐레이션·섹터 서사·리포트 | `industry_groups/members` |
| `chains` | 산업군 지도 — 밸류체인 표·지도 | `industry_groups/members` |

- 옛 경로: `/follow/universe` → `/map?view=universe`, `/discover/industry` → `/map?view=chains`. 세 보기는 기본 화면 머리의 '다른 보기' 메뉴로 연다.
- **기본 화면(`industry/SectorBoard`, ia-redesign §4.7·§4.29)**: 왼쪽 섹터 상대강도 표(시총·장기 RS·단기 RS·5일·Peer 그룹 수, 머리 클릭 정렬 `sort`=long·short·chg5, 기본 시총) | 오른쪽 고른 섹터(`group`, 없으면 첫 줄) 머리(종목 수·시총·장기 RS·단기 RS 3주 흐름·5일) → Peer 그룹(섹터에 걸린 그룹의 구성 종목 중앙값 경로 60거래일 시작=100 상위 5선, 1위 굵게, 선 끝 라벨; 20일 중앙값 표 8줄; 'Peer 비교 열기 ›' = `/discover/peers?group=`) → 이 산업의 데이터(수출입·대만 공급망·밸류체인·미국 실적 시즌 중 그 섹터에 해당하는 것) → 섹터 → Peer 그룹 대응(18줄, 연결 없음은 한 줄, '부분' 칩). 모바일: 정렬 칩 + 섹터 줄(이름 아래 시총·종목 수·Peer 수), 줄을 누르면 아래 시트(장기 RS · 단기 RS 4주 흐름 · 5일, Peer 그룹 20일 중앙값 상위 3, 이동 칩). 차트·대응 카드는 모바일에서 숨긴다.
- **섹터 → Peer 그룹 대응(서버, 2026-11-05 개편 5단계 ③)**: `GET /api/spine/sector-map/peers`(`pipeline/sector_peers`, 모델 호출 없음)가 섹터 18개마다 `{sector, partial, note, links[]}`를 준다. 사람이 정한 연결은 `sector_peer_map`(초안 10개 섹터·16행·부분 4, 표가 비었을 때 `init_db`가 한 번 심음, source='seed'). 링크마다 `members`(구성 종목)·`classified`(산업 맵 섹터를 아는 종목)·`in_sector`·`share = in_sector / classified` — 섹터는 /map과 같은 `sector_rs._members` = `pipeline/sector_overrides.effective_sectors`(회사 → KSIC 업종 → `sector_map` 대분류, 그 위에 `sector_overrides` 업종 정정).
- **업종 정정(2026-11-05)**: KSIC 원천이 지금 사업과 맞지 않는 회사는 `sector_overrides`(추가형, 원천은 그대로)로 대분류를 바꾼다. 11-05 전수 점검 184건 — 기타 금융업으로 잡힌 비금융 지주회사 73 → 지주·기타, KSIC 연구개발업·과학기술 서비스업의 바이오 64 → 바이오·헬스케어, 토목 건설업(매핑 오류) 17 → 건설·부동산, 화장품 제조사 17 → 유통·소비재(화장품 그룹은 유통·소비재 아래), 업종 없는 신규 상장 9, Peer 근거 4(LS에코에너지 → 전력·에너지, 두산테스나 → 반도체·전자부품, 오르비텍·우진엔텍 → 전력·에너지). 근거는 결정적인 것만 — KSIC 매핑 오류, 이름 어휘, 사람이 정한 묶음(관심 산업 그룹·Peer 카탈로그), 문서 공동 언급. 애매한 건은 적용하지 않는다.
- **업종 체계 = 밸류체인 기준(D-315, 2026-11-05)**: KSIC보다 사업이 속한 밸류체인을 따른다. 검토 목록에서 73행 추가·수정 — 반도체 장비·소재 18 → 반도체·전자부품, 조선 기자재 10 → 조선·해운·운송, 원전 관련 9 → 전력·에너지, 2차전지 소재 5 → 2차전지·에너지소재, 방산 5(한화시스템·현대로템·풍산·SNT다이내믹스·인텔리안테크) → 항공·방산·우주, 자동차 부품 2(한국타이어앤테크놀로지·한온시스템) → 자동차·모빌리티, 사업이 사실상 하나인 중간지주 4(HD한국조선해양 → 조선, 에코프로 → 2차전지, 한미사이언스·삼성에피스홀딩스 → 바이오), 연구개발업인데 이름·자료 근거 없는 바이오 20 → 바이오·헬스케어. 멤버십 근거는 Peer 밸류체인 그룹·관심 산업 그룹 구성. 그대로 둔 것: 조선소의 방산 겸업(HD현대중공업·한화오션), 원전 EPC를 하는 종합 건설(현대건설·DL이앤씨·대우건설), 건설·조선 겸업(HJ중공업), 여러 사업 지주(LS 등), 복합 소재(SKC), 로봇·자동화 묶음, 이름만 바이오인 다른 업종(서울바이오시스 등).
- **자동 제안**: 연결이 하나도 없는 섹터에만, `share ≥ 0.6`이고 그 섹터 종목이 2개 이상이며 아직 어느 섹터에도 걸리지 않은(직접 걸렸거나 걸린 그룹 안에 구성 종목이 모두 든 사업군이 아닌) 그룹을 `source='auto'`로 붙인다. 읽을 때 계산하고 저장하지 않는다. 화면은 같은 칩에 섹터 이름 옆 '자동' 배지. 편집 화면은 없다.
- 프론트는 대응표를 받아 상위 그룹을 제품 그룹까지 편다(`lib/sectorPeers.sectorPeerGroups`, `peerChildren`). Peer 그룹 → 섹터 역방향('이 그룹의 업황 보기')은 직접 연결 › 상위 그룹 연결, seed › auto 순(`sectorOfPeerGroup`).
- 5-state: 블록 단위(섹터 표 오류와 Peer 가격 오류, 대응표 오류가 따로 — 대응표를 받기 전에는 Peer 그룹·대응 블록이 스켈레톤), Peer 그룹 없는 섹터는 '이 업종엔 아직 Peer 그룹이 없습니다' 한 줄(그룹 만들기는 운영 작업이라 링크 없음), 가격 없는 종목은 중앙값에서 뺀다.
- 선택 섹터 = `?group=<대분류>`(기본 화면·산업 맵 공통). 선택되면 밸류체인·소속 종목을 구성표 **위**에 보이고 산점도의 다른 점을 흐린다. 소속 종목이 없으면 그 사실을 문구로.
- 교차 링크: 국장 거래대금 섹터 쏠림 라벨 → `/map?group=`. 유니버스 그룹 → '산업 맵에서 보기' 칩 = 멤버가 속한 `sector_map` 대분류 상위 3(`GET /api/industries/{id}` 응답 `map_groups: [{name, members}]`).
- 두 섹터 체계(`sector_map` 18 대분류 · `industry_groups` 11 큐레이션)는 **합치지 않는다**. 이름이 달라 멤버 분포로만 잇는다. 통합 여부는 별도 결정.

## 5. 위젯 (탐색 탭, `widgets/explore.tsx`)

| id | 이름 | 원천 | 기본 크기 | 큰 숫자 · 한 줄 · 목록 | 고장 표시 |
|---|---|---|---|---|---|
| explore.signals | 오늘의 신호 | `/signals/summary` | 4×3 | 기준일 건수 · 유형 수 · 유형별 건수+상위 칩 | 신호 최신일 1일 초과 |
| explore.momentum | 이번 시즌 실적 모멘텀 | `/transcript/momentum` | 4×4 | 새 모멘텀 수 · 시즌·발표 분석 수 · 상위 3(티커·점수·대표 동인) | 판정 2일 초과 · SEC 미설정 |
| explore.calls | 최근 받은 컨콜 | `/transcript/recent?days=7` | 4×5 | 7일 수집 수 · 발표일 순 목록(받은 순 아님). 곧 발표는 홈 › 미국 시장 실적 시즌 블록 하나로(D-303) | — (머리 = 마지막 수집 KST) |
| explore.sectorShift | 섹터 사분면 이동 | `/sector-map` | 4×4 | 사분면이 바뀐 대분류 수 · 1주 전 → 지금 · 단기 RS 변화 큰 순 | 시세 기준일 3일 초과 |

사분면: 장기 RS ≥50·단기 ≥50 주도 / 장기 <50·단기 ≥50 부상 / <50·<50 소외 / ≥50·<50 과열·경계 (`hooks/useSectorMap.quadrantOf`).

## 6. 검증

`tsc -p tsconfig.app.json` · FE `node --test tests/*.test.mjs`(빠른 시작 범위 규칙) · 백엔드 `test_transcript_calendar`(실패가 기존 값을 지우지 않음·장애 중단·정상 기록) · `test_signals_summary`(유형별 최신일·상위 순·빈 상태) · `test_market_discovery`(PRESETS 한 목록·id 중복 없음·방향 미정은 상승 아님). 실제 화면: 탭 4개, `/map?group=`, 옛 경로 리다이렉트, 위젯 추가 창 탐색 탭에서 4종 추가.
