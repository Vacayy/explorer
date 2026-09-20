"""File-backed state, replay and artifact storage, separate from the application DB."""
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import re
import stat
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ID = re.compile(r"^[0-9a-f]{32}$")
TERMINAL = {"completed", "partial", "blocked", "failed", "cancelled", "interrupted"}
MAX_FILE = 16 * 1024 * 1024


class StoreError(ValueError):
    pass


class Conflict(StoreError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def secure_directory(path: Path) -> Path:
    """Host-managed ancestors may never be symlinks, even at initialization."""
    path = path.absolute()
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise StoreError("Symlink directory rejected")
        part.mkdir(exist_ok=True, mode=0o700)
        if not part.is_dir():
            raise StoreError("Expected directory")
    return path


def read_bytes(root: Path, relative: str, limit: int = MAX_FILE) -> bytes:
    """Walk with directory FDs; reject traversal, symlinks and hardlinks atomically."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in {".", ".."} for p in parts):
        raise StoreError("Invalid file path")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        target = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(target)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
                raise StoreError("Only bounded regular files with one link are accepted")
            with os.fdopen(target, "rb", closefd=False) as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise StoreError("File exceeds size limit")
            return data
        finally:
            os.close(target)
    finally:
        os.close(fd)


def read_json(root: Path, relative: str) -> Any:
    def reject_constant(value):
        raise StoreError(f"Non-finite JSON number: {value}")
    return json.loads(read_bytes(root, relative), parse_constant=reject_constant)


def atomic_write(path: Path, data: bytes) -> None:
    """Only use for trusted control directories, never the sandbox workspace."""
    secure_directory(path.parent)
    if path.is_symlink() or (path.exists() and path.stat().st_nlink != 1):
        raise StoreError("Unsafe destination")
    tmp = path.parent / f".tmp-{uuid.uuid4().hex}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        tmp.unlink(missing_ok=True)


class RunStore:
    def __init__(self, root: Path):
        self.root = secure_directory(Path(root))
        for name in ("runs", "snapshots", "workspaces", "control"):
            secure_directory(self.root / name)
        self._mutex = threading.RLock()

    @contextmanager
    def lock(self, name: str = "requests"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name):
            raise StoreError("Invalid lock name")
        with self._mutex:
            fd = os.open(self.root / "control" / f"{name}.lock",
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                if os.fstat(fd).st_nlink != 1:
                    raise StoreError("Unsafe lock file")
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def run_dir(self, run_id: str) -> Path:
        if not ID.fullmatch(run_id):
            raise StoreError("Invalid run ID")
        return self.root / "runs" / run_id

    def read(self, run_id: str) -> dict:
        return read_json(self.run_dir(run_id), "state.json")

    @staticmethod
    def public(state: dict) -> dict:
        return {k: v for k, v in state.items() if not k.startswith("_")}

    def _save(self, state: dict) -> None:
        state["updated_at"] = now()
        atomic_write(self.run_dir(state["id"]) / "state.json", encode(state))

    def mutate(self, run_id: str, change) -> dict:
        with self.lock(run_id):
            state = self.read(run_id)
            change(state)
            self._save(state)
            self._emit(state, {"type": "CUSTOM", "name": "analysis.state", "value": self.public(state)})
            return state

    def create(self, request: dict) -> tuple[dict, bool]:
        key = hashlib.sha256(request["request_key"].encode()).hexdigest()
        with self.lock():
            index = self.root / "control" / f"request-{key}.json"
            if index.exists():
                previous = read_json(index.parent, index.name)
                if previous["request"] != request:
                    raise Conflict("같은 요청 키에 다른 질문을 사용할 수 없습니다.")
                return self.read(previous["id"]), False
            run_id = uuid.uuid4().hex
            secure_directory(self.run_dir(run_id))
            secure_directory(self.run_dir(run_id) / "events")
            state = {
                "id": run_id, "question": request["question"], "status": "queued", "phase": "queued",
                "created_at": now(), "updated_at": now(), "spec": None, "result": None,
                "pending": None, "error": None, "cost_usd": 0.0, "active_seconds": 0.0,
                "steps": 0, "artifacts": [], "snapshot": None,
                "_request": request, "_cancel": False, "_snapshot_id": None,
                "_observations": [], "_history": [], "_asked_fields": [],
                "_unsupported": [], "_calls": 0, "_last_seq": 0,
            }
            self._save(state)
            self._emit(state, {"type": "CUSTOM", "name": "analysis.state", "value": self.public(state)})
            atomic_write(index, encode({"id": run_id, "request": request}))
            return state, True

    def list(self, limit: int = 50) -> list[dict]:
        states = []
        for path in (self.root / "runs").iterdir():
            if ID.fullmatch(path.name) and not path.is_symlink() and path.is_dir():
                try:
                    states.append(self.read(path.name))
                except (OSError, ValueError):
                    continue
        return sorted(states, key=lambda s: s["created_at"], reverse=True)[:limit]

    def _emit(self, state: dict, event: dict) -> dict:
        # Sequence is derived from durable event files, so a crash between event
        # and state writes cannot overwrite or reuse an existing event number.
        directory = self.run_dir(state["id"]) / "events"
        previous = max((int(p.stem) for p in directory.iterdir()
                        if p.suffix == ".json" and p.stem.isdigit()), default=0)
        seq = previous + 1
        event = {**event, "seq": seq, "timestamp": int(datetime.now().timestamp() * 1000)}
        atomic_write(directory / f"{seq:08d}.json", encode(event))
        return event

    def emit(self, run_id: str, event: dict) -> dict:
        with self.lock(run_id):
            return self._emit(self.read(run_id), event)

    def events(self, run_id: str, after: int = 0) -> list[dict]:
        directory = self.run_dir(run_id) / "events"
        return [read_json(directory, p.name) for p in sorted(directory.iterdir())
                if p.suffix == ".json" and p.stem.isdigit() and int(p.stem) > after]

    def register_artifact(self, run_id: str, workspace: Path, relative: str) -> dict:
        suffix = Path(relative).suffix.lower()
        if suffix not in {".json", ".csv", ".png"}:
            raise StoreError("JSON, CSV, PNG 산출물만 제공할 수 있습니다.")
        data = read_bytes(workspace, relative)
        if suffix == ".json":
            data = encode(json.loads(data, parse_constant=lambda v: (_ for _ in ()).throw(StoreError(v))))
        elif suffix == ".csv":
            rows = csv.reader(io.StringIO(data.decode("utf-8-sig")))
            output = io.StringIO()
            writer = csv.writer(output)
            for row in rows:
                writer.writerow(["'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                                 else value for value in row])
            data = output.getvalue().encode("utf-8-sig")
        elif not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise StoreError("Invalid PNG")
        artifact_id = uuid.uuid4().hex
        dest = self.run_dir(run_id) / "artifacts" / f"{artifact_id}{suffix}"
        atomic_write(dest, data)
        artifact = {"id": artifact_id, "name": Path(relative).name, "kind": suffix[1:], "size": len(data)}
        self.mutate(run_id, lambda s: s["artifacts"].append(artifact))
        return artifact

    def artifact(self, run_id: str, artifact_id: str) -> tuple[dict, bytes]:
        if not ID.fullmatch(artifact_id):
            raise StoreError("Invalid artifact ID")
        artifact = next((a for a in self.read(run_id)["artifacts"] if a["id"] == artifact_id), None)
        if artifact is None:
            raise FileNotFoundError(artifact_id)
        return artifact, read_bytes(self.run_dir(run_id), f"artifacts/{artifact_id}.{artifact['kind']}")
