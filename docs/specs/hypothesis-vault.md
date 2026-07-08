# 가설·메모 Vault — 소유권 분할 설계

> 원칙: **대칭 양방향 sync 금지. "소유권 분할 + 단방향 흐름 2개".**
> 모든 파일에 주인이 정확히 하나 → 병합 로직이 필요 없다.
> Obsidian은 이 폴더를 여는 선택적 뷰어일 뿐 (종속 없음 — vault는 그냥 마크다운 폴더).

```
┌ 기계 소유: 자동 수집 (문서·시계열·그래프) ──────────────────┐
│ 원본 = DB → vault/entities/*.md 로 export (재생성 가능한 뷰)│
│ vault 쪽 사본 수정은 다음 export에서 덮어씀                  │
└──────────────────────────────────────────────────────────────┘
┌ 사람 소유: 가설·메모 ────────────────────────────────────────┐
│ 원본 = vault/notes/*.md (git 감사 가능 — gbrain 패턴)        │
│ → NoteConnector가 척추(raw_documents)로 흡수. DB는 인덱스     │
└──────────────────────────────────────────────────────────────┘
```

## 구성 요소

| 파일 | 역할 |
|---|---|
| `backend/pipeline/connectors/notes.py` | vault/notes/*.md → RawDoc (source_type=note). 레지스트리 등록 → 30분 cron이 자동 흡수 |
| `scripts/vault_sync.py --export` | 활동 있는 엔티티(언급·신호·왓치리스트) → vault/entities/ 도시에 페이지 (frontmatter `generated: true`, 섹터·신호·최근 언급 포함) |
| `store._link` 위키링크 처리 | 본문의 `[[엔티티명]]` → entities 정확 매칭 → entity_links **confidence 1.0** (사람이 명시한 연결) |

## 규약
- `VAULT_PATH` env로 위치 변경 가능 (기본 `<repo>/vault`). **vault/는 gitignore** — 개인 투자 메모를 공개 레포에 올리지 않기 위함. 감사가 필요하면 vault 자체를 별도 private git으로.
- 노트 제목 = 첫 `# ` 헤딩 (없으면 파일명). published_at = 파일 mtime.
- 노트는 keyword/LLM enrich도 통과 → 토픽·산업 태그 자동 부여.
- 효과: 사람 가설과 자동 수집 문서가 **같은 그래프·같은 검색 공간**에서 조인/랭킹됨.

## 미결 (다음 단계)
- 기존 research/memos(DB 직접 CRUD)와의 관계: vault 원본으로 이관 vs 병행 — 미정.
- 도시에 페이지에 "관련 가설(notes 역링크)" 섹션 추가.
