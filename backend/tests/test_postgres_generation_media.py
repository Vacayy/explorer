import tempfile
import unittest
from pathlib import Path

from pipeline.postgres_generation_media import _read_file


class AttachmentPathTest(unittest.TestCase):
    def test_rejects_traversal_symlinks_and_unsupported_types(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'safe').mkdir()
            (root / 'safe' / 'image.jpg').write_bytes(b'fixture')
            (root / 'safe' / 'wrong.html').write_text('fixture')
            (root / 'linked').symlink_to(root / 'safe', target_is_directory=True)
            self.assertEqual(_read_file(root, 'safe/image.jpg'), b'fixture')
            for path in ('../safe/image.jpg', '/safe/image.jpg', 'safe/../safe/image.jpg',
                         'safe/wrong.html', 'linked/image.jpg'):
                with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                    _read_file(root, path)
