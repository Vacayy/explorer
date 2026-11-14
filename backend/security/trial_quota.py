"""Atomic anonymous trial admission; stores usage metadata, never chat content.

Callers supply server-derived HMAC hashes, not client-chosen identifiers. Format
validation cannot establish their provenance. Transition methods are internal
broker operations, not user-authorized endpoints. The broker must mark_started
before invoking a provider. There is deliberately no timeout refund/reaper:
crashed workers require later reconciliation proving execution has stopped.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Callable


@dataclass(frozen=True, kw_only=True)
class TrialPolicy:
    per_actor_limit: int = 3
    per_network_day_limit: int
    global_day_limit: int
    max_in_flight: int

    def __post_init__(self):
        for value in (self.per_actor_limit, self.per_network_day_limit,
                      self.global_day_limit, self.max_in_flight):
            if type(value) is not int or not 0 < value <= 2**31 - 1:
                raise ValueError('Quota limits must be positive bounded integers')


class QuotaExceeded(Exception):
    """Reason is a fixed policy name, with no input identifiers or content."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class InvalidTransition(Exception):
    pass


class TrialQuota:
    def __init__(self, path: Path, *, policy: TrialPolicy,
                 clock: Callable[[], float] = time.time):
        if not isinstance(policy, TrialPolicy):
            raise ValueError('TrialPolicy required')
        self.path = Path(path).absolute()
        self.policy = policy
        self._clock = clock

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=10)
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        """Provision an explicit, separate database; never create its parent."""
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with self._connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables:
                if tables != {'trial_metadata', 'trial_reservations'}:
                    raise ValueError('Not a trial quota database')
                if conn.execute('SELECT version FROM trial_metadata').fetchall() != [(1,)]:
                    raise ValueError('Unsupported trial quota schema')
            else:
                conn.execute('CREATE TABLE trial_metadata (version INTEGER NOT NULL)')
                conn.execute('INSERT INTO trial_metadata VALUES (1)')
                conn.execute("""CREATE TABLE trial_reservations (
                    id TEXT PRIMARY KEY, actor_hash TEXT NOT NULL, network_hash TEXT NOT NULL,
                    utc_day TEXT NOT NULL, state TEXT NOT NULL
                    CHECK(state IN ('reserved','running','finished','released')))""")
                conn.execute('CREATE INDEX trial_actor ON trial_reservations(actor_hash,state)')
                conn.execute('CREATE INDEX trial_network ON trial_reservations(network_hash,utc_day,state)')
                conn.execute('CREATE INDEX trial_day ON trial_reservations(utc_day,state)')
                conn.execute('CREATE INDEX trial_state ON trial_reservations(state)')
            os.chmod(self.path, 0o600)

    @staticmethod
    def _validate_hash(value: str) -> None:
        if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
            raise ValueError('Expected server-derived lowercase hexadecimal hash')

    def reserve(self, *, actor_hash: str, network_hash: str) -> str:
        """Charge all limits atomically, returning an opaque reservation ID.

        Actor quota is lifetime; network/global quotas use the admission UTC day.
        In-flight slots span days. All processes must use the same policy.
        """
        self._validate_hash(actor_hash)
        self._validate_hash(network_hash)
        with self._connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            day = datetime.fromtimestamp(self._clock(), timezone.utc).date().isoformat()
            checks = (
                ('actor', 'actor_hash=? AND state != \'released\'', (actor_hash,), self.policy.per_actor_limit),
                ('network_day', 'network_hash=? AND utc_day=? AND state != \'released\'',
                 (network_hash, day), self.policy.per_network_day_limit),
                ('global_day', 'utc_day=? AND state != \'released\'', (day,), self.policy.global_day_limit),
                ('in_flight', "state IN ('reserved','running')", (), self.policy.max_in_flight),
            )
            for reason, predicate, params, limit in checks:
                count = conn.execute('SELECT count(*) FROM trial_reservations WHERE ' + predicate, params).fetchone()[0]
                if count >= limit:
                    raise QuotaExceeded(reason)
            reservation_id = secrets.token_hex(32)
            conn.execute("INSERT INTO trial_reservations VALUES (?,?,?,?,'reserved')",
                         (reservation_id, actor_hash, network_hash, day))
            return reservation_id

    def _transition(self, reservation_id: str, source: str, target: str) -> bool:
        self._validate_hash(reservation_id)
        with self._connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT state FROM trial_reservations WHERE id=?', (reservation_id,)).fetchone()
            if row is None:
                raise LookupError('Unknown reservation')
            if row[0] == target:
                return False
            if row[0] != source:
                raise InvalidTransition('Reservation transition not allowed')
            conn.execute('UPDATE trial_reservations SET state=? WHERE id=?', (target, reservation_id))
            return True

    def mark_started(self, reservation_id: str) -> bool:
        """Only a True result authorizes the broker to invoke the provider."""
        return self._transition(reservation_id, 'reserved', 'running')

    def release_before_start(self, reservation_id: str) -> bool:
        return self._transition(reservation_id, 'reserved', 'released')

    def finish(self, reservation_id: str) -> bool:
        return self._transition(reservation_id, 'running', 'finished')
