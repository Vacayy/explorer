"""Company links prepared against approved document revisions, with no private enrichment."""
from contextlib import closing

from pipeline.company_evidence import evidence_response, plain_text
from security.public_documents import PublicDocuments, DocumentUnavailable, ReadBudget
from security.public_us_season import connection, _company


def stored_evidence(company, *, path=None, service=None, q='', **filters):
    with closing(connection(path)) as conn:
        company = _company(conn, company)
        links = conn.execute('''SELECT doc_id, fingerprint FROM public_company_evidence
            WHERE ticker=? ORDER BY doc_id''', (company['ticker'],)).fetchall()
    service = service or PublicDocuments.from_environment()
    budget, candidates, fingerprints = ReadBudget(), [], {}
    needle = q.strip().lower()
    for link in links:
        try:
            snapshot = service.published(link['doc_id'], budget=budget)
        except DocumentUnavailable:
            continue
        if snapshot.fingerprint != link['fingerprint']:
            continue
        doc = snapshot.document
        fingerprints[doc.id] = snapshot.fingerprint
        candidates.append(dict(id=f'doc:{doc.id}', doc_id=doc.id,
            source_type=doc.source_type, source_id='',
            publisher=doc.channel.name if doc.channel else doc.source_type,
            title=plain_text(doc.title), url=doc.url or '', published_at=doc.published_at,
            excerpt=plain_text(doc.content[:1500])[:600], relation='기업 연결 자료',
            matched=needle in (doc.title + ' ' + doc.content).lower()))
    # Recheck the entire input before computing any count, coverage or flow.
    candidates = [row for row in candidates if
        (record := service.store.get(row['doc_id'])) and record['status'] == 'approved'
        and record['fingerprint'] == fingerprints[row['doc_id']]]
    return evidence_response(candidates, market='us', **filters)
