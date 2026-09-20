"""Transactional application records, wholly separate from the source database."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .store import Conflict, ID, StoreError, encode, now, secure_directory


class DiscoveryStore:
    def __init__(self, root: Path):
        self.root = secure_directory(root)
        self.path = self.root / "discovery.sqlite"
        if self.path.is_symlink() or (self.path.exists() and self.path.stat().st_nlink != 1):
            raise StoreError("Unsafe discovery database")
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(kind, id)
                );
                CREATE TABLE IF NOT EXISTS requests (
                    scope TEXT NOT NULL, key TEXT NOT NULL, body TEXT NOT NULL,
                    kind TEXT NOT NULL, id TEXT NOT NULL,
                    PRIMARY KEY(scope, key)
                );
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=15)
        try:
            conn.execute("PRAGMA busy_timeout=15000")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _get(conn, kind: str, record_id: str) -> dict:
        if not ID.fullmatch(record_id):
            raise StoreError("잘못된 기록 ID입니다.")
        row = conn.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        if row is None:
            raise FileNotFoundError(record_id)
        return json.loads(row[0])

    @staticmethod
    def put(conn, kind: str, record: dict):
        record["updated_at"] = now()
        conn.execute("INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
                     (kind, record["id"], encode(record).decode()))

    def get(self, kind: str, record_id: str) -> dict:
        with self.connection() as conn:
            return self._get(conn, kind, record_id)

    def list(self, kind: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute("SELECT body FROM records WHERE kind=?", (kind,)).fetchall()
        return sorted((json.loads(row[0]) for row in rows), key=lambda r: r["created_at"], reverse=True)

    def once(self, scope: str, request: dict, kind: str, create) -> dict:
        """Result and request receipt commit together; changed retries conflict."""
        body = json.dumps(request, ensure_ascii=False, sort_keys=True, allow_nan=False)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute("SELECT body,kind,id FROM requests WHERE scope=? AND key=?",
                                 (scope, request["request_key"])).fetchone()
            if prior:
                if prior[0] != body:
                    raise Conflict("같은 요청 키의 내용을 변경할 수 없습니다.")
                return self._get(conn, prior[1], prior[2])
            result = create(conn)
            self.put(conn, kind, result)
            conn.execute("INSERT INTO requests VALUES (?,?,?,?,?)",
                         (scope, request["request_key"], body, kind, result["id"]))
            return result

    def mutate(self, kind: str, record_id: str, change) -> dict:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            value = self._get(conn, kind, record_id)
            change(value)
            self.put(conn, kind, value)
            return value

    @staticmethod
    def fresh(**fields) -> dict:
        return {"id": uuid.uuid4().hex, "created_at": now(), "updated_at": now(), **fields}
