"""실행 중인 백엔드가 최신 코드인가 (docs/specs/frontend-api-reliability.md §서버 반영).

uvicorn은 --reload 없이 돈다(수 분짜리 백그라운드 작업이 코드 저장마다 끊기지 않게). 그래서 코드를 고친 뒤
재시작 전까지는 옛 코드가 응답하고, 프런트(vite는 즉시 반영)와 계약이 어긋난다(2026-10-31: 주가 응답 수정 후
재시작 전이라 기업 상세가 계속 계약 오류). 서버 프로세스가 import될 때의 시각과 backend/ 아래 .py 최신 수정
시각을 비교해 '재시작 필요'를 운영 점검과 화면 오류 안내에 알린다.
"""
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # backend/
STARTED_AT = datetime.now(timezone.utc)


def newest_code() -> tuple[datetime | None, str | None]:
    best, name = 0.0, None
    for p in ROOT.rglob("*.py"):
        if "__pycache__" in p.parts or "tests" in p.parts:
            continue
        m = p.stat().st_mtime
        if m > best:
            best, name = m, str(p.relative_to(ROOT))
    return (datetime.fromtimestamp(best, timezone.utc) if best else None), name


def status() -> dict:
    changed, name = newest_code()
    stale = bool(changed and changed > STARTED_AT)
    return {"started_at": STARTED_AT.isoformat(timespec="seconds"),
            "code_changed_at": changed.isoformat(timespec="seconds") if changed else None,
            "changed_file": name if stale else None, "stale": stale,
            "stale_minutes": int((datetime.now(timezone.utc) - changed).total_seconds() // 60) if stale else 0}


def health_item() -> dict:
    s = status()
    return {"key": "backend_code", "label": "백엔드 코드 반영", "kind": "runtime", "owner": "uvicorn 재시작",
            "critical": False, "latest": s["code_changed_at"], "expected": "시작 후 코드 변경 없음",
            "status": "stale" if s["stale"] else "ok",
            "detail": f"재시작 필요 — {s['stale_minutes']}분 전 {s['changed_file']} 변경" if s["stale"] else ""}
