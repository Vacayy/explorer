# 저장됨 (Saved / Bookmarks) — 산출물 북마크

> 2026-07-28 기획. 사용자 요청: 기업 디테일·문서·내러티브·리포트 각 페이지를 저장해두고 언제든 다시.
> 배경: 앱에 "특정 산출물을 다시 찾아보게 고정"하는 원시타입 부재. 팔로우(엔티티 흐름 구독)와 성격이 다름.

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
| kind | TEXT | `company` \| `doc` \| `narrative` \| `report` |
| ref | TEXT | 안정 식별자 — company=stockCode · doc=docId · narrative=narrative_id(**버전 행 PK**) · report=report id(**버전 PK**) |
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
