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

## 익명 체험 공개 근거 계약

체험 채팅의 근거 준비는 `security.public_evidence`에서 공개 승인 경계만 사용한다. 명시된 문서 최대4개 또는 검색어 최대120자의 공개 목록 최대3페이지를 조회하며, 전체 읽기 예산128MiB를 공유한다. 개인 검색/RAG로 대체하지 않는다. 문서별 발췌는 최대4096 UTF-8 bytes, 모델 문맥 JSON은 최대24KiB이며 잘림/검색 미완은 partial로 표시한다. 검색은 기존 목록의 문자열 검색으로 전체 자료의 의미 검색을 보장하지 않는다. 근거가 없으면 모델을 호출할 문맥을 반환하지 않는다.

문맥에는 서버가 부여한 D1…D4와 승인 snapshot의 id/fingerprint를 메모리에서 묶는다. 답변은 전체 버퍼링하며 반환 직전 **모델이 인용하지 않은 문서까지** 모든 문맥 문서의 본문/첨부를 별도128MiB 예산으로 다시 검증하고, 최종 승인 집합을 한 SQLite 조회로 확인한다. 변경·철회 또는 재검증 예산 초과이면 답변 전체를 폐기한다. 모델은 citation ID만 제안할 수 있고, 반환 링크/제목은 검증된 서버 문서에서 만든다. 답변 문자열은 plain text로 취급하며 모델의 임의 URL을 인용 링크로 승격하지 않는다. 이 내부 모듈만으로 실제 모델 호출·HTTP quota·브라우저 비저장이 완료되는 것은 아니다.

## 익명 체험 식별과 실행 연결 (준비 모듈)

`security.trial_identity`는 32-byte 별도 비밀키로 버전·발급시각·256-bit 난수를 서명한 30일 쿠키를 검증한다. actor/CSRF/network HMAC 용도를 분리하며 만료·미래 발급·변조를 거부한다. 원문 IP와 쿠키를 사용량 저장소로 넘기지 않는다. 프록시 CIDR이 명시된 peer만 단일 전달 IP를 신뢰하고, 나머지 peer의 전달 헤더는 무시한다. IPv4는 /32, IPv6는 /64로 집계하며 mapped IPv4를 정규화한다. HTTP에서는 Secure/HttpOnly/host-only/SameSite 쿠키와 검증된 프록시의 헤더 덮어쓰기를 추가해야 한다. 현재 이 모듈은 쿠키를 실제 발급하는 HTTP endpoint가 아니다.

`security.trial_chat`는 예약 → 공개 근거 준비 → 신뢰된 completion dispatcher → finished 상태 확인 → 근거 재검증 순서로 연결한다. 근거 준비/직렬화 실패는 실행 전 환불한다. 요청 취소 시에도 실제 읽기 thread가 종료될 때까지 예약 슬롯을 유지한 뒤 환불하여 반복 취소로 읽기 작업이 누적되지 않게 한다. IPC가 write()를 시도하기 전임을 증명하는 인코딩/연결 실패·취소만 환불한다. write() 시도 이후 예외/취소는 실행 여부를 추측해 환불하거나 슬롯을 반환하지 않는다. dispatcher가 실제 child 종료를 확인하고 상태를 정리해야 한다. 사용량의 remaining은 표시용 snapshot이며 실행 권한은 reserve transaction만 부여한다. HTTP 입력/본문 제한·Unix socket dispatcher·실제 프로세스 장애 복구·브라우저 메모리 전용 대화는 후속 연결이며, 이 내부 합성 테스트로 실제 서비스 완료를 주장하지 않는다.

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

목록/검색: GET `/api/public/documents?q=&cursor=&limit=10`은 승인 저장소의 문서ID 내림차순 후보만 검토한다. q는 제목·보관본문의 대소문자 무시 문자열 검색(최대120자), cursor는 서버가 발급한 불투명 이어보기 값, limit은1..20이다. 응답은 `{items:[{id,title,source_type,published_at,snippet}],next_cursor}`이며 snippet은 검증된 본문 앞부분/검색 주변 최대240자다. 전체 건수·비공개 후보수·관련자료는 반환하지 않는다. 검색 일치 검사도 본문/첨부 전체의 현재 승인 fingerprint 검증 뒤에 수행해, 변경된 비공개 본문에 따라 파일 검증 비용/상태가 달라지는 검색어 oracle을 막는다.

후보100개/파일·선택본문 읽기128MiB를 요청 예산으로 제한한다. 완료한 후보의 위치를 암호화해 전달하므로 앞100개가 검색불일치이거나 변경으로 제외되어도 뒤의 공개 결과를 계속 찾을 수 있다. 빈 items+next_cursor는 검색 완료0건이 아니다. 파일 읽기 예산 때문에 검증하지 못한 후보는 다음 범위에 남긴다. 첫 후보조차 완료할 수 없는 오류/예산은503이며 거짓0건으로 처리하지 않는다. 새 검색엔진/영속 검색 인덱스는 추가하지 않는다.

publication_metadata v2는 별도0600 SQLite 안에 cursor_key를 보관한다. 기존 v1은 명시 initialize 때만 ALTER/키생성/version2로 준비하며 요청 자동 변경은 없다. 재초기화는 기존 키를 유지한다. 설치된 cryptography50.0.2의 [Fernet 공식 API](https://cryptography.io/en/latest/fernet/)를 사용하고 진행위치·정규화검색어·버전의1024바이트 패딩 payload를 인증 암호화한다. 키는 서버 내부에만 있고 토큰의 생성시각은 Fernet 형식상 숨기지 않는다. 유효기간1시간, 검색어 재사용/변조/만료는400이며 처음부터 재검색한다. 키가 포함된 SQLite-aware 백업/복원을 요구하며 DB와 분리된 임의 키 파일·익명 요청별 영속 cursor 기록은 만들지 않는다. 초기화 누락은503이다.

목록 연결 검증: 관련 ASGI23검사·프론트308검사·TypeScript·318응답 계약 일치 통과. 101개 유효문서 중 마지막 검색일치 및 앞100개 변경+마지막 유효문서 도달, 파일 예산 중단 후보가 다음 페이지에 남음, 승인 재검사/철회/metadata·첨부 변경 제외, DB 불변을 확인했다. 키 초기화누락 거부/요청무변경·변조/다른검색어/만료400, SQLite-aware 백업 integrity와 별도 Python 프로세스에서 복원DB로 이어보기도 통과했다. Chrome1440/390px에 실제 ASGI 합성응답을 공급하여 목록 다음/이전→빈 중간 검색→다음 결과→본문→목록 복귀→완결0건→철회 재검증 제거를 확인했다. API28회 session/공용목록/문서뿐, uncaught0/미승인API0/가로overflow0. 탐색 중 취소된 요청4개는 CDP fixture 응답 취소로 처리했으며 모든 실제 화면 전이를 별도로 기다렸다. 실제 운영키/DB/Google/외부 공개 검증은 아니다.

공개 `/feed`는 검색 입력/URL q·cursor와 이전·다음 이동, 검증된 미리보기→`/doc/:id` 링크를 제공한다. 로딩·빈목록·검색0건·오류 재시도·정상목록을 구별하며 재검증 중/실패에는 이전 결과를 숨긴다. 공개 본문에서 목록으로 돌아갈 수 있다. 기존 개인 피드/검색/저장 API를 마운트하지 않는다. 실제 자료 승인/피드 전체·인용/RAG 연결과 외부 rate limit은 별도 후속이다.

공용 GET `/api/public/documents/{doc_id}`는 명시적으로 승인한 공개 투영만 반환한다. id/title/source_type/url/published_at/content/content_kind/attachments가 전부이며 개인 태그·메모·작업·연관자료는 없다. content는 저장된 markdown 우선, 없으면 raw_content다. 저장된 가공 본문일 수 있으므로 UI는 '보관된 본문'으로 표시하고 원문 그대로라고 보장하지 않는다. 출처 종류 자체는 공개 권한의 근거가 아니다.

운영자는 GET `/api/operator/publications/{doc_id}/preview`로 문서/첨부 목록/fingerprint/현재 version과 보호된 attachment_previews URL을 받는다. GET `/api/operator/publications/{doc_id}/preview/{fingerprint}/attachments/{attachment_id}`로 실제 파일을 검토한다. POST approve는 fingerprint/expected_version/rights_basis 및 personal_data_excluded=true를 요구한다. POST revoke는 expected_version을 받는다. 경로 앞부분은 동일한 `/api/operator/publications/{doc_id}`이며 회원은 운영자 경로에 접근할 수 없다. 기존 세션 역할과 Origin/CSRF를 검사하고 버전 충돌은409로 재검토를 요구한다. 운영자 검토 UI는 아직 없다.

EXPLORER_PUBLICATION_DB는 업무 DB와 다른 절대경로의 명시적 PublicationStore.initialize 대상이다. 요청/import 자동 초기화는 없고 누락/장애는503이다. 배포 시 영속 볼륨과 SQLite-aware 백업/복원 범위에 포함해야 하며 현재 운영 환경에는 초기화/연결하지 않았다. 테이블은 publication_metadata(v2, cursor_key 포함)와 현재 publications 결정이며 과거 본문/개정 이력 저장은 제공하지 않는다.

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


## 익명 채팅 HTTP 계약 (구현 중)

- `GET /api/public/chat/session`: `{remaining:int, limit:int, csrf_token:string}`. 익명 서명 쿠키가 없거나 무효이면 새로 발급한다. host-only Secure/HttpOnly/SameSite=Lax/Path=/, 30일. Google 로그인 설정과 독립이다.
- `POST /api/public/chat`: `X-CSRF-Token`과 정확한 Origin·유효 익명 쿠키 필수. 본문 `{question:string, history:[{role:"user"|"assistant",content:string}], search_query?:string, document_ids?:number[]}`. question1..4000자/12KiB, history 최대4개·각16KiB, search_query 최대120자, 문서 최대4개 양의 정수/중복 금지. history는 모델 문맥용 메모리 데이터이며 저장하지 않는다. search_query 생략 시 question의 앞120자로 승인 문서 문자열 검색한다.
- POST 전체 JSON body는96KiB 이내이며 JSON parsing 전에 실제 수신 bytes를 제한한다. 응답 `{answer:string, citations:[{id:string,title:string,url:string}], partial:boolean, remaining:int}`. 답변은 plain text, 인용 링크는 서버만 생성한다.
- 실패는 고정 문구(입력 원문/Pydantic input/공급자 예외 없음): 잘못된 입력422, 본문초과413, 신원/CSRF403, 한도429, 근거없음404, 근거변경409, 설정/실행불가503. no-store/no-referrer 적용, access log에서는 두 채팅 경로의 query를 제거한다.
- `EXPLORER_TRIAL_SECRET_FILE`은 명시적32-byte0600 키 파일, `EXPLORER_TRIAL_DB`는 사전 초기화된 별도 DB, `EXPLORER_TRIAL_NETWORK_DAY_LIMIT`/`EXPLORER_TRIAL_GLOBAL_DAY_LIMIT`/`EXPLORER_TRIAL_MAX_IN_FLIGHT`는 필수 정수 정책이다. `EXPLORER_PUBLIC_ORIGIN`은 HTTPS origin. `EXPLORER_TRIAL_TRUSTED_PROXIES`는 선택 comma-separated CIDR이며 기본 비신뢰. 명시 신뢰 peer에만 `X-Explorer-Client-IP`를 사용한다. 실제 gateway에서 사용자 헤더 제거/덮어쓰기 검증 전 활성화하지 않는다.
- `EXPLORER_PUBLIC_CHAT_SOCKET`은 절대 Unix socket 경로, `EXPLORER_PUBLIC_CHAT_TOKEN_FILE`은64hex0600 IPC capability 파일이다. API에는 Docker socket/공급자 인증을 제공하지 않는다. IPC newline JSON v1 request는 token/operation=complete/reservation_id/question/context/history, 최대160KiB. 응답은 version/status=complete/reservation_id/answer/citation_ids, 최대128KiB, 190초 deadline/no retry. dispatcher가 quota의 mark_started True인 경우에만 실행하고 실제 child 종료 뒤 finish한다. Unix socket/DB는 동일 Linux filesystem 안에서 공유해야 하며 macOS↔Linux SQLite WAL 공유는 허용하지 않는다.
- 기능은 public 경계의 정확한 두 route에만 독립 trial 정책을 적용한다. 설정·실제 dispatcher 준비 전503이며 Google/유료 API fallback은 없다. 실제 CLI/프록시/브라우저 비저장 검증 전 공개 완료가 아니다.


## 공개 체험 채팅 화면 계약

공개 `/chat`은 기존 개인 ChatPage를 마운트하지 않고 전용 `PublicTrialChatPage`를 사용한다. `/feed`와 공개 `/doc/:id`에서 체험 채팅으로 이동할 수 있고 문서의 버튼은 `/chat?doc=<id>`만 전달한다. 질문/답변을 URL·route state·browser storage에 넣지 않는다. 질문 q 프리필은 읽지 않는다. 계정 scope 변경 시 질문 draft/문맥 선택/대화 메모리 모두 초기화한다.

자료 선택은 기존 공개 문서 목록 API·검색·cursor를 사용한다. 문서 하나 이상 최대4개를 선택해야 질문을 보낼 수 있으며, URL로 받은 id도 공개 문서 조회로 확인한 다음 선택한다. 검색어는 자료 찾기용 별도 입력이며 search/cursor URL 파라미터로 탐색 상태를 관리한다. 질문 자연어를 자동 검색어로 쓰지 않는다. 선택 문서 id와 명시 검색어(없으면 빈 문자열)를 POST로 전달한다. 실제 승인/변경 검증은 서버가 다시 수행한다. 표시되지 않는 다른 페이지의 선택도 제목/해제 버튼으로 확인할 수 있어야 한다.

- Empty: 공개 자료 없음/검색0건/아직 질문 없음 각각 구분. 계속 검색 가능한 빈 cursor 페이지는 다음 버튼 유지. 선택 없이 보내기 비활성.
- Loading: 자료/체험 세션 준비 중 상태 표시, 제출 중 중복 입력·자료 변경 차단. 화면 이탈/초기화는 취소하고 늦은 답변을 버린다.
- Partial: 제한된 문맥으로 만든 답변에 부분 근거 안내. 답변 본문은 plain text, 검증된 `/doc/<positive id>` 인용만 링크.
- Error: 자료 조회·체험 세션 실패·질문 실패를 구분하고 고정 문구/명시 재시도. 실패한 질문 draft는 유지하되 자동 재전송 금지. 변경/철회된 자료로 실패하면 선택 재검토를 안내한다.
- Ideal: 선택 근거, 질문/답변, 인용, 남은 체험 횟수. 대화가 새로고침/화면 이탈 시 사라짐을 표시. 초기화는 대화만 지우며 횟수 복원을 암시하지 않는다.

횟수 소진은 추가 전송을 막고 Google 로그인 진입을 제공하되 로그인만으로 현재 체험 횟수가 초기화되거나 미구현 회원 무제한 채팅을 사용할 수 있다고 약속하지 않는다. 공급자 측 보존과 서비스 대화 기록 비저장은 구분한다. 현재 UI 준비는 실제 dispatcher·모델 호출·공개 서비스 완료가 아니다.


### 회원 운용 원칙: 소유권 준비

`/portfolio/principles` 동선은 회원의 원문·확인된 규칙·참고 원칙을 저장/조회/수정/삭제한다. 기존 개인 portfolio_principles와 전역 알림 jobs를 공유하지 않고 member_portfolio_principles를 회원 portfolio group FK로 분리한다. 회원 ID는 인증 principal에서만 받으며 group/id를 입력받아 소유자를 바꾸지 않는다. 기존 validate/describe 규칙 함수를 재사용한다. 초기화는 배포 시 명시적으로 수행하며 GET/요청에서 스키마를 변경하지 않는다. 운영 DB는 아직 미이관이다.

API는 `/api/member/portfolio/principles` GET/POST, `/{principle_id}` PUT/PATCH/DELETE로 계획한다. 본인 범위 SQL 안에서 수정·삭제하며 없는 항목과 타인 항목은 동일404. 사용자 데이터가 검증오류에 반사되지 않도록 기존 MemberRoute를 사용한다. 회원당 최대100원칙, 본문20000자·규칙20개·참고60개(각500자), 입력 owner/group 키 금지. 읽기는 부작용 없이 기존 empty 회원을 유지한다.

UI 상태: Empty는 아직 원칙없음, Loading은 skeleton, Error는 재시도/입력보존, Partial은 저장된 원칙과 아직 연결되지 않은 해석·평가·알림 상태를 구분, Ideal은 본인 원문/확인규칙/참고목록과 수정·삭제. 문장→규칙 LLM parse, 본인 원장만 사용하는 평가, 알림수신자 및 scheduler 연결은 별도 후속이며 CRUD 준비를 전체 원칙기능 완료로 표시하지 않는다. 개인용 모델/텔레그램을 회원 요청에 암묵적으로 호출하지 않는다.

회원 원칙 평가 GET `/api/member/portfolio/principles/state`는 같은 readonly transaction의 회원 원칙과 해당 group의 원장만 사용한다. 전역 current/alert/cache/LLM을 호출하지 않고 기존 순수 violations를 재사용한다. 규칙별 evaluated/partial/unavailable/not_applicable과 이유를 반환하며 partial/unavailable을 위반없음으로 표시하지 않는다. 현재 평가 연결은 보유수·보유기간·개별수익률/일변화·현재비중/현금비중이다. 진입비중·누적손실의 역사적 평가, 공통변수는 입력 완전성/공개근거 검토 전 unavailable이며 후속 범위다. 고점복합규칙의 연결 기준은 아래와 같다. 시세가 없는 보유종목이 있으면 취득가를 평가금액으로 대체해 비중을 판정하지 않는다. 알림상태를 읽거나 쓰지 않고 발송도 하지 않는다.

회원 원칙 화면은 `/portfolio/principles`에서 본인 원문·수치규칙·참고목록의 추가/수정/삭제와 평가 상태를 제공한다. 자동 문장해석이 연결되기 전에는 직접 확인한 수치규칙/참고원칙을 입력하며 자동해석을 흉내 내지 않는다. 허용 규칙·값 범위는 회원 metadata GET `/api/member/portfolio/principles/rules`에서 기존 RULES 정의로 제공한다. 저장 실패 시 편집 내용을 유지하고 삭제는 확인 후 실행한다. 세션/역할 변경 시 화면과 임시입력을 버린다. 평가불가·부분평가·대상없음과 위반없음을 구분하고 알림이 아직 발송되지 않는다는 사실을 명시한다. 포트폴리오↔원칙 왕복 링크와 Google 로그인 return_to를 유지한다.

고점 복합규칙은 본인 보유만 `load_prices`로 읽고 기존 `violations/exit_signals`에 전달한다. 시장구분(KOSPI/KOSDAQ/KOSDAQ GLOBAL/KONEX), 유한 양수 시세, 편입 전252개 저장관측 및 편입 후관측, 평가 종가일치가 있는 종목만 실행한다. 이 기준은 기존252관측 어깨탐색과50관측 이동평균의 입력범위를 확보하며 거래소 캘린더상의 무결한 전체이력을 보장하지 않는다. 부족종목은 실행전에 제외하고 부분/평가불가를 표시한다. 원칙별 고점규칙 입력 미연결 항목은 이 경로로 대체하며 다른 역사적평가·공통노출·parse·알림 잔여는 유지한다.

고점 시세 로더 호출 전에 동일400일 조회범위의 저장 원자료를 검사한다. NULL·0·음수·비수치 종가가 있으면 해당 종목을 제외한다. 따라서 로더의 양수 필터가 잘못된 저장 관측을 숨긴 채 평가하지 않는다.

### 한국 섹터 공개 시장 상세

`GET /api/spine/industry/{sector}/market`은 검토된 SEED 섹터만 같은 readonly snapshot에서 지도·개별 종목 RS·시총비중·벤치마크/코스피 시계열을 계산한다. 개인 detail cache/내러티브/AI 개괄/문서/팔로우/data_links/Peer runtime을 읽지 않는다. 구성종목은 기존 분류·시총 기준을 재사용한다. 응답은 KrSectorMarketResponse로 한정하며 미등록 또는 시장 자료 없는 섹터는404. 기존 상세 API와 개인 UI는 유지한다. 공개 화면은 Loading/Empty/Error/Partial/Ideal과 미연결 개인 기능을 구분하고, 섹터→기업요약→재무 왕복 동선으로 연결한다. 해당 UI 연결과 공개 승인 요약·문서 확장은 별도 진행 중이다.

공개 KR 화면은 기존 IndexCard/RsCard/SectorStocksTab의 시장 데이터 표현만 재사용한다. 개인 hook이 필요한 상세·요약·조사 컴포넌트를 마운트하지 않는다. `map_query`→`sector_query`→`summary_query`는 내부 경로에 붙이는 query로만 사용하고 외부 URL로 이동하지 않는다. 기업 요약의 시세 API는 등록회사 여부를 확인한 뒤 최신1500개 저장 OHLCV/시총을 반환한다(미등록404·등록/시세없음200). 불완전 OHLC는 캔들에서 제외하고 결측을 표시한다. 재무 미리보기는 기존 저장재무/회계범위를 그대로 쓰며 개인 KPI/조사 profile을 대신 호출하지 않는다. 산업 해설·Peer·사업 설명·관련 문서/AI 분석의 공개 연결은 미완으로 표시한다.

구성종목 수익률 표시 수정: 기존 ret_1m/ret_12m이 RS 기준7/91일 수익률을 재사용하던 오류를30/365일 비교로 수정했다. RS 자체의91/7일 계산과 순위는 유지한다. 거래일 달력 완전성/정확한 해당일 가격을 보장하지 않으며 기존 snapshot의 해당일 이하 저장값 선택을 따른다.

### 기업에서 공개 문서 검색 및 복귀

기업 요약에서 회사명으로 승인된 제목·본문을 검색한다. 기업과의 검증된 관계나 추천을 뜻하지 않으며 개인 관계 테이블을 조회하지 않는다. `/feed`의 `company_return`에는 내부 기업 요약 URL만 허용한다. 검색 수정·이어보기 후에도 기업의 시세 기간/섹터/지도 조건을 보존한다. 문서의 `return_to`는 내부 `/feed`만 허용하고 검색어/cursor/검증된 기업 복귀 조건을 재구성한다. 새로고침·404·철회·오류에서도 복귀 링크를 제공한다. 결과가 없는 경우는 검색 결과 없음으로 표시하고 재검증/오류에는 기존 결과를 숨긴다.
