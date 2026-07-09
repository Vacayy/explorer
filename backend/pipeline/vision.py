"""이미지 비전 분석 — 텔레그램 첨부에서 증시일정(캘린더) 이벤트 추출.

- 엔진: claude-code headless (haiku + Read 도구로 로컬 이미지 열람).
  ANTHROPIC_API_KEY 방식(base64)은 키 확보 후 확장.
- 이미지당 1회 분석 (media_analysis 캐시) — 재실행 안전.
- kind=calendar인 이미지의 events만 catalysts로 적재 (event 캘린더 자동화의 비정형 절반).
  적재된 이벤트는 홈 캘린더 스트립·research/catalysts에 즉시 표시된다.
"""
import json
import subprocess

from config import MEDIA_PATH
from database import get_connection
from pipeline.enrich import _claude_bin, llm_engine


def _analyze_image(path: str, published_at: str) -> dict:
    prompt = (
        f"Read 도구로 이 이미지를 읽어: {path}\n"
        "이미지를 보고 JSON만 출력해 (설명 금지):\n"
        '{"kind": "calendar|chart|table|text|other", "description": "한 줄", '
        '"events": [{"date": "YYYY-MM-DD", "title": "", "stock_name": "관련 한국 상장사 정식명 또는 null"}]}\n'
        "- kind=calendar(증시일정표)일 때만 events 채움, 아니면 빈 배열\n"
        "- 일정표의 개별 항목을 각각 이벤트로. 날짜에 연도가 없으면 게시 시점 기준으로 추정\n"
        f"- 이 이미지는 {published_at[:10]} 게시글 첨부임"
    )
    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", "haiku", "--allowedTools", "Read",
         "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=180,
        cwd=str(MEDIA_PATH),  # headless Read는 cwd 하위만 허용 — 호출 위치와 무관하게 고정
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {proc.stderr[:200]}")
    result = json.loads(proc.stdout).get("result", "")
    s, e = result.find("{"), result.rfind("}")
    if s < 0 or e <= s:
        raise ValueError(f"JSON 없음: {result[:80]}")
    return json.loads(result[s:e + 1])


def _insert_events(conn, events: list[dict], source_url: str) -> int:
    """calendar 이벤트 → catalysts. (event_date, title) 기준 중복 방지."""
    n = 0
    for ev in events:
        date, title = (ev.get("date") or "").strip(), (ev.get("title") or "").strip()
        if not date or not title:
            continue
        if conn.execute("SELECT 1 FROM catalysts WHERE event_date=? AND title=?",
                        (date, title)).fetchone():
            continue
        stock_code = corp_code = None
        if ev.get("stock_name"):
            row = conn.execute(
                "SELECT aliases, meta_json FROM entities WHERE type='company' AND name=?",
                (str(ev["stock_name"]).strip(),)).fetchone()
            if row and row["aliases"]:
                stock_code = row["aliases"]
                meta = json.loads(row["meta_json"] or "{}")
                corp_code = meta.get("corp_code")
        conn.execute(
            "INSERT INTO catalysts (stock_code, corp_code, event_type, event_date, title, description) "
            "VALUES (?, ?, 'schedule', ?, ?, ?)",
            (stock_code, corp_code, date, title, f"자동추출(이미지): {source_url}"),
        )
        n += 1
    return n


def extract_events(limit: int | None = None) -> dict:
    """미분석 이미지 전부 비전 분석 → calendar면 이벤트 적재."""
    if llm_engine() != "claude-code":
        return {"skipped": "claude-code 엔진 아님 (ENRICH_ENGINE 확인)"}

    conn = get_connection()
    todo = conn.execute("""
        SELECT rd.id doc_id, rd.url, rd.published_at, rd.media_json
        FROM raw_documents rd
        WHERE rd.media_json IS NOT NULL
    """).fetchall()

    stats = {"analyzed": 0, "calendars": 0, "events": 0, "failed": 0}
    pairs = []
    for r in todo:
        for rel in json.loads(r["media_json"]):
            if not conn.execute("SELECT 1 FROM media_analysis WHERE image_path=?", (rel,)).fetchone():
                pairs.append((r, rel))
    if limit:
        pairs = pairs[:limit]

    for r, rel in pairs:
        path = MEDIA_PATH / rel
        if not path.exists():
            continue
        try:
            data = _analyze_image(str(path), r["published_at"] or "")
        except Exception as e:
            stats["failed"] += 1
            print(f"  vision 실패 {rel}: {e}")
            continue
        events = data.get("events") or []
        conn.execute(
            "INSERT OR IGNORE INTO media_analysis (doc_id, image_path, kind, description, events_json, model) "
            "VALUES (?, ?, ?, ?, ?, 'claude-code/haiku')",
            (r["doc_id"], rel, data.get("kind"), data.get("description"),
             json.dumps(events, ensure_ascii=False) if events else None),
        )
        stats["analyzed"] += 1
        if data.get("kind") == "calendar" and events:
            stats["calendars"] += 1
            stats["events"] += _insert_events(conn, events, r["url"] or "")
        conn.commit()

    conn.close()
    return stats
