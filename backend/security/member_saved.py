"""Member references only; publication metadata is resolved on every read."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import errno
from security.public_documents import DocumentUnavailable, ReadBudget


class SavedUnavailable(Exception):
    pass


class SavedLimit(Exception):
    pass


def initialize_member_saved(conn):
    """Explicit deployment initialization; never called from request handlers."""
    conn.execute('''CREATE TABLE IF NOT EXISTS member_saved_documents(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_user_id TEXT NOT NULL, doc_id INTEGER NOT NULL CHECK(doc_id>0),
        saved_fingerprint TEXT NOT NULL,
        note TEXT CHECK(note IS NULL OR length(note)<=2000),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(owner_user_id,doc_id))''')


class MemberSaved:
    def __init__(self, source, owner, documents):
        if not isinstance(owner,str) or not owner:
            raise ValueError('Explicit member required')
        self.source, self.owner, self._documents = Path(source).absolute(), owner, documents

    @property
    def documents(self):
        if callable(self._documents): self._documents=self._documents()
        return self._documents

    @contextmanager
    def connection(self, write=False):
        conn=sqlite3.connect(self.source.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=5)
        conn.row_factory=sqlite3.Row
        try:
            if not write: conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield conn
            if write: conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def projection(row,snapshot=None):
        result={k:row[k] for k in ('id','doc_id','note','created_at')}
        result.update(title=None,url=None,current_url=None,available=False,status='unavailable')
        if snapshot is not None:
            if row['saved_fingerprint']==snapshot.fingerprint:
                result.update(title=snapshot.document.title,url=f"/doc/{row['doc_id']}",available=True,status='available')
            else:
                result.update(status='changed',current_url=f"/doc/{row['doc_id']}")
        return result

    def item(self,row,budget,fingerprints):
        try:
            snapshot=self.documents.published(row['doc_id'],budget=budget)
        except DocumentUnavailable as exc:
            # Missing/changed/revoked documents are partial results, DB outages are not.
            if isinstance(exc.__cause__,sqlite3.Error): raise exc.__cause__
            if isinstance(exc.__cause__,OSError) and exc.__cause__.errno not in {errno.ENOENT,errno.ENOTDIR,errno.ELOOP}:
                raise exc.__cause__
            return self.projection(row)
        fingerprints[row['doc_id']]=snapshot.fingerprint
        return self.projection(row,snapshot)

    def listing(self,offset=0,limit=20,doc_id=None):
        with self.connection() as conn:
            clause='owner_user_id=?'; params=[self.owner]
            if doc_id is not None:
                clause+=' AND doc_id=?';params.append(doc_id)
            rows=conn.execute(f'SELECT id,doc_id,note,created_at,saved_fingerprint FROM member_saved_documents WHERE {clause} '
                              'ORDER BY id DESC LIMIT ? OFFSET ?',(*params,limit+1,offset)).fetchall()
        budget=ReadBudget()
        fingerprints={}
        items=[self.item(row,budget,fingerprints) for row in rows[:limit]]
        for item in items:
            if item['status']!='unavailable':
                record=self.documents.store.get(item['doc_id'])
                if not record or record['status']!='approved' or record['fingerprint']!=fingerprints[item['doc_id']]:
                    item.update(available=False,title=None,url=None,current_url=None,status='unavailable')
        return {'items':items,'next_offset':offset+limit if len(rows)>limit else None}

    def add(self,body):
        budget=ReadBudget()
        with self.connection(write=True) as conn:
            row=conn.execute('SELECT * FROM member_saved_documents WHERE owner_user_id=? AND doc_id=?',
                             (self.owner,body.doc_id)).fetchone()
            # Even an idempotent POST must pass current publication checks.
            try: snapshot=self.documents.published(body.doc_id,budget=budget)
            except DocumentUnavailable as exc:
                if isinstance(exc.__cause__,sqlite3.Error): raise exc.__cause__
                if isinstance(exc.__cause__,OSError) and exc.__cause__.errno not in {errno.ENOENT,errno.ENOTDIR,errno.ELOOP}:
                    raise exc.__cause__
                raise SavedUnavailable() from None
            if row is None:
                count=conn.execute('SELECT count(*) FROM member_saved_documents WHERE owner_user_id=?',(self.owner,)).fetchone()[0]
                if count>=200: raise SavedLimit()
                ident=conn.execute('INSERT INTO member_saved_documents(owner_user_id,doc_id,note,saved_fingerprint) VALUES(?,?,?,?)',
                                   (self.owner,body.doc_id,body.note,snapshot.fingerprint)).lastrowid
                row=conn.execute('SELECT * FROM member_saved_documents WHERE id=?',(ident,)).fetchone()
            # Do not reread potentially large attachments just to return metadata.
            record=self.documents.store.get(body.doc_id)
            approved=bool(record and record['status']=='approved' and record['fingerprint']==snapshot.fingerprint)
            return self.projection(row,snapshot if approved else None)

    def change(self,ident,body=None):
        with self.connection(write=True) as conn:
            if body is None:
                cursor=conn.execute('DELETE FROM member_saved_documents WHERE id=? AND owner_user_id=?',(ident,self.owner))
            else:
                cursor=conn.execute('UPDATE member_saved_documents SET note=? WHERE id=? AND owner_user_id=?',(body.note,ident,self.owner))
            if not cursor.rowcount: raise SavedUnavailable()
