"""Keep newly decided Telegram grouping marks consistent across PG and a work copy."""
from psycopg.types.json import Jsonb

from database import get_connection
from pipeline.postgres_graph_fixture import _guard


class GroupMarkConflict(RuntimeError):
    """Stop collection; a partially written or conflicting decision needs reconciliation."""


class GroupMarks:
    def __init__(self, factory, sqlite_factory=get_connection):
        self.factory, self.sqlite_factory = factory, sqlite_factory

    @staticmethod
    def _rows(pg, db, channel, msg_id):
        local = db.execute('SELECT channel,msg_id,joins_prev,model,judged_at FROM telegram_group_marks '
                           'WHERE channel=? AND msg_id=?', (channel, msg_id)).fetchone()
        rows = pg.execute("SELECT row_data FROM legacy_supplement_rows WHERE table_name='telegram_group_marks' "
                          "AND row_data->>'channel'=%s AND row_data->>'msg_id'=%s", (channel, str(msg_id))).fetchall()
        if len(rows) > 1:
            raise GroupMarkConflict('Duplicate grouping mark in PG')
        remote = rows[0][0] if rows else None
        if (local is None) != (remote is None):
            raise GroupMarkConflict('Grouping mark is missing from one copy')
        if local is None:
            return None
        values = tuple(local)
        expected = (remote.get('channel'), remote.get('msg_id'), remote.get('joins_prev'),
                    remote.get('model'), remote.get('judged_at'))
        if values != expected:
            raise GroupMarkConflict('Grouping marks differ between copies')
        return {'joins_prev': bool(values[2])}

    def get(self, channel, msg_id):
        db = self.sqlite_factory()
        try:
            with self.factory() as pg:
                _guard(pg)
                return self._rows(pg, db, channel, msg_id)
        finally:
            db.close()

    def put(self, channel, msg_id, verdict, model):
        db = self.sqlite_factory()
        try:
            db.execute('BEGIN IMMEDIATE')
            with self.factory() as pg, pg.transaction():
                _guard(pg)
                pg.execute("SELECT pg_advisory_xact_lock(hashtextextended('supplement:telegram_group_marks',0))")
                if not pg.execute("SELECT 1 FROM legacy_supplement_tables WHERE table_name='telegram_group_marks'").fetchone():
                    raise GroupMarkConflict('Grouping mark supplement is missing')
                prior = self._rows(pg, db, channel, msg_id)
                if prior is not None:
                    result = prior['joins_prev']
                else:
                    db.execute('INSERT INTO telegram_group_marks(channel,msg_id,joins_prev,model) VALUES (?,?,?,?)',
                               (channel, msg_id, int(verdict), model))
                    row = db.execute('SELECT channel,msg_id,joins_prev,model,judged_at FROM telegram_group_marks '
                                     'WHERE channel=? AND msg_id=?', (channel, msg_id)).fetchone()
                    data = dict(zip(('channel', 'msg_id', 'joins_prev', 'model', 'judged_at'), tuple(row)))
                    pg.execute("INSERT INTO legacy_supplement_rows(table_name,row_ordinal,row_data) VALUES "
                               "('telegram_group_marks',(SELECT COALESCE(max(row_ordinal),-1)+1 FROM legacy_supplement_rows "
                               "WHERE table_name='telegram_group_marks'),%s)", (Jsonb(data),))
                    pg.execute("UPDATE legacy_supplement_tables SET row_count=row_count+1 WHERE table_name='telegram_group_marks'")
                    result = bool(verdict)
            db.commit()
            return result
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
