"""Chat usage reservations on the single-path candidate's PG (development security.trial_quota, same interface).

Anonymous trial chats (actor = cookie hash) and member chats (actor = account hash, trial_identity) charge the
same atomic reservation: lifetime per actor, per network and global per admission UTC day, and in-flight
slots. Usage metadata only, never chat content; no timeout refund (a crashed worker is reconciled later, as in
development). SQLite's BEGIN IMMEDIATE becomes one transaction-scoped advisory lock for admission, and a row
lock for each state transition.
"""
import secrets
import time
from datetime import datetime, timezone
from typing import Callable

from pipeline.postgres_graph_fixture import _guard
from security.trial_quota import InvalidTransition, QuotaExceeded, TrialPolicy, TrialQuota

LOCK = 'chat-quota-admission'


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('chat_quota_reservations')").fetchone()[0] is not None:
            raise ValueError('Chat quota already initialized')
        conn.execute("CREATE TABLE chat_quota_reservations (id TEXT PRIMARY KEY,actor_hash TEXT NOT NULL,network_hash TEXT NOT NULL,"
                     "utc_day TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('reserved','running','finished','released')),"
                     'created_at TIMESTAMPTZ NOT NULL DEFAULT now())')
        conn.execute('CREATE INDEX chat_quota_actor ON chat_quota_reservations(actor_hash,state)')
        conn.execute('CREATE INDEX chat_quota_network ON chat_quota_reservations(network_hash,utc_day,state)')
        conn.execute('CREATE INDEX chat_quota_day ON chat_quota_reservations(utc_day,state)')
        conn.execute('CREATE INDEX chat_quota_state ON chat_quota_reservations(state)')


class PostgreSQLTrialQuota:
    def __init__(self, connect, *, policy: TrialPolicy, clock: Callable[[], float] = time.time):
        if not isinstance(policy, TrialPolicy):
            raise ValueError('TrialPolicy required')
        self.connect = connect
        self.policy = policy
        self._clock = clock

    _validate_hash = staticmethod(TrialQuota._validate_hash)

    def reserve(self, *, actor_hash: str, network_hash: str) -> str:
        """Charge all limits atomically, returning an opaque reservation ID."""
        self._validate_hash(actor_hash)
        self._validate_hash(network_hash)
        with self.connect() as conn, conn.transaction():
            _guard(conn)
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (LOCK,))
            day = datetime.fromtimestamp(self._clock(), timezone.utc).date().isoformat()
            checks = (
                ('actor', "actor_hash=%s AND state != 'released'", (actor_hash,), self.policy.per_actor_limit),
                ('network_day', "network_hash=%s AND utc_day=%s AND state != 'released'",
                 (network_hash, day), self.policy.per_network_day_limit),
                ('global_day', "utc_day=%s AND state != 'released'", (day,), self.policy.global_day_limit),
                ('in_flight', "state IN ('reserved','running')", (), self.policy.max_in_flight),
            )
            for reason, predicate, params, limit in checks:
                if conn.execute('SELECT count(*) FROM chat_quota_reservations WHERE ' + predicate, params).fetchone()[0] >= limit:
                    raise QuotaExceeded(reason)
            reservation_id = secrets.token_hex(32)
            conn.execute("INSERT INTO chat_quota_reservations(id,actor_hash,network_hash,utc_day,state) VALUES (%s,%s,%s,%s,'reserved')",
                         (reservation_id, actor_hash, network_hash, day))
            return reservation_id

    def remaining(self, actor_hash: str) -> int:
        """Display-only snapshot; only reserve() authorizes an execution."""
        self._validate_hash(actor_hash)
        with self.connect() as conn:
            _guard(conn)
            used = conn.execute("SELECT count(*) FROM chat_quota_reservations WHERE actor_hash=%s AND state!='released'",
                                (actor_hash,)).fetchone()[0]
        return max(0, self.policy.per_actor_limit - used)

    def state(self, reservation_id: str) -> str:
        """Internal dispatcher verification, never a public lookup endpoint."""
        self._validate_hash(reservation_id)
        with self.connect() as conn:
            _guard(conn)
            row = conn.execute('SELECT state FROM chat_quota_reservations WHERE id=%s', (reservation_id,)).fetchone()
        if row is None:
            raise LookupError('Unknown reservation')
        return row[0]

    def _transition(self, reservation_id: str, source: str, target: str) -> bool:
        self._validate_hash(reservation_id)
        with self.connect() as conn, conn.transaction():
            _guard(conn)
            row = conn.execute('SELECT state FROM chat_quota_reservations WHERE id=%s FOR UPDATE', (reservation_id,)).fetchone()
            if row is None:
                raise LookupError('Unknown reservation')
            if row[0] == target:
                return False
            if row[0] != source:
                raise InvalidTransition('Reservation transition not allowed')
            conn.execute('UPDATE chat_quota_reservations SET state=%s WHERE id=%s', (target, reservation_id))
            return True

    def mark_started(self, reservation_id: str) -> bool:
        """Only a True result authorizes the broker to invoke the provider."""
        return self._transition(reservation_id, 'reserved', 'running')

    def release_before_start(self, reservation_id: str) -> bool:
        return self._transition(reservation_id, 'reserved', 'released')

    def finish(self, reservation_id: str) -> bool:
        return self._transition(reservation_id, 'running', 'finished')
