import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from pipeline import postgres_legacy_projection_builder as builder


class DocumentMetaRefreshTest(unittest.TestCase):
    def test_a_failed_refresh_is_logged_and_never_raises(self):
        out = io.StringIO()
        with patch.dict(os.environ, {'REFACTOR_POSTGRES_DSN': 'postgresql://unused', 'REFACTOR_FIXTURE_SCHEMA': 's'}), \
                patch.object(builder.psycopg, 'connect', side_effect=RuntimeError('database down')), redirect_stdout(out):
            builder.refresh_document_meta()
        self.assertEqual(json.loads(out.getvalue()), {'document_meta_failed': 'RuntimeError: database down'})


if __name__ == '__main__':
    unittest.main()
