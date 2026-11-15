"""Stored narrative text/version reads without questions, holdings or generation."""
from contextlib import closing
from pathlib import Path
import sqlite3
from config import DB_PATH
from pipeline.narrative import _version_diff, causal_subgraph, list_narratives
from pipeline.world_reads import narrative_changes

COLUMNS = {
    'signals': {'entity_id','signal_type','date','payload_json'},
    'narratives': {'id','topic','title','body','version','category','kind','created_at','superseded_at','drift_summary','change_summary'},
    'entities': {'id','name','type'},
    'entity_relations': {'id','src_id','dst_id','rel_type','narrative_id','mechanism','reference_period','time_orientation','confidence','effect_direction','effect_strength','geo_scope'},
    'narrative_edge_evidence': {'entity_relation_id','narrative_id'},
}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT: return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and (database == 'main' or database is None and column == '') and table in COLUMNS and (column == '' or column in COLUMNS[table]):return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column in {'count','max','coalesce','datetime'}:return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connection(path=None):
    conn=sqlite3.connect(Path(path or DB_PATH).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN');conn.set_authorizer(authorize)
    return conn


def changes(days=7,limit=20,*,path=None):
    with closing(connection(path)) as conn:return narrative_changes(conn,days,limit,public=True)


def stored_body(topic=None,version_id=None,*,path=None):
    with closing(connection(path)) as conn:
        field,value=('id',version_id) if version_id is not None else ('topic',topic)
        row=conn.execute('SELECT id,title,body,category,version,created_at FROM narratives WHERE '+field+"=? AND COALESCE(kind,'topic')='topic' ORDER BY version DESC LIMIT 1",(value,)).fetchone()
    if not row:return {'status':'not_found'}
    return dict(status='cached',title=row['title'],narrative=row['body'],category=row['category'],version=row['version'],created_at=row['created_at'],narrative_id=row['id'],stale=False)


def versions(topic,*,path=None):
    with closing(connection(path)) as conn:
        return [dict(r) for r in conn.execute("SELECT id,version,title,category,created_at,superseded_at FROM narratives WHERE topic=? AND COALESCE(kind,'topic')='topic' ORDER BY version DESC",(topic,))]


def graph(narrative_id,*,path=None):
    with closing(connection(path)) as conn:
        row=conn.execute("SELECT id FROM narratives WHERE id=? AND COALESCE(kind,'topic')='topic'",(narrative_id,)).fetchone()
        return causal_subgraph(conn,narrative_id,public=True) if row else {"nodes":[],"edges":[]}


def diff(narrative_id,*,path=None):
    with closing(connection(path)) as conn:
        result=_version_diff(conn,narrative_id,public=True)
        row=conn.execute('SELECT drift_summary FROM narratives WHERE id=?',(narrative_id,)).fetchone()
        result['summary']=row[0] if row and result['status']=='ok' and (result['added_edges'] or result['removed_edges']) else None
        return result


def index(*,path=None):
    with closing(connection(path)) as conn:return {"items":list_narratives(conn)}
