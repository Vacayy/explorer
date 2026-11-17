import json
import unittest
from unittest.mock import patch

from pipeline import feed_enrichment, llm


class FeedEnrichmentTest(unittest.TestCase):
    def test_batch_validates_complete_unique_mapping_and_actual_model_label(self):
        docs = [{'title': 'a', 'markdown': 'x' * 3000}, {'title': 'b', 'markdown': 'body'}]
        result = llm.LLMResult(text=json.dumps({'results': [{'doc': 2, 'summary': 'two'},
                                                          {'doc': 1, 'summary': 'one'}]}),
                               model='test', engine='codex-exec')
        with patch.object(llm, 'run', return_value=result) as run:
            output = feed_enrichment.enrich_documents(docs, vocabulary=([], [], [], []))
        self.assertEqual([item['summary'] for item in output], ['one', 'two'])
        self.assertTrue(all(item['model'] == 'codex-exec/test' for item in output))
        self.assertIn('x' * 3000, run.call_args.args[0])

    def test_incomplete_duplicate_and_fractional_results_are_rejected(self):
        docs = [{'title': 'a', 'markdown': 'x'}, {'title': 'b', 'markdown': 'y'}]
        for records in ([{'doc': 1, 'summary': 'one'}],
                        [{'doc': 1, 'summary': 'one'}, {'doc': 1, 'summary': 'two'}],
                        [{'doc': 1.5, 'summary': 'one'}, {'doc': 2, 'summary': 'two'}],
                        [{'doc': 1, 'summary': ''}, {'doc': 2, 'summary': 'two'}]):
            result = llm.LLMResult(text=json.dumps({'results': records}), model='test', engine='codex-exec')
            with patch.object(llm, 'run', return_value=result), self.assertRaises(ValueError):
                feed_enrichment.enrich_documents(docs, vocabulary=([], [], [], []))
