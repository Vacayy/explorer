# 회원 접근 및 세션 계약

상태: 구현 중. 기존 API에 인증/소유권 경계가 적용되기 전 외부 공개 불가.

## 인증 저장소

인증 데이터는 명시적으로 전달한 별도 SQLite 경로에 보존한다. import/객체 생성만으로 DB를 만들지 않으며 초기화는 명시적으로 실행한다. 테스트는 임시 DB만 사용한다. 기존 시장/개인 데이터 DB를 암묵적으로 열거나 수정하지 않는다.

검증된 Google issuer/subject를 identity 키로 사용하며 이메일만으로 계정을 합치거나 운영자로 승격하지 않는다. 신규 사용자는 member. operator 승격은 별도 명시적 관리 작업이다. 무작위 사용자 ID와 서버 세션을 사용하고 세션 원문 토큰은 발급 시에만 반환, DB에는 SHA256만 저장한다. 만료/폐기/비활성 계정은 세션 조회에 실패한다. 역할 변경과 비활성화는 다음 조회부터 반영한다. 토큰과 개인 claims는 로그에 출력하지 않는다.

별도 인증 DB는 기존 백업 도구의 최상위 SQLite 보존 대상에 포함될 경로를 운영 구성에서 지정한다. 실제 배포 전에 복원 및 설정 전달을 검증한다. 이 저장소만으로 기존 개인 데이터의 소유권 격리가 완료되는 것은 아니다.

## HTTP 및 데이터 경계 (연결 전 필수)

Google 로그인은 검증된 OIDC 응답과 state/nonce/PKCE를 사용한다. HttpOnly/Secure/host-only 세션 쿠키, CSRF 검증, 만료·폐기·로그인 시 교체. 인증되지 않은 identity claims로 세션을 발급하지 않는다. provider 검증 구현은 별도 검토한다.

공용 조회, 본인 소유 기능, 운영자 기능은 서버에서 분리한다. 목록/ID 상세/첨부/검색/캐시/스트림/배경 작업에 같은 소유권 경계를 적용한다. 신규 회원의 개인 공간은 비어 있어야 한다. 포트폴리오는 회원 소유 기능이다.

익명 채팅은 제한된 체험만 허용하며 대화 본문을 DB·로그·영속 파일·브라우저 영구 저장소에 기록하지 않는다. 사용량 메타데이터는 내용과 분리한다. 공용 자료만 검색하며 운영자 데이터나 CLI 인증 파일을 전달하지 않는다. 클라이언트 카운터만으로 한도를 강제하지 않는다.

## 화면 상태 계약

공개 데이터는 세션 확인 중에도 표시한다. 개인 블록은 세션 확인 동안 Skeleton, 비회원에는 로그인 안내, 회원 데이터가 없으면 Empty, 실패하면 Error/재시도, 공용만 준비됐으면 Partial, 본인 자료가 준비되면 Ideal. 로그아웃/계정 변경은 개인 요청 취소·캐시·대화 상태 제거를 수행한다. 로그인 후 고비용/쓰기 요청을 자동 실행하지 않는다.

## 검증

임시 SQLite에서 identity 중복/동일 이메일의 다른 subject/토큰 원문 비저장/만료/폐기/역할 변경/비활성 사용자/두 계정 분리를 검사한다. HTTP 연결 단계에서는 callback replay/CSRF/open redirect/session fixation과 교차 사용자 접근 검사를 추가한다. 저장소 단위 검사만으로 Google 로그인·웹 전체 보안을 완료 처리하지 않는다.

## 현재 구현 범위

`security.identity_store.IdentityStore`는 명시적 SQLite 초기화(0600), Google identity 고유키, member 기본 역할, 명시적 운영자 역할 변경, 무작위 세션의 SHA256 저장, 만료/폐기/비활성화를 제공한다. 생성자와 import는 DB를 만들지 않는다. 기존 비어 있지 않은 다른 DB는 수정하지 않고 거부한다.

`security.google_identity.verify_google_identity`는 `google-auth[requests]==2.62.2`로 서명/issuer/audience/시간을 검사한 뒤 서버 nonce 및 authorized-party를 검사한다. 이메일은 검증된 경우에만 부가 정보로 반환하며 사용자 키로 사용하지 않는다. nonce는 향후 일회용 서버 로그인 트랜잭션에서 공급해야 한다. 이 함수에는 state/PKCE/CSRF/HTTP 세션 처리가 없으며 독립적으로 로그인 완료를 뜻하지 않는다.

실제 Google 계정 없이 임시 RSA 키로 서명한 JWT를 사용해 정상/변조/다른 audience·issuer·nonce/만료·미래 발급을 검증한다. 모든 테스트는 임시 DB, 네트워크 없는 컨테이너에서 실행한다. HTTP router는 등록하되 명시적 설정 전에는503으로 비활성화한다. 기존 개인 데이터 소유권과 외부 공개는 아직 연결하지 않는다.

공식 참고: [Google OIDC](https://developers.google.com/identity/openid-connect/openid-connect), [서버 ID token 검증](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token), [google-auth verifier](https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.id_token.html).

CLI 기반 익명 체험은 별도 실행 경계에서 운영 DB/프로젝트/개인 RAG를 마운트하지 않고, 공용 근거만 입력한다. CLI 세션 기록을 비활성화하고 필요한 출력 파일은 tmpfs에서만 처리·정리한다. 기존 llm_calls.error의 원문 예외나 앱 대화 저장 경로를 재사용하지 않는다. 공급자 측 보존 정책과 서비스 내 대화 기록 비저장은 별개다. CLI 격리·비저장 검증을 통과하기 전 체험 경로를 열지 않는다.

## 익명 체험 사용량 예약 계약

`security.trial_quota`는 별도 명시적 SQLite 저장소에서 체험 횟수를 예약한다. 대화·원문 IP·쿠키·예외·모델 답변은 입력으로 받지 않는다. 서버가 만든 actor/network HMAC digest만 전달한다. 익명 쿠키의 발급·검증, IP 프록시 신뢰 경계 및 HMAC 키 관리는 HTTP 연결 단계의 책임이다.

한도는 actor 누적 체험 횟수(초기3회), network별 UTC 일간 횟수, 전체 UTC 일간 횟수, 전체 진행 중 요청 수를 함께 적용한다. DB write transaction 안에서 확인과 예약을 수행해 동시 요청 경쟁으로 한도를 넘지 않는다. 네트워크/전체 한도는 배포 정책으로 명시한다. 쿠키 삭제만으로 actor가 바뀔 수 있으므로 actor 한도 하나만으로 남용 방지를 주장하지 않는다.

예약은 reserved → running → finished. 공급자 실행 전 reserved만 released로 환불할 수 있고 실행 시작 뒤 오류/중단은 사용 횟수에 포함한다. released는 횟수에서 제외한다. reserved/running은 날짜가 바뀌어도 진행 슬롯을 차지한다. 시간만으로 슬롯을 해제하면 실제 실행 중인 프로세스와 중복되므로 자동 해제하지 않는다. 이후 dispatcher가 실제 컨테이너 종료를 확인하고 장애 예약을 정리해야 하며, 이 복구 경로 검증 전 운영 활성화하지 않는다. 동일 요청의 중복 상태 전이는 재차 환불/차감을 만들지 않아야 한다.

검증은 임시 SQLite에서 동시3회 초과 방지, 여러 actor의 network/global limit, 전날부터 진행 중인 슬롯, 실행 전 환불·실행 후 환불 거부 및 잘못된 원시 식별자 거부를 포함한다. 이는 HTTP 요청 제한·전체 실행 시간/토큰 한도·CLI 격리를 대신하지 않는다.

## 로그인 HTTP 계약

`GET /api/auth/session`은 authenticated/user(id,role)/csrf_token을 반환한다. Google start/callback은303리다이렉트, `POST /api/auth/logout`은{ok:boolean}. 모든 응답은no-store/no-referrer. 세션과5분짜리 로그인 binding은 __Host- Secure/HttpOnly/SameSite=Lax/Path=/ 쿠키를 사용한다. start는 안전한 내부 return_to만 받으며 callback은 단일 code/state와 binding을 검사한다. state를 원자적으로 일회용 consume한 뒤 PKCE코드 교환·nonce검증을 수행하고 기존 세션을 폐기한다. 공급자 오류·코드·토큰은 응답에 반영하지 않는다. logout은 정확한 HTTPS Origin과 세션별 CSRF 헤더를 요구한다.

활성화 설정은 EXPLORER_AUTH_ENABLED=1, EXPLORER_GOOGLE_CLIENT_ID, EXPLORER_GOOGLE_CLIENT_SECRET, EXPLORER_PUBLIC_ORIGIN(HTTPS), EXPLORER_IDENTITY_DB, EXPLORER_LOGIN_DB. 모든 설정 검증 후 명시적으로 초기화된 별도DB만 연다. 설정 누락/비활성/DB미준비는503이며 자동DB생성 없음. Google클라이언트/도메인 없이 실행되는 기존 리허설은 비활성 상태를 유지한다.

Uvicorn access의 정확한 callback 경로는 query를 제거한다. 프록시에서도 query와 Referer를 기록하지 않고 OAuth경로 upstream error에 전체URL이 찍히지 않도록 설정해야 한다. 실제Uvicorn과Nginx의 가짜code/state 요청에서 로그 비노출을 검증했다. Google실계정/외부TLS/쿠키 경로의 실제브라우저 검증은 아직 수행하지 않았다.

frontend/api/auth.ts는 생성된 응답 계약을 사용하는 session/logout 호출과 Google로그인 URL을 제공한다. 아래 공개 빌드에서는 계정 UI에 연결하며, 기존 개인 API 소유권 전체가 적용된 것은 아니므로 로그인 UI만으로 외부 공개하지 않는다.

## 공개 요청 진입 경계

`EXPLORER_ACCESS_MODE=private|public`을 import 시 검증한다. 기본 private은 기존 비공개 실행을 유지하며 공개에 적합하지 않다. public은 `security.access_boundary`의 ASGI 경계를 설치한다. 실제 공개 배포의 사전 검사에서 public 설정을 확인해야 하며, 이 변경은 Tunnel이나 운영 설정을 활성화하지 않는다.

현재 허용 목록은 `GET /api/health`, 기존 auth의 session/start/callback/logout 네 경로 및 `GET /api/spine/market/{market}/overview`, `GET /api/spine/industry/map`, `GET /api/spine/industry/us/map`, `GET /api/spine/industry/us/{ticker}/market`, 아래 승인 문서·첨부 GET과 운영자 검토/승인/철회 경로다. 메서드와 유효 route 경로를 함께 비교하고, 미분류 API·정적 media·API 문서 UI·WebSocket은 차단한다. 포함된 router의 prefix를 반영하며 등록하지 않은 정책·중복 정책 경로·알 수 없는 정책·public 쓰기 분류를 거부한다. 신규 라우트가 자동으로 공개되지 않는다. auth 경로는 기존 state/nonce/세션/CSRF 검사를 계속 수행한다.

member/operator 정책은 기존 IdentityStore를 매 요청 조회해 만료·폐기·역할 변경·비활성화를 반영하고 `request.state.principal`에 검증된 User를 전달한다. identity 헤더는 사용하지 않는다. 보호된 쓰기는 정확한 HTTPS Origin과 세션별 CSRF가 필요하다. 저장소 장애는 내용 없는503, 인증 실패401, 권한/CSRF 실패403, 미분류404다. 응답과 오류는 no-store이며 공용 캐시 최적화는 별도 계약 뒤에 한다. 응답 전 예외는 고정500으로 처리하며 이미 시작한 스트림에 예외 내용을 덧붙이지 않는다.

이 단계는 기존 개인 API를 member로 분류하지 않는다. 해당 저장소·목록·ID 상세·파일·파생 결과의 본인 소유권과 배경 작업 주체 전달이 검증된 뒤에만 허용 목록에 넣는다. 전체 시장 화면/회원별 포트폴리오/익명 비저장 채팅은 아직 공개되지 않았으며, 임시 차단 상태를 공개 기능 완료로 판정하지 않는다.

합성 ASGI 검사와 임시 identity SQLite로 두 회원/운영자 구별, 위조 헤더, 만료/폐기/비활성·역할 변경, 쓰기 Origin/CSRF, 실제 앱 등록경로의 미분류 차단, 정적 파일/메서드/WebSocket 우회, include prefix/parameter, 신규·중복 경로, 예외 비노출을 검사한다. 기존 Google HTTP 흐름 검사는 별도로 유지한다. 실제 Google 로그인·회원별 업무 데이터 격리·외부 프록시·공개 설정 누락 사전검사는 이후 수용 대상이다.

### 첫 공용 화면 데이터: 한국·미국 시장 개요

기존 `MarketHero`/`useMarketOverview`의 경로와 `MarketOverview` 응답은 유지한다. 공개 경계가 설정한 서버 내부 state에서만 공용 연결을 선택하며 클라이언트 헤더로 전환하지 않는다. `security.public_market.market_connection`은 기존 SQLite를 `mode=ro`로 열고 query_only 및 SQL authorizer를 적용한다. live WAL을 읽으므로 immutable 옵션은 사용하지 않는다. DB 생성·저널 전환·외부 수집·LLM 실행은 없다.

읽을 수 있는 데이터는 market_indicators(snapshot_date/indicator/value), index_intraday(key/trade_date/hhmm/value), retail_flows(date/credit_total/indiv_buy/indiv_sell), stock_prices(stock_code/trade_date/close)로 제한한다. 고정 overview 조회에 필요한 집계 함수만 허용하며 개인 테이블, 추가 열(extra_json 포함), DB 쓰기, ATTACH, PRAGMA 변경, 확장 로딩을 거부한다. 메모된 시장 폭과 응답 모델 역시 공용 수치만 사용한다. 이 열 제한은 임의 SQL API를 제공한다는 뜻이 아니다.

합성 개인 canary가 있는 DB에서 실제 익명 kr/us HTTP 응답의 비어 있지 않은 지수 값·기존 모델 일치·canary 비포함·원본 DB 바이트 불변을 검증했다. 직접 private table/column 조회와 쓰기 거부, 없는 DB 자동 생성 거부도 확인했다. 기존 시장 개요 계산 검사를 유지한다. 이는 시장 탭의 첫 지수/요약 블록이며 홈 전체의 개인 관심정보/원문/첨부 공개가 완료된 것은 아니다. 계정 UI 연결 범위는 다음 절에 기록한다.

## 공개 빌드의 계정 UI와 첫 화면 연결

`VITE_ACCESS_MODE=public`에서 `MemberAccessProvider`가 세션을 조회한다. 기본 private은 기존 개인용 UI를 유지하며 세션 조회를 시작하지 않는다. 잘못된 모드 값은 오류다. 이는 UI 선택값이며 서버의 EXPLORER_ACCESS_MODE를 대신하지 않는다. 공개 배포 사전검사에서 양쪽 설정과 실제 응답을 대조해야 한다.

Vite 빌드는 번들에 주입하는 같은 값으로 `_explorer/build.json`(version/access_mode/api_base)을 생성한다. public 빌드는 같은 origin의 API base(`""` 또는 `/`)만 허용하며, 빠진 설정 때문에 브라우저 localhost를 호출하는 빌드는 거부한다. API 공개 경계는 정상/차단 응답 모두 `X-Explorer-Access-Mode: public`을 표시한다. 배포 검사는 설정뿐 아니라 실제 서빙 파일과 live header/no-store를 대조한다. 표식은 공개 범위·권한·실제 Google 수용 완료 선언이 아니다.

`AccountControl`은 확인 중/익명 Google 로그인/회원·운영자 로그아웃/확인 실패 재시도를 표시한다. 세션 확인·실패가 공용 시장 화면을 가리지 않는다. 로그인 복귀 경로는 현재 내부 URL을 넘기고 서버의 기존 검증을 유지한다. 성공한 로그아웃과 확인된 계정·역할 변경에서는 요청 취소→query cache·앱 개인 browser storage 정리→전체 페이지 이동으로 이전 컴포넌트/모듈/첨부 메모리를 폐기한다. 세션/CSRF를 브라우저 저장소에 기록하지 않는다. 로그아웃 실패는 실패로 표시하고 미저장 초안을 삭제하거나 성공으로 가장하지 않는다. 테마와 다른 앱 저장소는 유지한다.

공개 화면은 기존 셸의 `/home`, `/home/kr`, `/home/us` 시장 개요와 아래 한국/미국 산업 지도·미국 섹터 가격 상세를 연결한다. `PublicContent`는 연결되지 않은 기존 개인 페이지를 숨겨서 마운트하는 대신 마운트하지 않는다. 공개 빌드의 전역 Omnibar/AnswerWatcher/ChatPanel, 관리자·개인 조회 버튼/모바일 개인 메뉴도 미마운트하며 검토 전 사용량/오류 telemetry 전송을 하지 않는다. 기존 private 빌드 동작은 유지한다.

이 분기는 첫 경로를 검증하는 **임시 구현 단계**다. 대부분 기존 화면·모바일 탐색·허용 검색·공개 원문/첨부·회원 포트폴리오·비저장 체험 채팅을 최종 수용에서 제외하지 않는다. 해당 API/데이터/도구 권한을 연결할 때 각 임시 제한을 해소해야 하며, 현재 축소된 연결 범위로 공개 완료를 선언하지 않는다.

검증: 전체 프론트281검사 및 TypeScript 통과. 별도 localhost Vite와 깨끗한 Chrome 프로필에서 실제 공용 시장 렌더링·390px 모바일 overflow 없음·비공개 페이지 미마운트·로그아웃 후 개인 draft/대기 대화 제거를 확인했다. API 요청16건은 session/kr·us overview/logout뿐이며 미승인 API0·uncaught 오류0. 시장 JSON은 합성 DB의 실제 ASGI 응답, 세션/로그아웃은 브라우저 fixture 응답이다. 실제 Google/OAuth/TLS 쿠키 수용이 아니다. 전용 프로세스·프로필·스크린샷·fixture는 검증 후 정리했다.

### 공용 미국 산업 지도

`/industry?market=us`는 기존 미국 ETF 지도·순위·이름/티커 검색·GICS/세부 업종 필터를 사용한다. 공개 `GET /api/spine/industry/us/map`은 sector_benchmark_prices의 ticker/trade_date/close만 읽으며 개인 transcript_follow와 문서/관심목록은 조회하지 않는다. 공개 응답의 coverage는 null(비공개)이고 0종목으로 가장하지 않는다. private 지도는 기존 팔로우 수를 유지한다.

공개 화면에서는 개인 커버리지 정렬/설명을 표시하지 않는다. Loading은 기존 skeleton, Empty는 시세 대기, Partial은 없는 지표의 '-' 및 받은 섹터 유지, Error는 재시도, Ideal은 지도/순위/카드·검색이다. 국내 지도·섹터 상세·허용 원문/첨부는 후속 연결 대상이며 이 단계로 전체 산업 화면 완료를 주장하지 않는다.

검증: 공개 산업/기존 미국 섹터/진입 경계24검사, 프론트283검사·TypeScript·생성 계약 일치 통과. 실제 Chrome1440px/390px에서 합성 SQLite로 계산한 ETF 응답을 공급해 지도·순위·개인 집계 미표시·상세 미마운트/복귀·가로 overflow 없음 확인. API4회는 session/미국 map뿐, 미승인 호출0/uncaught오류0. 실제 운영 데이터·Google 인증·외부 공개 수용은 아니며 테스트 프로세스/프로필/fixture는 제거했다.

### 공용 미국 섹터 가격 상세

`/industry/us/:ticker`는 `GET /api/spine/industry/us/{ticker}/market`의 시장 전용 모델을 사용한다. 응답에는 ETF 가격/수익률/RS/4주 경로·ETF/SPY 시계열·같은 상위 섹터 비교만 있다. 개인 coverage/members/docs/data_links 필드는 모델에도 없으며 개인 상세 함수를 호출하거나 결과를 지워서 만드는 방식은 사용하지 않는다. 기존 개인 상세 경로는 공개 허용하지 않는다.

지도→섹터→상위/같은 섹터→지도 동선을 제공하고 기존 가격 머리/기간 차트/RS UI를 재사용한다. Empty는 ETF 시세 대기, Loading은 skeleton, Partial은 비교 지수/일부 지표 '-' 유지, Error는 재시도와 없는 ticker404 안내, Ideal은 가격 차트·기간 선택·비교 이동이다. `tab=stocks|data` 직접 URL도 개인 탭을 마운트하지 않는다. 허용 원문/첨부와 회원 관심종목은 후속 경로로 유지한다.

상세 검증: 공용/기존 개인 미국 섹터·진입 경계26검사, 프론트285검사·TypeScript·생성 계약307개 일치 통과. 합성 DB의 실제 ASGI 모델 응답을 Chrome에 공급해 지도→SMH상세→3개월 선택→XLK상위→지도 복귀를 검증했다. 1440/390px에서 차트 렌더와 overflow0, API8건은 session/map/두 ETF 전용상세뿐이고 미승인호출0/uncaught0. 운영 서비스/실데이터/Google/외부 연결 수용은 아니다. 테스트 프로세스·브라우저 프로필·fixture는 정리했다.

### 공용 한국 산업 지도

한국 지도는 기존 회사→업종 정정의 공유 시장 분류를 유지한다. 개인 관심목록·문서·Peer 실행본은 읽지 않는다. 공용 요청은 자체 readonly 연결에서 계산하며 기존 전역 DB 연결/15분 캐시를 사용하지 않는다. 종목별 snapshot 메모는 요청 안에서만 유지한다. 출력 섹터 이름과 대표 ETF 설명은 코드의18개 benchmark SEED 범위로 한정하고, DB의 자유형 benchmark note와 업종 정정 reason/source는 읽지 않는다. 기존 private 계산은 기존 cache/분류 계약을 유지한다.

`/industry`의 기존 한국 지도/표/순위/카드와 한국·미국 전환을 사용한다. 공용 검색은 섹터/대표 ETF 이름만 대상으로 하며 Peer/종목 검색 API는 아직 호출하지 않는다. Loading skeleton·Empty 시세 대기·Partial 누락 지표 '-'·Error 재시도·Ideal 지도/카드·검색0건 안내를 유지한다. 한국 상세 및 Peer·허용 원문 연결은 후속이다.

한국 지도 검증: 전용4검사 및 관련42검사 중40통과/옵션 실데이터2건 skip(합계44통과). 개인 설명 변경 불변·공유 업종 정정 반영·임의 섹터명/benchmark canary 제외·전역 연결/cache/Peer 미사용·readonly SQL 거부를 확인했다. 프론트286검사·TypeScript·계약307개 일치 통과. 합성 DB 실제 ASGI 응답으로 Chrome1440/390px 한국 지도/카드·ETF 검색·검색0건·한국→미국 전환을 확인했고 API6건은 session/두 지도뿐, 미승인0/uncaught0/가로overflow0. 실제운영DB/외부공개 수용 아님. 임시 프로필/fixture/전용서버는 정리했다.

### 승인 문서·본문·첨부와 철회

공용 GET `/api/public/documents/{doc_id}`는 명시적으로 승인한 공개 투영만 반환한다. id/title/source_type/url/published_at/content/content_kind/attachments가 전부이며 개인 태그·메모·작업·연관자료는 없다. content는 저장된 markdown 우선, 없으면 raw_content다. 저장된 가공 본문일 수 있으므로 UI는 '보관된 본문'으로 표시하고 원문 그대로라고 보장하지 않는다. 출처 종류 자체는 공개 권한의 근거가 아니다.

운영자는 GET `/api/operator/publications/{doc_id}/preview`로 문서/첨부 목록/fingerprint/현재 version과 보호된 attachment_previews URL을 받는다. GET `/api/operator/publications/{doc_id}/preview/{fingerprint}/attachments/{attachment_id}`로 실제 파일을 검토한다. POST approve는 fingerprint/expected_version/rights_basis 및 personal_data_excluded=true를 요구한다. POST revoke는 expected_version을 받는다. 경로 앞부분은 동일한 `/api/operator/publications/{doc_id}`이며 회원은 운영자 경로에 접근할 수 없다. 기존 세션 역할과 Origin/CSRF를 검사하고 버전 충돌은409로 재검토를 요구한다. 운영자 검토 UI는 아직 없다.

EXPLORER_PUBLICATION_DB는 업무 DB와 다른 절대경로의 명시적 PublicationStore.initialize 대상이다. 요청/import 자동 초기화는 없고 누락/장애는503이다. 배포 시 영속 볼륨과 SQLite-aware 백업/복원 범위에 포함해야 하며 현재 운영 환경에는 초기화/연결하지 않았다. 테이블은 publication_metadata와 현재 publications 결정이며 과거 본문/개정 이력 저장은 제공하지 않는다.

승인은 실제 응답 전체와 첨부 상대경로·해시·크기·유형의 fingerprint에 결합한다. markdown만의 기존 content_hash는 근거로 쓰지 않는다. 매 GET마다 readonly 원본 조회와 첨부 검증, 승인 재조회로 변경/철회를 확인한다. 미승인/철회/변경/없는 문서는 같은404다. 공용 첨부 GET `/api/public/documents/{doc_id}/attachments/{attachment_id}`도 문서 전체 승인 검사를 통과해야 한다. 검증했던 바이트를 그대로 반환하며 경로를 다시 열지 않는다. 디렉터리 FD/O_NOFOLLOW로 중간 symlink·경로탈출을 막는다.

본문 UTF-8 2MiB, 첨부16개/개별16MiB/합계64MiB 제한이며 PNG/JPEG/GIF/WebP/PDF의 시그니처만 허용한다. 완전한 파일 무해성 검사나 악성코드 검사는 아니다. PDF는 다운로드, 이미지는 inline, nosniff/sandbox/no-store/same-origin을 적용한다. 한도 초과/지원하지 않는 첨부가 있으면 문서 전체를 공개하지 않는다. 큰 문서의 공개 분할은 후속 정책이 필요하다. 철회 전에 이미 전달된 바이트/다운로드를 회수할 수는 없다.

공개 `/doc/:docId`는 전용 GET만 사용하며 Markdown 임의 이미지와 상대 파일 링크를 로드하지 않는다. 공개 첨부 URL만 이미지/PDF로 제공한다. Loading·Empty404·Partial 본문 없음/첨부 실패·Error 재시도·Ideal 본문/첨부를 제공하며 재검증 중/오류/404에는 캐시된 본문을 숨긴다. 새 방문/창 복귀 시 재검증하며 실시간 강제 회수(push)는 아니다.

합성 ASGI8검사+경계10검사 통과: 운영자/회원/익명, Origin/CSRF, stale 승인/철회, 동일 content_hash에서 metadata/media 변경, 파일바이트 변경, 경로탈출/symlink, 검증중 철회/파일교체, private 모드와 저장소 미설정, 원본 DB 불변. 프론트292검사·TypeScript·311응답 계약 일치 통과. 실제 ASGI 합성 응답을 Chrome1440/390px에서 렌더해 승인 본문/이미지/PDF 링크·재검증404 본문 제거·가로overflow0·미승인 API0·uncaught0을 확인했다. 기존 셸 Google Fonts 요청은 존재하며 문서 임의 외부 이미지 요청은0이다. 범용 live 검사에는 문서1 예시를 두지만 실제 승인·운영자 세션이 없으면 미검증으로 보고해야 한다. 파일 경로2개는 JSON이 아닌 바이너리로 명시한다. 운영 서비스 재시작/실데이터 선정/Google/외부 공개 검증을 대체하지 않는다.

실제 자료 선정은 운영자가 출처의 배포 권한 근거와 개인 기록 제외를 확인한 뒤 preview 본문 및 각 파일을 검토하는 절차다. 실제 담당 계정/소스별 근거 목록은 PM과 소스 담당이 운영자에게 확인할 미해결 항목이며, 합성 검사 통과를 실자료 일괄 승인으로 취급하지 않는다. 검색·피드·인용은 이 승인 경로에 연결하기 전 공개하지 않는다.

### 회원 포트폴리오 첫 연결 (준비 코드, 운영 미적용)

`/api/member/portfolio` 및 `/history`, `/transactions` GET은 검증된 principal 소유 그룹만 조회하며 기존 PortfolioSummary/HistoryPoint/TransactionItem 계약을 유지한다. 새 회원의 조회는 빈 응답이고 쓰기/그룹 생성이 없다. POST `/transactions`는 기존 TransactionCreate 입력, `{ok,id}` 응답, DELETE `/transactions/{tx_id}`는 `{ok}` 응답이다. Origin/CSRF 및 세션 회원 확인을 적용한다. 회원용 `/companies?q=` GET은 회사 코드·이름만 최대20개 제공한다. 사용자 body/header의 owner/group ID는 받지 않는다.

명시적 준비 작업에서 stock_groups.owner_id(nullable TEXT)와 portfolio owner별 unique partial index를 추가한다. 기존 행은 NULL로 그대로 보존하며 첫 로그인에게 배정하지 않는다. 기존 private group 선택은 NULL 소유만 사용하여 신규 회원 그룹을 잡지 않는다. 운영자 실제 identity 매핑은 private job 주체 연결/백업/동결과 함께 후속 적용하며 여기서 실행하지 않는다. 요청은 준비되지 않은 schema/DB를 자동 생성하지 않는다.

회원 쓰기는 BEGIN IMMEDIATE 뒤 소유 그룹 선택/생성, 자동 부족금 입금+거래+members 변경을 하나의 트랜잭션으로 처리한다. 실패는 그룹 생성까지 rollback한다. 타인/없는 거래 삭제는 같은404로 처리한다. summary/history/transactions는 동일 읽기 snapshot에서 기존 순수 계산을 사용한다. 원칙·논지·알림·exposure/events/flow·시세 수집과 기존 그룹/검색/도구 경로는 소유권 연결 전 공개 허용하지 않는다. 부분 연결은 전체 포트폴리오 완료가 아니다.

공개 `/portfolio` 화면은 비로그인 Google 로그인 안내, Loading, 빈 포트폴리오와 거래 추가, Partial 누락 시세, Error 재시도, Ideal 비율/가격/거래 내역을 제공한다. 금액·수량은 입력 때만 사용하며 조회에서 노출하지 않는다. 회원별 query key와 기존 계정 전환 전체 캐시 제거를 사용한다. 회원 전용 hook만 마운트하며 개인용 자동 시세갱신/원칙/논지/알림 요청을 시작하지 않는다. 첫 UI는 기존 입력/표 컴포넌트를 재사용하되 미연결 기능은 완료로 표시하지 않는다.

거래 입력은 실제 달력 날짜와 유한한 amount/price만 받는다. 원장 재생의 cash/수량/평단/원가가 계산 범위를 벗어나면409로 전체 rollback한다. 회원422 응답은 제출한 원장 input/금액/메모를 다시 보내지 않고 loc/type/msg만 제공한다. 회사 검색은 기존 입력 계약에 맞는6자리 대문자/숫자 코드와 이름이 있는 회사만 조회하며 NULL/빈 코드 행은 제외한다.

회원 기능8개 ASGI/동시성 검사와 기존 포트폴리오·경계 회귀를 포함한73검사 통과. 신규/기존 회원 UI·인증을 포함한 프론트300검사, TypeScript,317응답 계약 일치 통과. Chrome1440/390px에서 실제 ASGI 합성 응답으로 비로그인 차단→빈 공간→입금→회사 검색·매수→비율/차트/거래 조회→매수 삭제→입금 삭제·빈 공간을 확인했다. API27회는 session/회원 포트폴리오뿐이며 쓰기 CSRF·입력 body를 대조했고 uncaught0/미승인API0/가로overflow0. 브라우저는 합성 응답 재생이며 실제 Google/운영 DB/외부 공개 수용은 아니다. 범용 live 검사는 실제 로그인 없으면 해당 경로를 미검증으로 보고해야 한다.

기존 GroupDigestTests의 us_prices 없는 fixture 실패는 변경 전 portfolio 코드에서도 재현되었다. 실제 그룹 상세의 한미 날짜 조회에 필요한 빈 us_prices fixture를 추가했으며 동작 검증을 생략하거나 production 쿼리를 완화하지 않았다.

**기존 작업의 회원 기록 제외:** `pipeline.group_ownership.legacy_groups_condition`은 고정 SQL alias g에 대해 ownership 준비 전 전체 legacy, 준비 후 owner_id IS NULL을 반환한다. schema 검사는 캐시하지 않는다. `kr_company_data.targets()`의 보유/관심 우선순위와 이를 사용하는 수집 script의 개인 컨센서스 대상, `world_reads._member_companies()`를 사용하는 개인 서사 연결/체크포인트, `watch_rules.evaluate_all()`의 그룹 선택 및 선행 `refresh_us_prices()`에 적용한다. 공용 시가총액/코드상 산업 연결 수집은 유지하며, 회원이 같은 종목을 보유한다는 이유로 공용 시장 수집에서 제외하지 않는다.

합성 legacy 결과를 ownership 준비 전 저장하고 A/B의 별개·겹치는 종목/그룹 추가 후 대조했다. 개인 수집 우선순위·월드 보유집합, 실제 watch 평가 결과와 job 요약/미국 가격 수집 호출은 동일하며 회원 그룹 평가0이다. 외부 provider는 stub, Docker network none에서 관련47검사와 main import 통과. 기존 수집 script 회귀 fixture에서 새 consensus/preliminary 두 단계의 stub/기대값이 빠져 있었고 보완 후 전체 단계 계속 실행·실패 exit1 검사를 유지했다.

이 검증은 위 연결 경로의 합성 격리 수용이다. `watch_reasons`/`stock_tracker` 등의 watch 전용 조회는 현재 회원 API가 portfolio만 만들므로 이번 경로에 연결되지 않으며, 회원 관심묶음을 도입하기 전에 별도 소유권 적용이 필요하다. 기존 그룹 API/원칙/논지/알림·파생 전체/실제 소유 매핑과 운영 backup/restore·공개 사전검사는 미완이다. prepared code를 즉시 운영 활성화하거나39개 실제 작업 전체를 수용했다는 의미가 아니다.
