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

frontend/api/auth.ts는 생성된 응답 계약을 사용하는 session/logout 호출과 Google로그인 URL을 제공한다. 로그인 버튼·계정별 UI gating은 아직 연결하지 않는다. 기존API의 인증·소유권 경계가 적용된 것은 아니므로 이 로그인만으로 외부 공개하지 않는다.

## 공개 요청 진입 경계

`EXPLORER_ACCESS_MODE=private|public`을 import 시 검증한다. 기본 private은 기존 비공개 실행을 유지하며 공개에 적합하지 않다. public은 `security.access_boundary`의 ASGI 경계를 설치한다. 실제 공개 배포의 사전 검사에서 public 설정을 확인해야 하며, 이 변경은 Tunnel이나 운영 설정을 활성화하지 않는다.

현재 허용 목록은 `GET /api/health`와 기존 auth의 session/start/callback/logout 네 경로뿐이다. 메서드와 유효 route 경로를 함께 비교하고, 미분류 API·정적 media·문서 UI·WebSocket은 차단한다. 포함된 router의 prefix를 반영하며 등록하지 않은 정책·중복 정책 경로·알 수 없는 정책·public 쓰기 분류를 거부한다. 신규 라우트가 자동으로 공개되지 않는다. auth 경로는 기존 state/nonce/세션/CSRF 검사를 계속 수행한다.

member/operator 정책은 기존 IdentityStore를 매 요청 조회해 만료·폐기·역할 변경·비활성화를 반영하고 `request.state.principal`에 검증된 User를 전달한다. identity 헤더는 사용하지 않는다. 보호된 쓰기는 정확한 HTTPS Origin과 세션별 CSRF가 필요하다. 저장소 장애는 내용 없는503, 인증 실패401, 권한/CSRF 실패403, 미분류404다. 응답과 오류는 no-store이며 공용 캐시 최적화는 별도 계약 뒤에 한다. 응답 전 예외는 고정500으로 처리하며 이미 시작한 스트림에 예외 내용을 덧붙이지 않는다.

이 단계는 기존 개인 API를 member로 분류하지 않는다. 해당 저장소·목록·ID 상세·파일·파생 결과의 본인 소유권과 배경 작업 주체 전달이 검증된 뒤에만 허용 목록에 넣는다. 전체 시장 화면/회원별 포트폴리오/익명 비저장 채팅은 아직 공개되지 않았으며, 임시 차단 상태를 공개 기능 완료로 판정하지 않는다.

합성 ASGI 검사와 임시 identity SQLite로 두 회원/운영자 구별, 위조 헤더, 만료/폐기/비활성·역할 변경, 쓰기 Origin/CSRF, 실제 앱 등록경로의 미분류 차단, 정적 파일/메서드/WebSocket 우회, include prefix/parameter, 신규·중복 경로, 예외 비노출을 검사한다. 기존 Google HTTP 흐름 검사는 별도로 유지한다. 실제 Google 로그인·회원별 업무 데이터 격리·외부 프록시·공개 설정 누락 사전검사는 이후 수용 대상이다.
