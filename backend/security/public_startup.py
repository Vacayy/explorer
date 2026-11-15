"""Read-only readiness for public API startup; deployment owns schema changes.

Full restore integrity/schema/ownership validation belongs to the deployment
gate. This check never provisions stores, starts private workers or resumes chat.
"""
import os
from pathlib import Path
import sqlite3
import stat

from security.login_flow import AuthConfig
from security.publication_store import PublicationStore
from security.trial_service import configured_trial


def readonly(path, statements):
    path=Path(path)
    info=path.lstat()
    if (not path.is_absolute() or path.resolve()!=path or not stat.S_ISREG(info.st_mode)
            or info.st_nlink!=1 or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600):
        raise ValueError('Private existing public store required')
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)
    try:
        conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        for query,expected in statements:
            rows=conn.execute(query).fetchall()
            if rows!=expected:raise ValueError('Public store not prepared')
    finally:conn.close()


def validate_public_state():
    from config import DB_PATH, MEDIA_PATH
    try:
        auth=AuthConfig.from_environment()
        _,quota,_,_=configured_trial()
        publication=Path(os.environ['EXPLORER_PUBLICATION_DB'])
        macro=Path(os.environ['EXPLORER_PUBLIC_MACRO_DB'])
        paths=[DB_PATH,auth.identity_db,auth.login_db,publication,quota.path,macro]
        if len({path.resolve() for path in paths})!=len(paths):raise ValueError('Separate public stores required')
        if MEDIA_PATH.resolve()!=MEDIA_PATH or not MEDIA_PATH.is_dir():raise ValueError('Existing media required')
        readonly(DB_PATH,[
            ('SELECT owner_id FROM stock_groups LIMIT 0',[]),
            ('SELECT group_id FROM portfolio_transactions LIMIT 0',[]),
            ('SELECT group_id,text,rules_json,notes_json FROM member_portfolio_principles LIMIT 0',[]),
            ('SELECT owner_user_id,doc_id,saved_fingerprint,note FROM member_saved_documents LIMIT 0',[]),
            ('SELECT id,markdown,media_json FROM raw_documents LIMIT 0',[]),
        ])
        for path,table,version in [(auth.identity_db,'identity_metadata',1),
                                    (auth.login_db,'login_metadata',1),
                                    (publication,'publication_metadata',2),
                                    (quota.path,'trial_metadata',1)]:
            readonly(path,[('SELECT version FROM '+table,[(version,)])])
        readonly(macro,[("SELECT value FROM meta WHERE key='schema'",[('public_macro_direct_v1',)])])
        PublicationStore(publication).cursor_cipher()
    except Exception:
        # Do not expose paths, Google configuration, tokens or DB contents in logs.
        raise RuntimeError('Public persistent state is not prepared') from None
