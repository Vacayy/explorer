"""Capture one existing blog source snapshot without changing the published document."""
import requests


def stage_one(queue, connector, is_known, before_attempt, *, max_requests=3):
    selected = None
    for _seq, ref in queue.revision_refs('blog'):
        post = ref.meta.get('post') or {}
        identity = post.get('url') or post.get('title') or ''
        old = queue.conn.execute('SELECT defer_reason FROM pending WHERE source_type=? AND source_id=?',
                                 ('blog', identity)).fetchone()
        if identity and (not old or old[0] != 'analysis') and is_known('blog', identity):
            selected = (ref, identity)
            break
    if selected is None:
        return {'revision_snapshot': 0, 'revision_requests': 0}
    ref, identity = selected
    before_attempt()  # the one-shot flag is gone before any source request
    send, made, refused = requests.Session.send, [0], [False]
    def limited(session, request, **kwargs):
        if made[0] >= max_requests:
            refused[0] = True
            raise RuntimeError('Revision source request limit reached')
        made[0] += 1
        return send(session, request, **kwargs)
    requests.Session.send = limited
    try:
        doc = connector.fetch_post(ref)
    finally:
        requests.Session.send = send
    if refused[0] or doc.source_type != 'blog' or doc.source_id != identity or not (doc.raw_content or '').strip():
        raise ValueError('Revision snapshot was not safely captured')
    queue.enqueue('blog', ref.key, doc)
    row = queue.conn.execute('SELECT seq,revision_pending FROM pending WHERE source_type=? AND source_id=?',
                             ('blog', identity)).fetchone()
    if not row:
        raise ValueError('Revision snapshot is missing after staging')
    if not row[1]:
        queue.defer_revision(row[0])
    return {'revision_snapshot': 1, 'revision_requests': made[0]}
