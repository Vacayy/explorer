# 프런트엔드 디자인 시스템 점검

2026-09-10 · 상태: 현행 코드 감사 완료, 기반 정비와 홈·피드 적용 완료, 다른 페이지군 이행은 남음. 2026-06-15 검토를 현재 코드 기준으로 갱신했다. 실행 기준은 [DESIGN_SYSTEM](DESIGN_SYSTEM.md), 구조는 [SYSTEM](SYSTEM.md). 별도 개편 spec을 계속 추가하지 않고 이 문서에서 감사·이행 범위를 관리한다.

## 2026-09-10 통합안 구현 현황

승인된 기반 정비와 홈·피드 파일럿을 적용했다(D-152). IBM Plex Sans/KR, 역할별 타입, 단색 테마, Card/Button/Input, PageLayout/PageHeader/SplitWorkspace, 대비 브리핑, 연속 피드, 도크 글래스를 구현했다. 홈·ChartCard의 flex-row/grid 가정 충돌과 홈·피드 출처/시각의 작은 글자 일부도 정리했다.

검증: FE 타입·프로덕션 빌드, 실제 데이터 소스/시스템 필터·펼침·밀도·페이지 이동·문서 검색 호환·빈 상태/오류 복구, 지수 캐러셀 확인. 7개 라우트×2개 폭에서 가로 넘침 표본 점검. 마지막 브리핑 재조회는 로컬 백엔드 지연(직접 GET 10초 초과)이 있어 날짜·대비·스크롤 최종 검증은 명시적 UI fixture로 분리해 통과했다. CDP로 한글 제목의 실제 IBM Plex Sans KR 렌더링도 확인했다. 전체 백엔드 가용성·접근성 검증을 뜻하지 않는다. 기존 대형 청크 경고는 남는다.

D-153 후속: Home을 상단 시장/피드 전환, 전체 폭 시장 그리드, 소스 목록 + 원문 리더로 변경했다. 전체 소스 집계 API와 개별 소스 필터, 저장 요약/없음, 모바일 복귀, 모드/선택/페이지 URL 및 읽기 위치를 적용했다. Markdown의 기본 text-sm이 읽기 토큰을 덮던 문제는 리더에서 명시적 길이 토큰으로 해소했다. 기존 `/feed`는 유지한다. 검증 자료 `logs/home-reader/`.

다음: 기업/산업/수출입의 분석형 → 리포트/원문의 읽기형 → 대화 앱형. 남은 8–11px 글씨, 미이행 CardHeader, 소형 터치 대상·포털·긴 제목·모바일 Safari와 시각 회귀를 점검한다. 전역 atom 개선을 전체 페이지 개편 완료로 보고하지 않는다. 아래 집계는 변경 전 감사 기준선이다.

## 상세 화면 후속 — 승인된 구현 계약

[상세 읽기 HTML 기획안](prototypes/detail-reading-workspace.html): 문서와 내러티브의 실제 구조를 확인하고, 같은 읽기 레이아웃으로 묶는 안이다. 사용자가 상세 이행을 승인했다. 문서 상세·복귀 동선과 내러티브 상세·버전 화면을 같은 DetailLayout으로 적용한다.

현재 단절: DocPage는 PageContainer·작은 메타·요약/이미지/본문 카드가 분리되고 `navigate(-1)` 복귀만 사용한다. NarrativePage는 별도 상단 액션, 본문 아래 이력/질문/시나리오/인과/근거/관련 항목이 길게 이어진다. 홈 원문 리더와 글 표시 방식도 달라진다. 문서의 원시 텍스트/Markdown 구분은 DocPage의 원문 보존 규칙을 공통 DocumentBody로 추출했다. Telegram·블로그 등은 저장 텍스트를 보존하고 YouTube/canon/note 및 저장 요약은 Markdown으로 표시한다. 피드와 상세가 이 규칙을 공유하며 영상 본문은 AI 정리본일 수 있음을 표시한다.

구현: PageLayout 위에 DetailLayout(context, header, actions, navigation, body, aside, related) 조합. 전체 페이지 상세부터 이행하고, 좁은 오른쪽 추가 패널은 기본으로 쓰지 않는다. 넓은 화면 본문 680–760px + 보조 맥락 220px, 모바일은 보조 영역 아래 배치. 본문 14px·페이지 제목 24px·소제목 18/16px·캡션 12px. 상세의 팔로우 레일은 독립 상태로 기본 접힘이며 수동 토글을 유지한다.

- 복귀 계약: canonical `/doc/:id`, `/narrative?topic=...`, 버전 URL 보존. 내부 이동 state에는 출발 URL·선택·목록 페이지·이전 history 위치를 전달하고, 스크롤·복귀 링크를 저장하고 탭 단위 sessionStorage의 최대 100개 UI 상태로 복원한다. 원문 데이터는 저장하지 않는다. 직접 링크/새 탭은 출처·목록 fallback을 제공한다. `navigate(-1)`만으로 외부 페이지에 나가지 않게 한다. 스크롤/포커스는 실제 복귀 완료 후 복원하며 캐시가 없으면 안전한 시작 위치로 간다.
- 문서: 출처·게시/수집 시각, 원문/저장 요약, 첨부, 저장·원문·자료 첨부 대화. 모델명/추가 파보기는 보조 정보로 내린다. 원문 없음·요약 없음 명시.
- 내러티브: AI 해석 표기 + 현재 서사/실제 연결 근거/저장 변경 이력. 질문·파급 시나리오·인과 흐름은 보조 탐구로 묶고, 실제 자료 연결 이상의 문장별 입증을 주장하지 않는다. 저장되지 않은 핵심결론·기대변화 요약을 화면이 새로 만들지 않는다.
- 실행 비용 경계: NarrativePage에는 오래된 저장본 진입 시 자동 compute 경로가 있다. 레이아웃 이행과 별도로, 읽기 진입은 저장본 조회·새 근거 알림, 생성은 명시적 ‘갱신’으로 분리하는 정책을 제안한다. 기존 동작은 현재 변경하지 않았다. SourceDeepDive 역시 대화/읽기와 별개로 생성 작업임을 구분한다.
- 완료: 문서 상세+복귀, 내러티브의 현재 해석/근거/변경 이력/추가 탐구, 버전 상세 및 v URL. 남은 이행: 출처·인물·기업 상세. 빠른 근거 오버레이는 이후 필요성이 확인되면 같은 본문 컴포넌트로 추가하고 중첩하지 않는다.

## 판단

디자인 시스템 문서, semantic 색상 토큰, shadcn/Radix atom, shared 조합 컴포넌트는 이미 있다. 문제는 이들이 하나의 제품 규칙으로 연결되어 있지 않다는 점이다. **기본 atom의 실제 계약과 화면의 가정이 다르고, 역할별 글자 크기·밀도·모바일 상호작용을 화면마다 재정의하고 있다.**

공통 UI 층의 전면 정비를 권고한다. React·라우팅·API·데이터·수집 및 분석 로직은 유지하면서, 타이포그래피 → atom 계약 → 조합 컴포넌트 → 페이지 템플릿 순서로 교체하는 범위다. IBM 서체만 바꾸거나 shadcn preset을 일괄 재설치하는 것으로 해결되지 않는다.

이번에 만든 홈·피드에도 10~11px 메타데이터와 atom 스타일의 개별 보정이 들어갔다. 당시 홈의 두 열은 D-153에서 모드 전환으로 대체했다. 목록·리더의 독립 스크롤을 포함해도 전체 제품의 시각 시스템 정비 완료를 뜻하지 않는다.

## 감사 범위와 한계

- 프런트엔드 전체 TS/TSX 정적 집계. AST는 JSX 태그·속성을 확인했고, 크기/색 클래스 수는 텍스트 출현 횟수다. 모든 출현을 접근성 위반으로 판정하지 않는다. 라우트 미등록 파일도 포함한다.
- `/home`, `/feed`, `/follow`, `/follow/trade`, `/chat`, `/analyze/000660/financials`, `/narrative`: 1440×1000 / 390×1000 Chromium 화면과 computed style 점검. 스크린샷 14개. 이 표본에서는 body 가로 넘침이 없었다. 모바일 Safari·전체 모달/빈 상태/장문·모든 라우트·다크 모드 전수검사는 아직 아니다.
- 브라우저의 API POST 차단 장치를 걸고 읽기만 점검했다. 해당 표본의 실제 POST 시도는 0건.
- 실행 자료·재현 도구: `logs/design-system-audit/inventory.cjs`, `inventory.json`, `browser.cjs`, `browser.json`, 스크린샷. 버전 관리에는 개인 소스/자료를 넣지 않는다.

## 규모: 있는 것과 빠진 것

| 항목 | 실측 | 해석 |
|---|---:|---|
| TS/TSX 파일 | 217개, 그중 TSX 170개 | 캐러셀 조합 컴포넌트 추가 후 집계 |
| ui atom / shared 모듈 | 35 / 26개 | 기반은 이미 존재 |
| ui를 직접 import하는 파일 | 112개 | atom을 쓰지 않는 시스템은 아님 |
| shared를 import하는 파일 | 68개 | 조합 계층도 존재하지만 적용 범위 불균일 |
| 8~11px arbitrary text 클래스 | 458회 / 81파일 | 보조 정보가 지나치게 작은 크기로 굳어 있음 |
| 전체 arbitrary px text 클래스 | 493회 / 88파일 | `body`, `caption`, `metric` 같은 역할별 타입 토큰 부재 |
| CardHeader 중 flex-row만 주는 사용처 | 22 / 52개, 17파일 | 기본 grid와 소비자 flex 가정 불일치 후보 |
| raw button (ui 외부) | 38개 / 19파일 | raw button 자체가 잘못은 아니지만 저장소의 atom 공통화 규칙과 불일치 |
| JSX Button에 높이/여백/크기 등 개별 보정 | 49개 / 32파일 | 정확한 예외 목록과 size/density 계약 필요 |
| 6자리 hex 직접 사용 (ui 외부 TS/TSX) | 78회 / 13파일 | CSS 토큰 정의는 집계에서 제외, 차트 설정·주석 등도 포함 |
| 명시적 Tailwind 색상 팔레트 클래스 | 78회 / 15파일 | 상태 색/차트 색의 semantic 경로 이탈 후보 |

## 우선순위별 근거

### P1 · atom과 조합 컴포넌트의 계약 불일치

- `frontend/src/components/ui/card.tsx:28` — CardHeader는 `display:grid`.
- `frontend/src/components/shared/ChartCard.tsx:18` — `flex-row`를 주지만 `flex`가 없다. flex 방향 지정이 grid를 flex로 바꾸지 않는다.
- `frontend/src/components/home/UsBriefingSection.tsx:55` — 같은 가정. 제목/설명/날짜 액션이 별도 행으로 배치되어 헤더가 커진다.
- `frontend/src/components/ui/card.tsx:15` — 기본 `rounded-4xl`, `shadow-md`, 외부 세로 패딩·자식 gap 각각 24px. 문서는 `rounded-xl`을 규정한다. 실제 radius는 현재 토큰 기준 31.2px다.
- `frontend/components.json:3` — `radix-luma` preset. 이 기본 외형과 문서의 분석 도구 외형이 일치하지 않는다. preset을 언제 바꿨는지는 이번 감사에서 확인하지 않았다.

조치: Header(title/description/action), Card(surface/density), Toolbar(wrap/overflow) 계약을 먼저 확정한다. 라이브러리 설치본을 각 화면에서 덮어쓰는 방식은 줄이고, 프로젝트가 소유하는 스타일 기본값과 업그레이드 규칙을 명시한다. 현재 `ui 수정 금지`를 기계적으로 유지하면서 예외를 호출부로 밀어내면 같은 문제가 반복된다. 이는 다음 단계의 규칙 변경 제안이며 이번 감사에서 atom을 일괄 수정하지 않았다.

### P1 · 한글 서체와 역할별 타입 스케일이 통제되지 않음

- `frontend/src/index.css:4` — 로드하는 웹폰트는 Inter.
- `frontend/src/index.css:15` — Noto Sans KR은 fallback 이름에 있지만 로드 설정은 없다.
- DevTools `CSS.getPlatformFontsForNode`로 피드의 한·영 혼합 제목을 실측: 영문은 웹폰트 Inter, 한글은 로컬 Apple SD Gothic Neo. 이 결과는 이번 macOS 환경에 한정하며 다른 OS에서는 다른 fallback을 사용할 수 있다.
- `frontend/src/components/shared/SegmentTabs.tsx:31` — 13px를 직접 지정. 홈/피드/팔로우 등에서는 9·10·11px를 따로 지정한다.
- 큰 카드·넓은 패딩과 작은 글자를 함께 써서, 화면은 넓게 차지하면서 읽을 정보는 작게 보인다.

조치: IBM Plex Sans + IBM Plex Sans KR을 명시적으로 로드하고, 본문/제목/라벨/보조 정보/수치 역할을 토큰으로 만든다. 단순 전역 폰트 교체 후 모든 px를 키우는 식으로 진행하지 않는다.

### P1 · 모바일은 재배치와 조작 방식까지 정의해야 함

- `frontend/src/components/follow/FollowPage.tsx:327` · `:339` — 수집/노출 제어가 `opacity-0 group-hover:opacity-100`. 터치에서 조작을 발견하기 어렵고, 키보드 포커스 시 드러내는 규칙도 없다.
- `frontend/src/components/follow/FollowPage.tsx:338` — 노출 토글 18×18px. 크기만으로 표준 위반을 단정하지 않더라도 자주 쓰는 조작의 제품 기본값으로는 작다.
- `frontend/src/components/follow/FollowPage.tsx:362` — 모바일 입력창 실측 12px, 28px 높이. placeholder 외 연결된 label도 없다.
- `frontend/src/components/follow/TradePage.tsx:56` · `:58` — 좁은 화면에 품목 목록과 상세를 단순 세로 스택, 목록 자체는 최대 70vh. 첫 화면 대부분이 목록이며 상세는 아래로 밀린다. 모바일에서는 선택 품목 요약 + Sheet/검색 선택기로 바꾸는 편이 적절하다.
- `frontend/src/components/shared/ProposalPanel.tsx:29` — 기본 70vh 내부 스크롤이 여러 화면에 퍼진다. 홈의 독립 패널 안에 다시 내부 스크롤이 들어갈 수 있다.

조치: 문서형/분할 작업형/목록-상세형 3개 화면 계약을 두고 모바일 변환을 각각 정한다. hover 액션은 터치에서 메뉴 버튼으로 제공하고 focus-within도 지원한다. 데이터 표는 무조건 카드로 바꾸기보다 중요 열 유지/상세 확장/컨테이너 스크롤 중 용도에 맞게 선택한다.

### P1 · 접근성 기본값이 조합 단계에서 빠짐

- `frontend/src/components/follow/FollowPage.tsx:292` — 출처로 이동하는 클릭 가능한 div, 기본 키보드 내비게이션 없음. 내비게이션은 Link, 별도 토글은 형제 버튼으로 구성해야 한다.
- `frontend/src/components/follow/FollowPage.tsx:362` — 입력 라벨 누락.
- `frontend/src/components/ui/card.tsx:40` — CardTitle은 div. 제목의 시각 스타일을 적용해도 heading 의미가 생기지는 않는다. 서비스 Heading/SectionTitle에서 레벨을 명시해야 한다.
- `frontend/src/index.css:225` — 모든 요소에 150ms transition을 주지만 해당 전역 규칙에는 reduced-motion 분기가 없다. 개별 atom에도 `transition-all`이 있다(`ui/button.tsx:8`).

표본의 24px 미만 컨트롤 수는 자동 스캔의 검토 후보일 뿐, 간격·예외·실제 타깃 영역까지 검증한 WCAG 판정이 아니다.

### P2 · 색상 토큰은 있으나 타입·밀도·차트 적용은 불완전

- `frontend/src/index.css:14` — semantic 테마, 주가 up/down, 사실/해석 토큰은 유지할 기반.
- `frontend/src/components/business/BusinessPage.tsx:23` — 차트 배열에 hex 직접 사용.
- `frontend/src/components/analyze/ComparePage.tsx:214` — emerald 팔레트 직접 지정.
- `frontend/src/utils/format.ts:101` · `:112` — KST 표시는 timezone 없는 UTC 문자열을 정규화하지만 상대 시간은 직접 Date로 파싱한다. 시간·숫자·단위·결측값의 의미를 표시 컴포넌트와 공통 formatter로 묶어야 한다.

색상은 브랜드·상승하락·사실/해석의 의미를 보존하고, 장식보다 정보 구분에 쓴다. 글자 크기·행간·모서리·표면·control 높이·chart label까지 같은 semantic 계약을 소비하도록 확장한다.

### P1 · 문서 규칙을 검증하는 실행 장치가 없음

- `frontend/package.json:9` — lint 스크립트는 있지만 실제 `npm run lint`는 ESLint config 없음으로 실패한다.
- 이번 인벤토리에서 프런트엔드 컴포넌트 story/test 및 시각 회귀 설정을 찾지 못했다. 현재 로컬 브라우저 스크립트는 검증 증거이지 지속 실행되는 회귀 체계가 아니다.
- `docs/DESIGN_SYSTEM.md`의 규칙과 코드 기본값이 달라도 빌드는 성공한다. 타입 검사와 빌드만으로 디자인 일관성을 확인할 수 없다.

조치: 실제 실행되는 lint + 허용 예외 목록 + 컴포넌트 상태 갤러리 + 주요 화면 시각 회귀를 기준선으로 만든다. 기존 위반을 한꺼번에 막기보다 새 위반 유입을 차단하고 점진적으로 줄인다.

## 제안하는 IBM 기반 타이포그래피

IBM Plex는 한국어용 Sans KR을 제공한다([IBM 공식 Typeface](https://www.ibm.com/design/language/typography/typeface/), [공식 배포 저장소](https://github.com/IBM/plex)). Carbon도 정보 밀도가 높은 제품용과 표현 중심 화면의 타입 세트를 나눈다([Carbon type sets](https://carbondesignsystem.com/elements/typography/type-sets/)). 이를 참고하되 아래 수치는 **Explorer를 위한 제안값**이며 IBM 표준을 그대로 옮긴 값이 아니다.

- 일반 UI/영문·수치: IBM Plex Sans. 한글: IBM Plex Sans KR. 코드·티커 등 한정된 식별자에는 IBM Plex Mono 선택.
- 숫자 전체를 Mono로 강제하지 않는다. 일반 표의 숫자는 Sans + tabular-nums + 우측 정렬, 단위/결측/부호는 formatter 계약.
- 400/500/600 굵기부터, 한글 subset 및 로딩/레이아웃 이동을 실제 브라우저에서 검증. 라이선스 파일 보존. IBM 글꼴 도입이 Carbon 컴포넌트 전면 도입을 뜻하지 않는다.

| 역할 토큰(제안) | 크기 / 행간 | 용도 |
|---|---|---|
| page-title | 24 / 32px, 600 | 페이지 제목 |
| section-title | 18 / 26px, 600 | 브리핑·피드 등 구역 |
| card-title | 16 / 24px, 600 | 게시물·분석 카드 제목 |
| body-reading | 16 / 26px, 400 | 브리핑·문서·AI 답변 |
| body-ui | 14 / 20px, 400 | 목록·표·일반 UI |
| label | 13 / 18px, 500 | 필터·짧은 라벨 |
| caption | 12 / 18px, 400 | 시각·출처 등 보조 정보 |
| metric | 20 / 28px, 500 | 주요 시장 수치 |

제품 기본 읽기 경로에서 12px 미만을 쓰지 않는 방향을 권고한다. 차트의 조밀한 눈금 등은 별도 검증된 예외로 관리한다. 모바일 입력 텍스트는 16px, 주요 터치 조작은 44px 높이를 기본 후보로 삼는다. rem으로 구현하고 브라우저 확대·텍스트 확대에 대응한다.

## 이행 순서와 완료 기준

1. **기본 계약과 표본 화면**: IBM 서체/타입 토큰, Card/Header/Button/Field/Badge의 default·compact·disabled·loading·error·focus 상태. 모바일/데스크톱·라이트/다크·한글 장문 표본을 한 갤러리에서 비교한다. atom 원본 보호 규칙과 프로젝트 소유 스타일 규칙을 합의 가능한 단일 문서로 정리한다.
2. **공통 조합층**: SectionHeader, Toolbar, SourceIdentity, Timestamp, MetricValue, FeedPost, Empty/ErrorState. 슬롯으로 atom을 조합하고 각 화면이 radius·높이·폰트를 반복 덮어쓰지 않게 한다. 모든 JSX를 거대한 하나의 Page 컴포넌트 안에 숨기는 방식은 피한다.
3. **핵심 흐름 이관**: 홈/피드 → 원문/대화 → 팔로우/수출입/컨콜 → 기업 재무/차트. 기존 데이터·URL·상호작용 계약 보존. 홈은 지수 한 줄 캐러셀 + 좌우 독립 스크롤 유지.
4. **재발 방지**: lint 정상화, semantic 타입/색상 예외 목록, 키보드와 터치 경로, 360·390·768·1024·1440px 및 200% 확대 회귀 검사. 화면 가로 넘침뿐 아니라 중요 정보 접근·컨트롤 발견·글자 가독성을 확인한다.

전체 전환은 단계별로 진행하되, 각 단계의 공통 규칙을 끝까지 적용한다. 폰트만 바꾸고 화면별 보정을 남기는 중간 상태를 완료로 취급하지 않는다. 일정·비용 수치는 실제 표본 이관 전에는 확정하지 않는다.

## 이번 요청에서 실제 반영한 변경

시장 지수는 모든 폭에서 한 줄 캐러셀로 바꿨다. 초과하면 가로 스크롤·스냅·좌우 버튼으로 이동하며, 끝에서는 해당 버튼이 비활성화된다. 자동 회전은 없고 reduced-motion 설정을 따른다. `HorizontalCarousel`은 기존 Button과 네이티브 스크롤을 조합한 shared 컴포넌트다. 390·768·1080·1920px 한 줄/넘침/버튼 동작 검증을 통과했다.

그 외 전면 타이포그래피/atom/페이지 재설계는 위 제안과 감사에 포함되며 아직 적용하지 않았다.

상세 이행 검증: TypeScript·프로덕션 빌드, 격리 브라우저에서 피드 → 상세 → 새로고침 → 피드의 필터/페이지/스크롤 복원, 관련 문서 복귀, 직접 URL fallback, 원문/요약/없음, 내러티브 탭·버전 URL/새로고침/복귀, 390/768/1440px·다크·오류, 명시적 문서 첨부 대화 및 내러티브 버전 본문 대화 전달을 확인했다. 대화 API는 fixture로 검증해 실생성하지 않았다. `logs/detail/`에 검증 자료를 보존한다. 문서 조회 API가 수집 시각을 제공하지 않는 경우 게시 시각만 표시하며 임의로 채우지 않는다.
