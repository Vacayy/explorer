"""Bounded publication projection with exact bytes and per-document decisions."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
from urllib.parse import urlsplit

from models.public_documents import PublishedAttachment, PublishedDocument
from security.publication_store import PublicationStore, PublicationConflict

MAX_TEXT = 2 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_FILES = 16


class DocumentUnavailable(Exception):
    pass


class ListingBudgetExceeded(Exception):
    pass


@dataclass
class ReadBudget:
    remaining: int = 128 * 1024 * 1024

    def consume(self, size):
        if size > self.remaining:
            raise ListingBudgetExceeded()
        self.remaining -= size


def casefold_match_offset(text, query):
    """Map a Unicode casefold match back to the original string's index."""
    position = text.casefold().find(query.casefold())
    if position <= 0:
        return 0
    offset = 0
    for index, character in enumerate(text):
        offset += len(character.casefold())
        if offset > position:
            return index
    return 0


@dataclass
class Snapshot:
    document: PublishedDocument
    fingerprint: str
    selected_bytes: bytes | None


def _safe_url(value):
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def _media_type(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')): return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return 'image/webp'
    if data.startswith(b'%PDF-'): return 'application/pdf'
    raise DocumentUnavailable()


def _file_bytes(root: Path, relative: str, budget: ReadBudget | None = None):
    # All traversal uses directory FDs and O_NOFOLLOW, including intermediate
    # directories. Never reopen a checked path later for the actual response.
    if (not isinstance(relative, str) or not relative or len(relative) > 1024
            or '\x00' in relative or '\\' in relative or relative.startswith('/')
            or any(p in {'', '.', '..'} for p in relative.split('/'))):
        raise DocumentUnavailable()
    parts = PurePosixPath(relative).parts
    current = os.open(root.resolve(strict=True), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
                raise DocumentUnavailable()
            if budget is not None and info.st_size > budget.remaining:
                raise ListingBudgetExceeded()
            data = bytearray()
            while True:
                chunk = os.read(fd, min(1024 * 1024, MAX_FILE + 1 - len(data)))
                if not chunk: break
                if budget is not None:
                    budget.consume(len(chunk))
                data.extend(chunk)
                if len(data) > MAX_FILE: raise DocumentUnavailable()
            return bytes(data)
        finally:
            os.close(fd)
    finally:
        os.close(current)


class PublicDocuments:
    def __init__(self, source: Path, media_root: Path, store: PublicationStore):
        self.source, self.media_root, self.store = Path(source).absolute(), Path(media_root).absolute(), store
        if self.source.resolve() == self.store.path.resolve():
            raise ValueError('Separate publication store required')

    def collection_enabled(self):
        with sqlite3.connect(self.source.as_uri() + '?mode=ro', uri=True, timeout=3) as conn:
            return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_collection_index'").fetchone() is not None

    @classmethod
    def from_environment(cls):
        from config import DB_PATH, MEDIA_PATH
        name = os.environ.get('EXPLORER_PUBLICATION_DB', '')
        if not name or not Path(name).is_absolute():
            raise ValueError('Publication store not configured')
        return cls(DB_PATH, MEDIA_PATH, PublicationStore(Path(name)))

    def capture(self, doc_id: int, selected: int | None = None, *, budget: ReadBudget | None = None) -> Snapshot:
        try:
            conn = sqlite3.connect(self.source.as_uri() + '?mode=ro', uri=True, timeout=3)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute('PRAGMA query_only=ON')
                conn.execute('BEGIN')
                row = conn.execute('''SELECT id,substr(title,1,1025) title,substr(source_type,1,129) source_type,
                    substr(url,1,4097) url,substr(published_at,1,129) published_at,
                    substr(markdown,1,?) markdown,substr(raw_content,1,?) raw_content,
                    substr(media_json,1,65537) media_json FROM raw_documents WHERE id=?''',
                    (MAX_TEXT + 1, MAX_TEXT + 1, doc_id)).fetchone()
                from security.public_feed import channel_for
                channel = channel_for(conn, row) if row else None
                collection = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_collection_index'").fetchone() is not None
                summary = conn.execute('SELECT summary FROM enrichments WHERE doc_id=? ORDER BY enriched_at DESC,id DESC LIMIT 1', (doc_id,)).fetchone() if collection and row else None
            finally:
                conn.close()
            if not row: raise DocumentUnavailable()
            for field, limit in [('title',1024),('source_type',128),('url',4096),('published_at',128),('media_json',65536)]:
                if row[field] is not None and (not isinstance(row[field], str) or len(row[field]) > limit):
                    raise DocumentUnavailable()
            content = row['markdown'] or row['raw_content'] or ''
            if not isinstance(content, str) or len(content.encode('utf8')) > MAX_TEXT:
                raise DocumentUnavailable()
            if budget is not None:
                budget.consume(len(content.encode('utf8')))
            paths = json.loads(row['media_json']) if row['media_json'] else []
            if not isinstance(paths, list) or len(paths) > MAX_FILES or len(set(paths)) != len(paths):
                raise DocumentUnavailable()
            attachments, manifest, selected_bytes, total = [], [], None, 0
            for index, path in enumerate(paths):
                data = _file_bytes(self.media_root, path, budget) if budget is not None else _file_bytes(self.media_root, path)
                total += len(data)
                if total > MAX_TOTAL: raise DocumentUnavailable()
                media_type = _media_type(data)
                attachments.append(PublishedAttachment(id=index, media_type=media_type, size=len(data),
                    url=f'/api/public/documents/{doc_id}/attachments/{index}'))
                manifest.append({'path':path, 'sha256':hashlib.sha256(data).hexdigest(), 'size':len(data), 'type':media_type})
                if index == selected: selected_bytes = data
            document = PublishedDocument(id=doc_id, title=row['title'] or '', source_type=row['source_type'] or '',
                url=_safe_url(row['url']), published_at=row['published_at'], content=content,
                content_kind='stored_markdown' if row['markdown'] else 'stored_text', attachments=attachments, channel=channel,
                summary=summary[0] if summary else None)
            material = {'version':1, 'document':document.model_dump(mode='json'), 'attachments':manifest}
            if document.summary is None:
                material['document'].pop('summary')
            if channel is None:
                material['document'].pop('channel')  # Preserve old approvals with no additional source metadata.
            fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(',',':')).encode()).hexdigest()
            return Snapshot(document, fingerprint, selected_bytes)
        except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
            raise DocumentUnavailable() from exc

    def preview(self, doc_id):
        snapshot = self.capture(doc_id)
        record = self.store.get(doc_id)
        return {'fingerprint': snapshot.fingerprint, 'version': record['version'] if record else 0, 'document': snapshot.document,
                'attachment_previews': [f'/api/operator/publications/{doc_id}/preview/{snapshot.fingerprint}/attachments/{a.id}' for a in snapshot.document.attachments]}

    def approve(self, doc_id, request, actor):
        snapshot = self.capture(doc_id)
        if snapshot.fingerprint != request.fingerprint:
            raise PublicationConflict()
        from security.public_feed import feed_metadata
        return self.store.approve(doc_id, snapshot.fingerprint, request.expected_version, actor, request.rights_basis,
                                  feed_metadata=feed_metadata(snapshot.document))

    def published(self, doc_id, selected=None, *, budget=None):
        if self.collection_enabled():
            with sqlite3.connect(self.source.as_uri() + '?mode=ro', uri=True, timeout=3) as conn:
                if conn.execute('SELECT 1 FROM public_collection_index WHERE doc_id=?', (doc_id,)).fetchone() is None:
                    raise DocumentUnavailable()
            snapshot = self.capture(doc_id, selected, budget=budget)
            if selected is not None and snapshot.selected_bytes is None:
                raise DocumentUnavailable()
            return snapshot
        record = self.store.get(doc_id)
        if record is None or record['status'] != 'approved':
            raise DocumentUnavailable()
        snapshot = self.capture(doc_id, selected, budget=budget) if budget is not None else self.capture(doc_id, selected)
        if snapshot.fingerprint != record['fingerprint'] or self.store.get(doc_id) != record:
            raise DocumentUnavailable()
        if selected is not None and snapshot.selected_bytes is None:
            raise DocumentUnavailable()
        return snapshot

    def listing(self, query='', cursor=None, limit=10, *, budget=None, snapshots=None):
        if self.collection_enabled():
            return self.collection_listing(query, cursor, limit, budget=budget, snapshots=snapshots)
        # Only approved candidates enter the read path. No private full-text
        # index, related-document lookup, or count is exposed.
        self.store.cursor_cipher()  # Explicit v2 preparation required even for an empty first page.
        if snapshots is not None:
            snapshots.clear()
        needle = query.strip().casefold()
        before = self.store.decode_cursor(cursor, needle) if cursor else None
        candidates = self.store.candidates(before, 101)
        items, fingerprints = [], {}
        budget = ReadBudget() if budget is None else budget
        more = False
        progress = None
        for index, doc_id in enumerate(candidates):
            if index == 100:
                more = True
                break
            try:
                snapshot = self.published(doc_id, budget=budget)
            except DocumentUnavailable:
                progress = doc_id
                continue
            except ListingBudgetExceeded:
                more = True
                break
            progress = doc_id
            document = snapshot.document
            if needle and needle not in document.title.casefold() and needle not in document.content.casefold():
                continue
            # Normalize whitespace only; never generate AI summaries or render
            # source Markdown/HTML in the listing.
            text = ' '.join(document.content.split())
            position = casefold_match_offset(text, needle) if needle else 0
            start = max(0, position - 80)
            items.append(dict(id=doc_id, title=document.title, source_type=document.source_type,
                              published_at=document.published_at, snippet=text[start:start+240]))
            fingerprints[doc_id] = snapshot.fingerprint
            if snapshots is not None:
                snapshots[doc_id] = snapshot
            if len(items) == limit:
                # Continuation does not assert more public matches exist.
                more = True
                break
        # A later candidate can take time to read. Reflect approval/revocation
        # changes to earlier entries before emitting their title/snippet.
        items = [item for item in items if (record := self.store.get(item['id']))
                 and record['status'] == 'approved' and record['fingerprint'] == fingerprints[item['id']]]
        if snapshots is not None:
            retained = {item['id'] for item in items}
            for doc_id in list(snapshots):
                if doc_id not in retained:
                    del snapshots[doc_id]
        if more and progress is None:
            raise ListingBudgetExceeded()
        return {'items': items, 'next_cursor': self.store.encode_cursor(progress, needle) if more else None}

    def collection_listing(self, query='', cursor=None, limit=10, *, budget=None, snapshots=None):
        needle = query.strip().casefold()
        before = self.store.decode_cursor(cursor, needle) if cursor else None
        with sqlite3.connect(self.source.as_uri() + '?mode=ro', uri=True, timeout=3) as conn:
            conn.execute('PRAGMA query_only=ON')
            conn.create_function('casefold', 1, lambda value: (value or '').casefold(), deterministic=True)
            rows = conn.execute('''SELECT i.doc_id FROM public_collection_index i
                JOIN raw_documents d ON d.id=i.doc_id
                WHERE (? IS NULL OR i.doc_id<?) AND (?='' OR instr(casefold(d.title),?)>0
                    OR instr(casefold(coalesce(nullif(d.markdown,''),d.raw_content,'')),?)>0)
                ORDER BY i.doc_id DESC LIMIT ?''', (before, before, needle, needle, needle, limit+1)).fetchall()
        if snapshots is not None:
            snapshots.clear()
        items = []
        budget = ReadBudget() if budget is None else budget
        for (doc_id,) in rows[:limit]:
            snapshot = self.published(doc_id, budget=budget)
            doc = snapshot.document
            content = ' '.join(doc.content.split())
            start = max(0, casefold_match_offset(content, needle)-80) if needle else 0
            items.append(dict(id=doc_id,title=doc.title,source_type=doc.source_type,
                              published_at=doc.published_at,snippet=content[start:start+240]))
            if snapshots is not None:
                snapshots[doc_id] = snapshot
        return {'items':items, 'next_cursor':self.store.encode_cursor(items[-1]['id'], needle) if len(rows)>limit and items else None}
