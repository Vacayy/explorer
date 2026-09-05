"""축적물 백업 — DB·vault·media (D-129).

git은 **로직만** 지킨다. 이 프로젝트의 값어치는 축적물에 있는데 그건 전부 gitignore다:
  · `backend/db/stock_explorer.db` (422MB) — 문서 12,000+건. 텔레그램은 공개 채널 최근 ~20개
    창만 긁으므로 **재수집으로 복원 불가**. 재태깅·인과추출에 들어간 LLM 비용도 함께 날아간다.
  · `vault/` (34MB) — 사람이 쓴 canon 노트·원칙 원장·리서치 노트. **원본이라 복구 불가.**
  · `media/` (215MB) — 텔레그램 첨부. CDN 만료분은 영구 소실.

설계:
  ① **DB는 `VACUUM INTO`** — 실행 중에도 안전한 온라인 백업이고 조각까지 제거한다
     (실측 422MB → 404MB → gzip 123MB). 파일 복사는 쓰기 중이면 깨진 스냅샷이 나온다.
  ② **검증까지가 백업이다** — 만든 파일을 열어 `PRAGMA integrity_check`와 핵심 테이블 건수를
     확인한다. 복원해본 적 없는 백업은 백업이 아니다.
  ③ **세대 보관** — 랩탑 고장뿐 아니라 '잘못된 배치가 데이터를 망친' 논리 사고도 되돌리려면
     최신 1개로는 부족하다(기본 7세대).
  ④ **media는 버전 없이 미러** — append-only라 세대를 쌓을 이유가 없고 용량만 먹는다.

목적지는 `BACKUP_DIR`(.env 또는 인자). **같은 디스크는 랩탑 고장에 무의미**하므로
외장·클라우드 동기화 폴더를 권한다.

  python scripts/backup.py --dir /Volumes/X/explorer-backup
  python scripts/backup.py --skip-media          # DB·vault만 (빠름)
  python scripts/backup.py --verify-only <경로>  # 기존 백업 검증
"""
import argparse
import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "backend"))
import config  # noqa: E402,F401 — .env 로드 부수효과

DB = PROJECT / "backend" / "db" / "stock_explorer.db"
KEEP = 7                       # DB 세대 보관 수
CORE_TABLES = ("raw_documents", "enrichments", "entity_relations", "narratives", "knowledge")


def _human(n: int) -> str:
    return f"{n / 1048576:.0f}MB" if n >= 1048576 else f"{n / 1024:.0f}KB"


def snapshot_db(dest: Path) -> Path:
    """VACUUM INTO → gzip. 실행 중 쓰기와 안전하게 공존한다(파일 복사와 다름)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    raw = dest / f"db-{stamp}.sqlite"
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        conn.execute("VACUUM INTO ?", (str(raw),))
    finally:
        conn.close()
    out = dest / f"db-{stamp}.sqlite.gz"
    with open(raw, "rb") as fi, gzip.open(out, "wb", compresslevel=6) as fo:
        shutil.copyfileobj(fi, fo, 1024 * 1024)
    verify_db(raw)                       # 압축 전 원본으로 검증
    raw.unlink()
    return out


def verify_db(path: Path) -> dict:
    """무결성 + 핵심 테이블 건수. 하나라도 어긋나면 예외."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise RuntimeError(f"무결성 검사 실패: {ok[:200]}")
        counts = {}
        for t in CORE_TABLES:
            try:
                counts[t] = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                counts[t] = None
        if not counts.get("raw_documents"):
            raise RuntimeError("raw_documents가 비었다 — 백업이 유효하지 않다")
        return counts
    finally:
        conn.close()


def verify_gz(path: Path) -> dict:
    """압축 백업을 풀어 검증 — 복원 리허설. 이걸 통과해야 '백업됐다'고 말할 수 있다."""
    tmp = path.with_suffix(".verify.sqlite")
    try:
        with gzip.open(path, "rb") as fi, open(tmp, "wb") as fo:
            shutil.copyfileobj(fi, fo, 1024 * 1024)
        return verify_db(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def snapshot_vault(dest: Path) -> Path | None:
    src = PROJECT / "vault"
    if not src.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = dest / f"vault-{stamp}.tar.gz"
    subprocess.run(["tar", "-czf", str(out), "-C", str(PROJECT), "vault"], check=True)
    return out


def mirror_media(dest: Path) -> dict:
    """append-only라 세대 없이 미러. --delete 없이 — 원본에서 사라져도 백업은 남긴다."""
    src = PROJECT / "media"
    if not src.exists():
        return {"skipped": "media 없음"}
    target = dest / "media"
    target.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["rsync", "-a", "--stats", f"{src}/", f"{target}/"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"rsync 실패: {r.stderr[:200]}")
    files = sum(1 for _ in target.rglob("*") if _.is_file())
    return {"files": files}


def rotate(dest: Path, prefix: str, keep: int) -> int:
    olds = sorted(dest.glob(f"{prefix}-*.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for p in olds[keep:]:
        p.unlink()
        removed += 1
    return removed


def run(dest: Path, skip_media: bool) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    if dest.resolve().is_relative_to(PROJECT.resolve()):
        raise RuntimeError(f"백업 경로가 프로젝트 안이다({dest}) — 저장소 비대·유실 위험")

    t0 = time.time()
    out: dict = {"dest": str(dest)}

    db_gz = snapshot_db(dest)
    counts = verify_gz(db_gz)            # 복원 리허설
    out["db"] = {"file": db_gz.name, "size": _human(db_gz.stat().st_size), "counts": counts}

    v = snapshot_vault(dest)
    out["vault"] = {"file": v.name, "size": _human(v.stat().st_size)} if v else {"skipped": True}

    out["media"] = {"skipped": True} if skip_media else mirror_media(dest)
    out["rotated"] = {"db": rotate(dest, "db", KEEP), "vault": rotate(dest, "vault", KEEP)}
    out["total_dest"] = _human(sum(p.stat().st_size for p in dest.rglob("*") if p.is_file()))
    out["elapsed_s"] = round(time.time() - t0, 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.getenv("BACKUP_DIR"),
                    help="백업 목적지 (미지정 시 .env BACKUP_DIR)")
    ap.add_argument("--skip-media", action="store_true")
    ap.add_argument("--verify-only", metavar="PATH", help="기존 .sqlite.gz 검증만")
    args = ap.parse_args()

    if args.verify_only:
        print("[backup] 검증:", verify_gz(Path(args.verify_only)))
        return
    if not args.dir:
        print("BACKUP_DIR 미지정 — .env에 BACKUP_DIR=... 를 넣거나 --dir 를 주세요.")
        sys.exit(2)

    from pipeline.ops import run_job
    r = run_job("backup", lambda: run(Path(args.dir).expanduser(), args.skip_media))
    print("[backup]", r)


if __name__ == "__main__":
    main()
