"""이미지 해석 — 본문 속 이미지를 '전달하려는 메시지' 텍스트로 바꿔 넣는다 (docs/specs/image-reading.md).

- 이미지 파일은 저장하지 않는다: 격리 runtime 폴더에 임시로 받아 haiku(Read)로 읽고 지운다.
- 해석은 image_readings에 캐시 — 재수집 때 LLM·다운로드 없이 같은 텍스트가 나와 문서 해시가 안정적이다.
- 해석 줄은 AI_PREFIX로 시작한다. 저자의 말이 아니므로 원문 인용·인과 추출은 strip_ai_notes로 뺀다.
- 게이트: 관리자 플래그 image_reading · 게시 7일 이내 · 30분당 30콜 · 문서 단위 원자성(일부만 해석하지 않음).
- 백로그(7일 밖)는 backfill_mode 안에서만 읽는다 — 별도 job 라벨·회차 예산·마감 시각 (pipeline/image_backfill.py).
"""
import io
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
import urllib3

from database import get_connection
from pipeline.dates import parse_dt

AI_PREFIX = "[이미지 해석·AI"
JOB = "image_reading"
BUDGET = int(os.getenv("IMAGE_READ_BUDGET", "30"))            # 30분 창당 콜 수
MAX_AGE_DAYS = int(os.getenv("IMAGE_READ_MAX_AGE_DAYS", "7"))  # 신규분만 — 백로그는 별도 결정
MAX_PER_DOC = 12
MAX_ATTEMPTS = 3
MIN_SIDE = 200
MIN_BYTES = 5_000
WORKERS = 3

KIND_LABEL = {"chart": "차트", "table": "표", "text": "텍스트", "diagram": "도식",
              "calendar": "일정표", "photo": "사진", "other": "기타"}

# 블로그 <img> 사전 필터 (LLM 0) — 링크 미리보기·스티커·이모지·아바타
_SKIP_HOSTS = ("s.w.org", "dthumb-phinf.pstatic.net", "gravatar.com", "ssl.pstatic.net")
_SKIP_CLASS = ("se-oglink-thumbnail", "se-sticker", "emoji", "avatar")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@dataclass
class Backfill:
    calls_left: int      # 이번 회차에 남은 호출 수
    deadline: float      # time.time() 기준 마감
    job: str = "image_backfill"
    offline: bool = False  # 인터넷이 끊겨 있었다 — 회차를 접는다


_backfill: ContextVar[Backfill | None] = ContextVar("image_backfill", default=None)


@contextmanager
def backfill_mode(bf: Backfill):
    """이 블록 안의 read_images는 게시일 제한 없이, bf의 예산·마감으로 읽는다."""
    token = _backfill.set(bf)
    try:
        yield bf
    finally:
        _backfill.reset(token)


def unresolved(keys: list[str]) -> int:
    """아직 해석이 필요한(캐시에 없거나 재시도 가능한 실패) 이미지 수."""
    if not keys:
        return 0
    conn = get_connection()
    try:
        rows = _rows(conn, keys)
    finally:
        conn.close()
    return len({k for k in keys if _needs(rows.get(k))})


def _needs(row) -> bool:
    return row is None or (row["status"] == "failed" and row["attempts"] < MAX_ATTEMPTS)

PROMPT = (
    "Read 도구로 이 이미지를 읽어: {path}\n"
    "{source}에 첨부된 이미지다. 정확한 수치 판독보다 \"이 이미지가 전달하려는 메시지\"에 집중해.\n"
    "함께 게시된 글(의도 파악용 맥락):\n\"\"\"{context}\"\"\"\n"
    "- 글의 주장을 평가·반박하지 마라. 이미지가 말하는 것만 써라. 이미지에 없는 내용을 지어내지 마라.\n"
    "- 작은 글씨의 고유명사가 확실하지 않으면 쓰지 마라.\n"
    "- 정보 가치가 없는 이미지(로고·밈·인물/풍경 사진·광고·장식)는 skip=true.\n"
    "- 이미지가 함께 게시된 글을 그대로 옮긴 것일 뿐 새 정보가 없으면(기사·보고서 표지, 글 캡처) skip=true.\n"
    "- kind=calendar(증시·실적 일정표)일 때만 events를 채워라. 날짜에 연도가 없으면 게시일({date}) 기준으로 추정.\n"
    "JSON 한 줄만 출력:\n"
    '{{"kind":"chart|table|text|diagram|calendar|photo|other","skip":false,'
    '"title":"이미지 제목(없으면 짧은 요약)","insight":"이 이미지가 말하려는 핵심 메시지 1~2문장",'
    '"evidence":"그 메시지를 받치는 근거 — 추세·비교·특이점, 꼭 필요한 수치만 1~3개",'
    '"events":[{{"date":"YYYY-MM-DD","title":"","stock_name":"관련 한국 상장사 정식명 또는 null"}}]}}'
)


def strip_ai_notes(text: str) -> str:
    """AI 해석 줄을 뺀 본문 — 저자의 말만 필요한 경로(원문 인용·인과 추출)용."""
    return "\n".join(l for l in (text or "").split("\n") if not l.lstrip().startswith(AI_PREFIX))


def format_note(row) -> str | None:
    if not row or row["status"] != "ok" or not (row["insight"] or "").strip():
        return None
    label = KIND_LABEL.get(row["kind"] or "", "이미지")
    title = (row["title"] or "").strip()
    note = f"{AI_PREFIX} · {label}] " + (f"{title} — " if title else "") + row["insight"].strip()
    if (row["evidence"] or "").strip():
        note += f" (근거: {row['evidence'].strip()})"
    return " ".join(note.split())


def blog_image_ref(img) -> tuple[str, str] | None:
    """<img> 태그 → (캐시 키, 다운로드 URL). 장식으로 보이면 None."""
    url = img.get("data-lazy-src") or img.get("data-src") or img.get("src") or ""
    if not url.startswith("http") or url.lower().split("?")[0].endswith(".svg"):
        return None
    host = urlparse(url).netloc
    if any(host == h or host.endswith("." + h) for h in _SKIP_HOSTS):
        return None
    classes = " ".join(img.get("class") or [])
    if any(c in classes for c in _SKIP_CLASS):
        return None
    for attr in ("width", "height", "data-width", "data-height"):
        v = str(img.get(attr) or "").strip()
        if v.isdigit() and int(v) < MIN_SIDE:
            return None
    return url, url


def _in_scope(published_at: str) -> bool:
    from pipeline.enrich import llm_engine
    from pipeline.ops import flag_enabled
    if llm_engine() != "claude-code" or not flag_enabled(JOB):
        return False
    dt = parse_dt(published_at or "")
    return dt is not None and dt >= datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)


def _remaining_budget(conn) -> int:
    used = conn.execute(
        "SELECT COUNT(*) FROM llm_calls WHERE job=? AND created_at >= datetime('now','-30 minutes')",
        (JOB,)).fetchone()[0]
    return BUDGET - used


def _load(it: dict) -> tuple[bytes, str] | None:
    """이미지 바이트와 확장자 — 로컬 파일(it['file']) 또는 다운로드. 너무 작거나 이미지가 아니면 None(필터)."""
    from PIL import Image
    if it.get("file"):
        with open(it["file"], "rb") as f:
            data = f.read()
    else:
        resp = requests.get(it["url"], headers={"User-Agent": _UA, "Referer": it.get("referer") or it["url"]},
                            timeout=20, verify=False)  # 수집기 공통(blog_service·옛 텔레그램 다운로드)과 같은 설정
        resp.raise_for_status()
        data = resp.content
    if len(data) < MIN_BYTES:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        w, h = im.size
        fmt = (im.format or "").lower()
    except Exception:
        return None
    if min(w, h) < MIN_SIDE or fmt not in ("jpeg", "png", "gif", "webp"):
        return None
    return data, "jpg" if fmt == "jpeg" else fmt


def _call(data: bytes, ext: str, context: str, source: str, published_at: str, job: str = JOB) -> dict:
    from pipeline import llm
    llm.RUNTIME_DIR.joinpath("img").mkdir(parents=True, exist_ok=True)
    rel = f"img/{uuid.uuid4().hex}.{ext}"   # headless Read는 cwd(RUNTIME_DIR) 하위만 읽는다
    path = llm.RUNTIME_DIR / rel
    path.write_bytes(data)
    try:
        res = llm.run(PROMPT.format(path=rel, source=source, context=(context or "")[:1200],
                                    date=(published_at or "")[:10]),
                      model="haiku", effort="low", tools=("Read",), job=job, timeout=180)
    finally:
        path.unlink(missing_ok=True)
    out = llm.extract_json(res.text)
    if not out:
        raise ValueError(f"JSON 없음: {res.text[:80]!r}")
    return out


def _save(conn, key: str, status: str, out: dict | None = None, error: str | None = None) -> None:
    out = out or {}
    events = out.get("events") if out.get("kind") == "calendar" else None
    conn.execute("""
        INSERT INTO image_readings (image_key, status, kind, title, insight, evidence, events_json, attempts, error, model)
        VALUES (?,?,?,?,?,?,?,1,?,?)
        ON CONFLICT(image_key) DO UPDATE SET status=excluded.status, kind=excluded.kind, title=excluded.title,
            insight=excluded.insight, evidence=excluded.evidence, events_json=excluded.events_json,
            attempts=image_readings.attempts+1, error=excluded.error, model=excluded.model,
            updated_at=datetime('now')""",
        (key, status, out.get("kind"), out.get("title"), out.get("insight"), out.get("evidence"),
         json.dumps(events, ensure_ascii=False) if events else None, error, "claude-code/haiku"))
    conn.commit()


def read_images(items: list[dict], *, published_at: str, source: str, source_url: str = "") -> dict[str, str | None]:
    """items=[{key, url|file, context, referer[, published_at, source_url]}] → {키: 해석 줄 또는 None}.
    항목별 published_at·source_url은 여러 문서를 한 번에 읽는 백필용(없으면 인자값).

    캐시 우선. 미해석분은 게이트 통과 시 문서 단위로 한꺼번에 — 남은 예산으로 전부 못 읽으면 이번엔
    하나도 읽지 않는다(일부씩 들어가면 문서 해시가 여러 번 바뀌어 재태깅이 반복된다).
    """
    items = items[:MAX_PER_DOC]
    if not items:
        return {}
    keys = [it["key"] for it in items]
    bf = _backfill.get()
    conn = get_connection()
    try:
        rows = _rows(conn, keys)
        todo = list({it["key"]: it for it in items if _needs(rows.get(it["key"]))}.values())  # 같은 이미지는 한 번
        if todo and _allowed(conn, published_at, len(todo), bf):
            from pipeline.vision import _insert_events
            job = bf.job if bf else JOB

            def work(it):  # → (항목, 상태, 해석, 오류, LLM 호출 여부)
                try:
                    got = _load(it)
                except (requests.ConnectionError, requests.Timeout) as e:
                    # PC가 오프라인이면 모든 다운로드가 즉시 실패한다 — 시도 횟수로 세면 멀쩡한 이미지를 포기하게 된다
                    err = f"{type(e).__name__}: {str(e)[:200]}"
                    return it, ("failed" if _online() else "offline"), None, err, False
                except Exception as e:  # noqa: BLE001 — 이미지 하나의 실패가 수집을 막지 않는다
                    return it, "failed", None, f"{type(e).__name__}: {str(e)[:200]}", False
                if got is None:
                    return it, "filtered", None, None, False
                try:
                    out = _call(*got, context=it.get("context", ""), source=source,
                                published_at=it.get("published_at") or published_at, job=job)
                    return it, "skip" if str(out.get("skip")).lower() == "true" else "ok", out, None, True
                except Exception as e:  # noqa: BLE001
                    return it, "failed", None, f"{type(e).__name__}: {str(e)[:200]}", True
            with ThreadPoolExecutor(min(WORKERS, len(todo))) as ex:
                results = list(ex.map(work, todo))
            for it, status, out, err, called in results:      # DB 쓰기는 한 스레드에서
                if status == "offline":
                    if bf:
                        bf.offline = True
                    continue                                    # 기록하지 않는다 — 다음 회차에 그대로 다시
                _save(conn, it["key"], status, out, err)
                if called and bf:
                    bf.calls_left -= 1
                if out and out.get("kind") == "calendar" and out.get("events"):
                    _insert_events(conn, out["events"], it.get("source_url") or source_url)
                    conn.commit()
            rows = _rows(conn, keys)
        return {k: format_note(rows.get(k)) for k in keys}
    finally:
        conn.close()


def _online() -> bool:
    """다운로드 실패가 그 호스트 문제인지, PC가 오프라인인지."""
    try:
        requests.head("https://www.google.com", timeout=5, verify=False)
        return True
    except requests.RequestException:
        return False


def _allowed(conn, published_at: str, n: int, bf: Backfill | None) -> bool:
    if bf:
        from pipeline.enrich import llm_engine
        return llm_engine() == "claude-code" and n <= bf.calls_left and time.time() < bf.deadline
    return _in_scope(published_at) and n <= _remaining_budget(conn)


def _rows(conn, keys: list[str]) -> dict:
    return {r["image_key"]: r for r in conn.execute(
        f"SELECT * FROM image_readings WHERE image_key IN ({','.join('?' * len(keys))})", keys)}


_PH = "\x00IMG{}\x00"
_PH_RE = re.compile(r"\x00IMG(\d+)\x00")


def placeholder(i: int) -> str:
    return _PH.format(i)


def fill_placeholders(text: str, refs: list[tuple[str, str]], *, title: str, published_at: str,
                      source: str, page_url: str) -> str:
    """정규화 텍스트 속 이미지 자리표시 → 해석 줄(없으면 제거). 맥락 = 제목 + 그 이미지 앞뒤 본문."""
    clean = _PH_RE.sub("", text)
    pos = {int(m.group(1)): len(_PH_RE.sub("", text[:m.start()])) for m in _PH_RE.finditer(text)}
    items = []
    for i, (key, url) in enumerate(refs):
        p = pos.get(i, 0)
        items.append({"key": key, "url": url, "referer": _referer(url, page_url),
                      "context": f"{title}\n…{clean[max(0, p - 600):p]}\n[이미지 위치]\n{clean[p:p + 300]}…"})
    notes = read_images(items, published_at=published_at, source=source, source_url=page_url)

    def sub(m):
        i = int(m.group(1))
        return (notes.get(refs[i][0]) or "") if i < len(refs) else ""
    return _PH_RE.sub(sub, text)


def _referer(url: str, page_url: str) -> str:
    return "https://blog.naver.com/" if "pstatic.net" in url else (page_url or url)
