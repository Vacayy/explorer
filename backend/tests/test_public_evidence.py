"""Actual SQLite/file publication checks before and after a buffered answer."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from security.public_documents import PublicDocuments
from security.publication_store import PublicationStore
from security.public_evidence import PublicEvidence, EvidenceUnavailable, EvidenceChanged, InvalidAnswer


class PublicEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root/'source.sqlite'
        self.media = self.root/'media'; self.media.mkdir()
        (self.media/'one.png').write_bytes(b'\x89PNG\r\n\x1a\noriginal')
        with sqlite3.connect(self.db) as conn:
            conn.execute('''CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, title, source_type,
                url, published_at, markdown, raw_content, media_json, private_note)''')
            conn.executemany('INSERT INTO raw_documents VALUES(?,?,?,?,?,?,?,?,?)', [
                (1, 'Public one', 'web', 'https://example.test/one', None, 'Reviewed earnings one', None, '["one.png"]', 'PRIVATE_CANARY'),
                (2, 'Public two', 'web', None, None, 'Reviewed earnings two', None, '[]', 'PRIVATE_CANARY'),
                (3, 'Private', 'note', None, None, 'PRIVATE_CANARY earnings', None, '[]', 'PRIVATE_CANARY')])
        self.store = PublicationStore(self.root/'publications.sqlite'); self.store.initialize()
        self.documents = PublicDocuments(self.db, self.media, self.store)
        for doc_id in (1, 2): self.approve(doc_id)
        self.service = PublicEvidence(self.documents)

    def approve(self, doc_id):
        snapshot = self.documents.capture(doc_id)
        record = self.store.get(doc_id)
        self.store.approve(doc_id, snapshot.fingerprint, record['version'] if record else 0, 'operator', 'synthetic rights')

    def test_search_context_and_server_owned_citations_do_not_include_private_data(self):
        context = self.service.gather('earnings')
        self.assertEqual({source.document_id for source in context.sources}, {1, 2})
        self.assertNotIn('PRIVATE_CANARY', context.model_input())
        self.assertNotIn('https://', context.model_input())
        self.assertNotIn('operator', context.model_input())
        first = context.sources[0]
        result = self.service.finalize(context, 'Buffered answer', [first.reference])
        self.assertEqual(result['citations'], [{'id': first.reference, 'title': first.title, 'url': f'/doc/{first.document_id}'}])

    def test_unapproved_or_no_matching_evidence_cannot_reach_model_context(self):
        for query, ids in [('PRIVATE_CANARY', ()), ('missing', ()), ('', (3,)), ('', (1, 999))]:
            with self.subTest(query=query, ids=ids), self.assertRaises(EvidenceUnavailable):
                self.service.gather(query, ids)

    def test_revoked_uncited_context_discards_whole_answer(self):
        context = self.service.gather(document_ids=(1, 2))
        self.store.revoke(2, self.store.get(2)['version'], 'operator')
        with self.assertRaises(EvidenceChanged):
            self.service.finalize(context, 'Answer used both documents', ['D1'])

    def test_revocation_during_later_document_verification_discards_answer(self):
        context = self.service.gather(document_ids=(1, 2))
        published = self.documents.published
        def check(doc_id, **kwargs):
            if doc_id == 2:
                self.store.revoke(1, self.store.get(1)['version'], 'operator')
            return published(doc_id, **kwargs)
        with patch.object(self.documents, 'published', side_effect=check), self.assertRaises(EvidenceChanged):
            self.service.finalize(context, 'answer', ['D1'])

    def test_casefold_expansion_maps_search_hit_to_original_content(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute('UPDATE raw_documents SET markdown=? WHERE id=2', ('ß'*5000+'needle',))
        self.approve(2)
        self.assertIn('needle', self.documents.listing('needle')['items'][0]['snippet'])
        context = self.service.gather('needle')
        self.assertEqual(context.sources[0].document_id, 2)
        self.assertIn('needle', context.sources[0].excerpt)

    def test_search_reuses_verified_snapshot_within_one_read_budget(self):
        self.store.revoke(2, self.store.get(2)['version'], 'operator')
        with patch('security.public_evidence.READ_BYTES', 40):
            context = self.service.gather('one')
        self.assertEqual([s.document_id for s in context.sources], [1])

    def test_changed_text_and_attachment_each_discard_answer(self):
        context = self.service.gather(document_ids=(1,))
        (self.media/'one.png').write_bytes(b'\x89PNG\r\n\x1a\nchanged')
        with self.assertRaises(EvidenceChanged): self.service.finalize(context, 'answer', ['D1'])
        self.approve(1)
        context = self.service.gather(document_ids=(1,))
        with sqlite3.connect(self.db) as conn: conn.execute('UPDATE raw_documents SET markdown=? WHERE id=1', ('changed',))
        with self.assertRaises(EvidenceChanged): self.service.finalize(context, 'answer', ['D1'])

    def test_reapproval_of_different_content_does_not_validate_old_context(self):
        context = self.service.gather(document_ids=(2,))
        with sqlite3.connect(self.db) as conn: conn.execute('UPDATE raw_documents SET markdown=? WHERE id=2', ('newly approved',))
        self.approve(2)
        with self.assertRaises(EvidenceChanged): self.service.finalize(context, 'old answer', ['D1'])

    def test_model_cannot_supply_foreign_ids_urls_duplicates_or_unbounded_answer(self):
        context = self.service.gather(document_ids=(1,))
        for ids in [['D2'], ['https://attacker.invalid'], [], ['D1', 'D1'], [1], 'D1']:
            with self.subTest(ids=ids), self.assertRaises(InvalidAnswer): self.service.finalize(context, 'answer', ids)
        for answer in ['', ' ', '한'*6000, None, '\ud800']:
            with self.subTest(answer_type=type(answer)), self.assertRaises(InvalidAnswer): self.service.finalize(context, answer, ['D1'])

    def test_context_budget_counts_json_escaping_and_multibyte_content(self):
        text = ('한글\\"\x01'*5000)
        with sqlite3.connect(self.db) as conn:
            conn.execute('UPDATE raw_documents SET markdown=? WHERE id IN (1,2)', (text,))
        self.approve(1); self.approve(2)
        context = self.service.gather(document_ids=(1, 2))
        self.assertTrue(context.partial)
        self.assertLessEqual(len(context.model_input().encode('utf8')), 24*1024)
        self.assertEqual(len(json.loads(context.model_input())), 2)
        for source in context.sources: self.assertLessEqual(len(source.excerpt.encode('utf8')), 4096)

    def test_reads_share_budget_and_revalidation_budget_failure_discards_answer(self):
        with patch('security.public_evidence.READ_BYTES', 1), self.assertRaises(EvidenceUnavailable):
            self.service.gather('earnings')
        context = self.service.gather(document_ids=(1,))
        with patch('security.public_evidence.READ_BYTES', 1), self.assertRaises(EvidenceChanged):
            self.service.finalize(context, 'answer', ['D1'])

    def test_lookup_passes_empty_intermediate_page_and_stops_at_page_cap(self):
        real_listing = self.documents.listing
        seen = []
        def pages(query, cursor, limit, *, budget, snapshots):
            seen.append(budget)
            return {'items': [], 'next_cursor': 'continuation'} if len(seen)==1 else real_listing(query, None, limit, budget=budget, snapshots=snapshots)
        with patch.object(self.documents, 'listing', side_effect=pages):
            self.assertEqual(len(self.service.gather('earnings').sources), 2)
        self.assertIs(seen[0], seen[1])
        with patch.object(self.documents, 'listing', return_value={'items': [], 'next_cursor': 'continue'}) as listing:
            with self.assertRaises(EvidenceUnavailable): self.service.gather('earnings')
            self.assertEqual(listing.call_count, 3)

    def test_selection_validation_and_no_database_writes(self):
        before = (self.db.read_bytes(), self.store.path.read_bytes())
        for ids in [(True,), (0,), (1, 1), tuple(range(1, 6)), ([1],), None]:
            with self.assertRaises(ValueError): self.service.gather(document_ids=ids)
        context = self.service.gather(document_ids=(1,))
        self.service.finalize(context, 'answer', ['D1'])
        self.assertEqual(before, (self.db.read_bytes(), self.store.path.read_bytes()))


if __name__ == '__main__':
    unittest.main()
