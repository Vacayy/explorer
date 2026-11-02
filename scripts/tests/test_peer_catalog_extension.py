import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.build_peer_catalog import extend_catalog

class CatalogExtensionTests(unittest.TestCase):
    def test_preserves_prior_evidence_and_memberships_without_duplicate_company(self):
        company = dict(code='000001', name='기존', aliases=[], products=['기존 제품'], groupIds=['old'], caveats=['기존 한계'], sources=[dict(url='https://example.org/old')])
        base = dict(groups=[dict(id='old')], companies=[company])
        before = copy.deepcopy(base)
        extra = dict(version='v2', asOf='2026-11-02', groups=[dict(id='new')], companies=[dict(company, name='신규 명칭', products=['새 제품'], groupIds=['new'], sources=[dict(url='https://example.org/new')])])
        result = extend_catalog(base, extra)
        self.assertEqual(base, before)
        self.assertEqual(len(result['companies']), 1)
        self.assertEqual(result['companies'][0]['groupIds'], ['old', 'new'])
        self.assertEqual(len(result['companies'][0]['sources']), 2)
        self.assertEqual(extend_catalog(result, extra), result)

    def test_rejects_unknown_group_before_export(self):
        extra = dict(version='v2', asOf='2026-11-02', groups=[], companies=[dict(code='000001', name='기업', groupIds=['missing'])])
        with self.assertRaisesRegex(AssertionError, 'unknown group'):
            extend_catalog(dict(groups=[], companies=[]), extra)
