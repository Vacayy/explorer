"""Isolated run ledger; operating corpus is never opened for writing here."""
import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH

ROOT = Path(__file__).resolve().parents[3]
TERMINAL = {"complete", "partial", "failed", "cancelled"}


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256((value if isinstance(value, str) else dumps(value)).encode()).hexdigest()


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class Store:
    def __init__(self, db_path=None, runs_dir=None, source_path=None):
        self.source_path = Path(source_path or DB_PATH).resolve()
        self.db_path = Path(db_path or ROOT / "backend/db/weekly_experiment.sqlite").resolve()
        self.runs_dir = Path(runs_dir or ROOT / "logs/weekly-harness/runs").resolve()
        if self.db_path == self.source_path or (self.db_path.exists() and self.source_path.exists() and self.db_path.samefile(self.source_path)):
            raise ValueError("Weekly DB는 운영 DB와 분리해야 합니다")

    @contextmanager
    def connect(self, *, write=False):
        if write:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.db_path.exists():
            raise FileNotFoundError("Weekly 실행 기록이 없습니다")
        conn = sqlite3.connect(self.db_path if write else f"{self.db_path.as_uri()}?mode=ro",
                               uri=not write, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            if write:
                conn.execute("PRAGMA journal_mode=WAL")
            else:
                conn.execute("PRAGMA query_only=ON")
            yield conn
            if write:
                conn.commit()
        except BaseException:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        with self.connect(write=True) as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
              status TEXT NOT NULL, config TEXT NOT NULL, checkpoint TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              cancel_requested INTEGER NOT NULL DEFAULT 0, error TEXT);
            CREATE TABLE IF NOT EXISTS events (
              seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
              kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_run ON events(run_id,seq);
            """)

    def directory(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("잘못된 run id")
        return self.runs_dir / run_id

    def create(self, request):
        self.initialize()
        config = request.model_dump(mode="json")
        with self.connect(write=True) as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT * FROM runs WHERE request_key=?", (request.request_key,)).fetchone()
            if old:
                # A repeated request must not silently change the task or its evidence boundary.
                previous = json.loads(old["checkpoint"]).get("initial_config", json.loads(old["config"]))
                if "cutoff" in request.model_fields_set and datetime.fromisoformat(previous["cutoff"].replace("Z", "+00:00")) != request.cutoff:
                    raise ValueError("request_key의 cutoff를 변경할 수 없습니다")
                for key in ("request_key", "cutoff"):
                    previous.pop(key, None)
                current = {k: v for k, v in config.items() if k not in ("request_key", "cutoff")}
                if previous != current:
                    raise ValueError("request_key가 다른 설정으로 이미 사용됐습니다")
                return old["id"], False
            # Validate freshness only for new runs: a delayed HTTP retry must still
            # return its original run, including an explicitly repeated cutoff.
            if request.mode == "live" and (datetime.fromisoformat(now().replace("Z", "+00:00")) - request.cutoff).total_seconds() > 300:
                raise ValueError("과거 cutoff는 public_reconstruction 또는 system_replay로 지정하세요")
            rid = uuid.uuid4().hex
            cp = {"steps": 0, "tool_calls": 0, "elapsed_seconds": 0, "history": [],
                  "read_ids": [], "decisions": [], "gaps": [], "reviews": [], "initial_config": config}
            c.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,0,NULL)",
                      (rid, request.request_key, "queued", dumps(config), dumps(cp), now(), now()))
        self.directory(rid).mkdir(parents=True, exist_ok=True)
        return rid, True

    def get(self, run_id):
        self.directory(run_id)
        with self.connect() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        data = dict(row)
        for key in ("config", "checkpoint"):
            data[key] = json.loads(data[key])
        data["cancel_requested"] = bool(data["cancel_requested"])
        data["artifacts"] = sorted(p.name for p in self.directory(run_id).glob("*") if p.is_file() and not p.name.endswith((".tmp", ".lock")))
        return data

    def list_runs(self, limit=30):
        if not self.db_path.exists():
            return []
        with self.connect() as c:
            return [dict(r) for r in c.execute(
                "SELECT id,status,created_at,updated_at,error FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))]

    def save(self, run_id, *, checkpoint=None, status=None, error=None, event=None):
        with self.connect(write=True) as c:
            c.execute("BEGIN IMMEDIATE")
            if checkpoint is not None:
                c.execute("UPDATE runs SET checkpoint=? WHERE id=?", (dumps(checkpoint), run_id))
            if status:
                c.execute("UPDATE runs SET status=?,error=? WHERE id=?", (status, error, run_id))
            c.execute("UPDATE runs SET updated_at=? WHERE id=?", (now(), run_id))
            if event:
                c.execute("INSERT INTO events(run_id,kind,data,created_at) VALUES(?,?,?,?)",
                          (run_id, event[0], dumps(event[1]), now()))

    def events(self, run_id):
        with self.connect() as c:
            return [{**dict(r), "data": json.loads(r["data"])} for r in c.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,))]

    def cancel(self, run_id):
        self.get(run_id)
        with self.connect(write=True) as c:
            c.execute("UPDATE runs SET cancel_requested=1,updated_at=?,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END WHERE id=? AND status NOT IN ('complete','partial','failed','cancelled')", (now(), run_id))
        return self.get(run_id)

    def resume(self, run_id, request):
        with self.connect(write=True) as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row["status"] not in {"partial", "failed", "cancelled"}:
                raise ValueError("종료되거나 중단된 실행만 재개할 수 있습니다")
            if not (self.directory(run_id) / "corpus.sqlite").exists():
                raise ValueError("고정 자료가 없는 실행입니다. 새 request_key로 시작하세요")
            config = json.loads(row["config"])
            config["max_steps"] += request.extra_steps
            config["max_seconds"] += request.extra_seconds
            config["max_tool_calls"] += request.extra_tool_calls
            cp = json.loads(row["checkpoint"])
            cp.setdefault("initial_config", json.loads(row["config"]))
            cp["resume_count"] = cp.get("resume_count", 0) + 1
            c.execute("UPDATE runs SET status='queued',cancel_requested=0,error=NULL,config=?,checkpoint=?,updated_at=? WHERE id=?", (dumps(config), dumps(cp), now(), run_id))
            c.execute("INSERT INTO events(run_id,kind,data,created_at) VALUES(?,?,?,?)", (run_id, "resume", dumps(request.model_dump()), now()))
        return self.get(run_id)

    def recover(self, run_id):
        """Only an absent process owner permits recovery; elapsed time alone is insufficient."""
        import fcntl
        self.get(run_id)
        with self.db_path.with_suffix(".worker.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Weekly worker가 실행 중이므로 복구할 수 없습니다")
            with self.connect(write=True) as c:
                c.execute("UPDATE runs SET status='failed',error='worker 중단: 고정 자료로 resume 가능',updated_at=? WHERE id=? AND status NOT IN ('complete','partial','failed','cancelled')", (now(), run_id))
        return self.get(run_id)

    def memory(self, cutoff, exclude):
        if not self.db_path.exists():
            return []
        with self.connect() as c:
            rows = c.execute("SELECT id,config,checkpoint,created_at,updated_at FROM runs WHERE id!=? AND status IN ('complete','partial') ORDER BY created_at DESC", (exclude,)).fetchall()
        result = []
        boundary = datetime.fromisoformat(cutoff)
        for r in rows:
            cp, cfg = json.loads(r["checkpoint"]), json.loads(r["config"])
            if datetime.fromisoformat(r["updated_at"]) <= boundary and datetime.fromisoformat(cfg["cutoff"].replace("Z", "+00:00")) < boundary:
                result.append({"run_id": r["id"], "cutoff": cfg["cutoff"], "kind": "prior_model_judgment_not_evidence", "hypotheses": cp.get("draft", {}).get("hypotheses", [])})
            if len(result) == 3:
                break
        return result
