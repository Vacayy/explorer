"""문서 디테일 '관련 문서' 정리 규칙 (D-221) — 최소 유사도·같은 제목·출처당 상한·겹치는 엔티티."""
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import sqlite_vec

from pipeline import search
from pipeline.chunks import _serialize


def _vec(angle: float) -> list[float]:
    """첫 두 축 평면의 단위 벡터 — 각도로 유사도를 정한다(cos)."""
    v = np.zeros(search.EMBED_DIM, dtype=np.float32)
    v[0], v[1] = np.cos(angle), np.sin(angle)
    return v.tolist()


class RelatedDocsTests(unittest.TestCase):
    def setUp(self):
        self.f = tempfile.NamedTemporaryFile(suffix=".db")
        c = self.connect()
        c.executescript(f"""
            CREATE VIRTUAL TABLE doc_centroid_vec USING vec0(embedding float[{search.EMBED_DIM}]);
            CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT, url TEXT, title TEXT, published_at TEXT);
            CREATE TABLE telegram_channels(channel_name TEXT, display_name TEXT);
            CREATE TABLE blog_sources(url TEXT, blog_name TEXT);
            CREATE TABLE youtube_channels(channel_id TEXT, title TEXT);
            CREATE TABLE scrap_links(doc_id INTEGER, channel TEXT);
            CREATE TABLE entities(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE entity_links(doc_id INTEGER, entity_id INTEGER, link_type TEXT, confidence REAL);
            INSERT INTO telegram_channels VALUES ('chA', '채널A'), ('chB', '채널B');
            INSERT INTO entities VALUES (1, 'SK하이닉스'), (2, '온'), (3, '반도체');
        """)
        docs = [  # id, channel, title, angle(유사도 = cos)
            (1, "chB", "기준 문서", 0.0),
            (2, "chA", "같은 채널 1", 0.1), (3, "chA", "같은 채널 2", 0.12), (4, "chA", "같은 채널 3", 0.14),
            (5, "chB", "제목 중복", 0.2), (6, "chB", "제목  중복", 0.22),
            (7, "chB", "너무 먼 문서", 1.2),   # cos ≈ 0.36
        ]
        for i, ch, title, a in docs:
            c.execute("INSERT INTO raw_documents VALUES (?, 'telegram', ?, '', ?, '2026-10-01')", (i, f"{ch}/{i}", title))
            c.execute("INSERT INTO doc_centroid_vec(rowid, embedding) VALUES (?, ?)", (i, _serialize(_vec(a))))
        c.executemany("INSERT INTO entity_links VALUES (?,?,?,?)", [
            (1, 1, "stock", 0.8), (1, 2, "stock", 0.6), (1, 3, "industry", 0.5),
            (2, 1, "stock", 0.9), (2, 2, "stock", 0.6), (2, 3, "industry", 0.5)])
        c.commit()
        c.close()

    def tearDown(self):
        self.f.close()

    def connect(self):
        c = sqlite3.connect(self.f.name)
        c.row_factory = sqlite3.Row
        c.enable_load_extension(True)
        sqlite_vec.load(c)
        return c

    def test_rules(self):
        with patch.object(search, "_vec_conn", side_effect=self.connect):
            out = search.related_docs(1)
        ids = [r["id"] for r in out]
        self.assertEqual(ids, [2, 3, 5])               # 채널A는 2개까지, 제목 중복(공백 차이)은 하나, 먼 문서 제외
        self.assertEqual(out[0]["channel"], "채널A")
        self.assertEqual(out[0]["reasons"], ["SK하이닉스", "반도체"])   # 낮은 확신 종목 매칭('온')은 이유에서 뺀다
        self.assertGreater(out[0]["similarity"], 0.99)

    def test_missing_centroid_returns_empty(self):
        with patch.object(search, "_vec_conn", side_effect=self.connect):
            self.assertEqual(search.related_docs(99), [])


if __name__ == "__main__":
    unittest.main()
