# 저장됨 (Saved / Bookmarks) — 산출물 북마크

> 2026-07-28 기획. 목표: 기업 디테일·문서·내러티브·리포트 각 페이지를 저장해두고 언제든 다시.
> 배경: 앱에 "특정 산출물을 다시 찾아보게 고정"하는 원시타입 부재. 팔로우(엔티티 흐름 구독)와 성격이 다름.

## 현행 진입 (2026-09-10)

**현행(2026-11-05, 개편 4a)**: 저장됨은 피드 › 저장됨 `/feed/saved`(옛 `/follow/saved`는 리다이렉트). 머리 '저장됨 n건' + ⓘ(저장 방법), 유형 탭에 건수(`?kind=`), 목록 폭 980px, 메모는 있는 줄만 보이고 쓰기·저장 해제는 줄에 마우스를 올리면 나오는 '메모'·'×'(터치 기기는 항상), 메모 입력은 누른 줄에만 펼친다. 상단 바 인박스 시트(compact `SavedList`)는 그대로. 이하 옛 기록: Dock 관심목록의 기본 목적지는 `/follow/saved`이며 저장됨을 첫 탭으로 표시한다. 기존 관심 대상 관리 `/follow`는 유지한다. 스터디 기능은 [별도 단일 기획](study-mode.md) 단계이며 아직 저장 목록에 구현하지 않았다.

## 관통 원칙

1. **팔로우 ≠ 저장됨** — 팔로우=엔티티 *흐름 구독*(delta 스트림), 저장됨=특정 *아티팩트 북마크*(다시 찾기). 겹치지 않음.
2. **버전 고정** — 내러티브·리포트는 **보던 그 버전**을 저장(topic이 아니라 version id). 재방문 시 그때 본 그대로.
3. **가볍게** — 테이블 1개 + spine 라우터 1개. 폴더·태그 없음(MVP). 메모 한 줄만.
4. **어디서든 저장, 두 곳에서 열람** — 4개 페이지에 북마크 토글 + 헤더 상시 아이콘(Sheet 빠른 열람) + 팔로우 '저장됨' 서브탭(전체 목록).

## 데이터 모델

`saved_items` (신규):

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INTEGER PK | |
| kind | TEXT | `company` \| `doc` \| `narrative` \| `report` \| `chat`(대화 답변, 2026-11-05 개편 4j) |
| ref | TEXT | 안정 식별자 — company=stockCode · doc=docId · narrative=narrative_id(**버전 행 PK**) · report=report id(**버전 PK**) · chat=`chat_messages.id`(url `/chat?id=대화`) |
| url | TEXT | 네비게이션 타깃(내러티브·리포트는 해당 버전 URL) |
| title | TEXT | 저장 시점 제목 스냅샷 |
| subtitle | TEXT | 보조 스냅샷 — 예: `v3`, topic, 기업명 |
| note | TEXT | 한 줄 메모(선택) |
| created_at | TEXT | |

`UNIQUE(kind, ref)` — 토글 멱등. 버전이 다르면 ref가 달라 **별개 항목**(원칙 2).

> MVP는 제목 **스냅샷**만 저장하고 재-resolve 안 함(단순성). 원본이 사라진 링크는 클릭 시 각 페이지의 자체 Empty가 처리.

## API (`/api/spine/saved`, spine 라우터)

| 엔드포인트 | 기능 |
|---|---|
| `GET ""` | 저장 목록 최신순(`?kind=` 선택 필터). 헤더 배지 카운트·토글 상태·목록 공용 |
| `POST ""` | `{kind, ref, url, title, subtitle?, note?}` → `INSERT OR IGNORE`(멱등). id 반환 |
| `PATCH "/{id}"` | `{note}` 갱신 |
| `DELETE "/{id}"` | 삭제(=저장 해제) |

토글 "저장됨?" 판정은 별도 status 엔드포인트 없이 **GET 목록 캐시에서 (kind, ref) 매칭**으로 결정(ApprovalsInbox 패턴 — 목록 하나로 배지·토글·리스트 전부).

## 화면

### 진입점
- **각 페이지 북마크 토글**(`shared/SaveButton`): 기업 디테일(KPI 스트립 우측, WatchlistButton 옆) · 문서(헤더 메타 행) · 내러티브(툴바, `v{version}` 배지 옆) · 리포트(카드 헤더 버튼 클러스터). 채움/빈 북마크 아이콘, 낙관적 토글, sonner 토스트.
- **헤더 상시 아이콘**(`SavedInbox`, ApprovalsInbox 미러): 북마크 아이콘 + 카운트 배지 → 클릭 시 Sheet(우측)에 최신순 목록(compact).
- **팔로우 서브탭 '저장됨'**(`/follow/saved`, `SavedPage`): 전체 목록 + kind 필터 + 인라인 메모 편집·삭제.

### 5-state (`SavedPage`·Sheet 공용 `SavedList`)
| 상태 | 표시 |
|---|---|
| Empty | "아직 저장한 항목이 없어요" + 저장 방법 힌트(각 페이지의 북마크 아이콘) |
| Loading | Skeleton 행 |
| Error | ErrorState |
| Partial | 목록은 표시하되 title 비면 url/ref로 폴백 라벨 |
| Ideal | kind별 아이콘·제목·subtitle·메모·저장시각, 클릭=url 이동, 우측 삭제 |

## 구현 노트 (통합 지점)

- FE: `Header.tsx`(SavedInbox) · `ModeNavigation.tsx`(FOLLOW_TABS + getActiveSubTab에 `/follow/saved`) · `App.tsx`(route+import) · `api/spine.ts`(`spineKeys.saved`) · `hooks/useSaved.ts`(SavedItem 타입 co-locate — types/index.ts 동시편집 회피) · `shared/SaveButton.tsx` · `follow/SavedList.tsx`·`SavedPage.tsx` · 4개 페이지 토글.
  - 내러티브 현재 버전 id = `NarrativePage`의 `narrativeId`(cached.data.narrative_id) · 리포트 현재 버전 id = `ReportView`의 `display?.id`.
- BE: `database.py`(saved_items CREATE) · `routers/spine_saved.py`(spine_follows 미러) · `main.py`(등록).

## Out of Scope (MVP)
- 폴더·태그·정렬 커스텀 · 제목 재-resolve/liveness 체크 · 드래그 정렬 · 공유.

## 회원 문서 저장 계약 (구현 중)

공용 로그인 모드의 첫 저장 단위는 승인 문서다. 기존 전역 saved_items와 분리된 member_saved_documents에 owner_user_id/doc_id/saved_fingerprint/본인 note/created_at만 저장하며 제목·본문·요약·URL은 복제하지 않는다. 요청마다 principal을 사용하고 owner는 클라이언트가 지정하지 못한다. 명시 schema 초기화만 허용하며 GET은 DDL/쓰기0이다. 기존 company/narrative/report/chat 저장의 회원 연결은 후속이며 전체 저장 범위를 문서로 축소하지 않는다.

`GET /api/member/saved?offset=0&limit=20&doc_id=` → `{items,next_offset}`. items는 `{id,doc_id,title:null|string,url:null|string,available:boolean,status:available|unavailable|changed,current_url:null|string,note:null|string,created_at:string}`. doc_id 필터는 문서별 저장 토글용이며 본인 참조만 검색한다. 목록은 최대20개/페이지, 회원당 최대200개. 각 자료는 기존 publication fingerprint/승인 검사를 통과한 현재 제목과 서버 내부 `/doc/{id}` 링크만 보여준다. 철회·원문변경·삭제로 현재 승인이 유효하지 않은 자료는 status=unavailable,available=false,title/url/current_url=null로 반환하며 본인 메모와 저장 해제는 유지한다. 현재 승인 fingerprint가 저장당시와 다르면 status=changed,title/url=null과 현재공개본 current_url만 반환한다. UI는 저장 이후 내용이 바뀌었음을 명시하고 현재 공개본 링크를 별도로 표시한다. 같은 내용의 재승인은 available이며 중복 POST로 저장 fingerprint를 조용히 바꾸지 않는다. 원문 전체/첨부를 클라이언트에 반환하지 않고 요청별 공용 검증 예산을 적용한다. 예산/저장소 장애는 성공한 빈 목록으로 위장하지 않는다.

`POST /api/member/saved` `{doc_id,note?}` → item(201), 승인 자료만 저장하며 owner/doc 중복은 기존 메모·fingerprint를 바꾸지 않는 멱등 처리. `PATCH /api/member/saved/{id}` `{note}` → `{ok:true}`, `DELETE` 동일응답. 메모 최대2000자, 임의 title/url/owner 필드는 거부한다. 인증·Origin·CSRF와 no-store는 기존 public boundary를 사용한다. 목록과 개별 metadata는 승인 철회를 다시 확인하고 기존 전역 저장을 승계하지 않는다.

화면 `/feed/saved`: 미로그인 로그인안내, loading skeleton, empty 안내, error 재시도(권한오류에 이전 개인정보 숨김), 정상·철회자료 혼합 partial 표시. 승인 문서 화면에 회원 저장/해제와 내 저장목록 링크를 연결한다. 계정별 query key와 계정전환 remount를 사용하며 개인 legacy useSaved/usage 전송은 연결하지 않는다. 메모 편집 실패·해제 실패는 행을 유지하고 오류를 표시한다.
