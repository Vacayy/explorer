"""Memory-only public evidence for trial chat; no provider or private retrieval."""
from dataclasses import dataclass
import json

from security.public_documents import DocumentUnavailable, ListingBudgetExceeded, ReadBudget, casefold_match_offset

MAX_DOCUMENTS = 4
MAX_PAGES = 3
READ_BYTES = 128 * 1024 * 1024
CONTEXT_BYTES = 24 * 1024


class EvidenceUnavailable(Exception):
    pass


class EvidenceChanged(Exception):
    pass


class InvalidAnswer(Exception):
    pass


def _cut(text, size):
    return text.encode('utf8')[:size].decode('utf8', errors='ignore')


@dataclass(frozen=True)
class EvidenceSource:
    reference: str
    document_id: int
    fingerprint: str
    title: str
    excerpt: str


@dataclass(frozen=True)
class EvidenceContext:
    sources: tuple[EvidenceSource, ...]
    partial: bool

    def model_input(self):
        # Local paths, source URLs, private fields and approval identities are absent.
        return json.dumps([{'reference': s.reference, 'title': _cut(s.title, 512),
                            'content': s.excerpt} for s in self.sources], ensure_ascii=False)


class PublicEvidence:
    def __init__(self, documents):
        self.documents = documents

    def gather(self, query='', document_ids=()):
        if not isinstance(query, str) or len(query) > 120:
            raise ValueError('Invalid public evidence query')
        query.encode('utf8')
        if not isinstance(document_ids, (list, tuple)) or len(document_ids) > MAX_DOCUMENTS:
            raise ValueError('Invalid public document selection')
        ids = tuple(document_ids)
        if (any(type(i) is not int or not 0 < i < 2**63 for i in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('Invalid public document selection')
        budget = ReadBudget(READ_BYTES)
        sources, seen, cursor = [], set(), None
        partial = False

        def append(doc_id, snapshot=None):
            nonlocal partial
            snapshot = snapshot or self.documents.published(doc_id, budget=budget)
            document = snapshot.document
            if not document.content.strip():
                return
            content = document.content
            position = casefold_match_offset(content, query.strip()) if query.strip() else 0
            start = max(0, position - 200)
            excerpt = _cut(content[start:], 4096)
            partial |= start > 0 or excerpt != content or _cut(document.title, 512) != document.title
            reference = 'D' + str(len(sources) + 1)
            def candidate(text):
                return EvidenceSource(reference, doc_id, snapshot.fingerprint, document.title, text)
            # JSON escaping also counts toward the actual serialized context budget.
            while excerpt and len(EvidenceContext(tuple([*sources, candidate(excerpt)]), partial).model_input().encode('utf8')) > CONTEXT_BYTES:
                excerpt = excerpt[:len(excerpt)//2]
                partial = True
            if not excerpt:
                partial = True
                return
            sources.append(candidate(excerpt))

        try:
            if ids:
                for doc_id in ids:
                    append(doc_id)  # Explicit selection must fail if any document is unavailable.
            else:
                for _ in range(MAX_PAGES):
                    snapshots = {}
                    page = self.documents.listing(query, cursor, MAX_DOCUMENTS, budget=budget, snapshots=snapshots)
                    cursor = page['next_cursor']
                    for item in page['items']:
                        if item['id'] in seen:
                            continue
                        seen.add(item['id'])
                        append(item['id'], snapshots.get(item['id']))
                        if len(sources) == MAX_DOCUMENTS:
                            break
                    if len(sources) == MAX_DOCUMENTS or cursor is None:
                        break
                partial |= cursor is not None
        except DocumentUnavailable:
            raise EvidenceUnavailable() from None
        except ListingBudgetExceeded:
            partial = True
        if not sources:
            raise EvidenceUnavailable()
        return EvidenceContext(tuple(sources), partial)

    def finalize(self, context, answer, citation_ids):
        try:
            answer_bytes = len(answer.encode('utf8')) if isinstance(answer, str) else 0
        except UnicodeError:
            raise InvalidAnswer() from None
        if (not isinstance(answer, str) or not answer.strip()
                or answer_bytes > 16 * 1024
                or not isinstance(citation_ids, list)
                or not 1 <= len(citation_ids) <= MAX_DOCUMENTS
                or any(not isinstance(i, str) for i in citation_ids)
                or len(set(citation_ids)) != len(citation_ids)):
            raise InvalidAnswer()
        allowed = {source.reference: source for source in context.sources}
        if any(reference not in allowed for reference in citation_ids):
            raise InvalidAnswer()
        budget = ReadBudget(READ_BYTES)
        try:
            for source in context.sources:
                snapshot = self.documents.published(source.document_id, budget=budget)
                if snapshot.fingerprint != source.fingerprint:
                    raise EvidenceChanged()
        except (DocumentUnavailable, ListingBudgetExceeded):
            raise EvidenceChanged() from None
        if not self.documents.store.all_approved({s.document_id: s.fingerprint for s in context.sources}):
            raise EvidenceChanged()
        return {'answer': answer, 'partial': context.partial,
                'citations': [{'id': reference, 'title': allowed[reference].title,
                               'url': f'/doc/{allowed[reference].document_id}'} for reference in citation_ids]}
