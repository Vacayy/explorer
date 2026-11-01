"""질문 판정 엔진은 자동 제안 없이도 관측 갱신·재판정을 한다 (2026-10-16 재가동).

자동 제안(지배 내러티브·다이제스트 → 제안 큐)은 승인 대기만 늘려 별도 스위치 question_autopropose로 분리했다.
"""
import unittest
from unittest.mock import patch

from pipeline import ops, questions as q


class RefreshAllTests(unittest.TestCase):
    def run_refresh(self, autopropose: bool):
        flags = {"question_autopropose": autopropose}
        with patch.object(ops, "flag_enabled", side_effect=lambda name, default=True: flags.get(name, default)), \
             patch.object(q, "propose_from_narratives", return_value={"proposed": 2}) as pn, \
             patch.object(q, "propose_from_digests", return_value={"proposed": 1}) as pd, \
             patch("pipeline.transcript.extract_proxies", return_value={"extracted": 3}), \
             patch.object(q, "extract_sentiment_proxies", return_value={"extracted": 4}), \
             patch.object(q, "get_connection") as gc, \
             patch.object(q, "rollup") as rollup:
            gc.return_value.execute.return_value.fetchall.return_value = [{"id": 7}, {"id": 8}]
            out = q.refresh_all()
        return out, pn, pd, rollup

    def test_without_autopropose_it_still_observes_and_rejudges(self):
        out, pn, pd, rollup = self.run_refresh(False)
        pn.assert_not_called()
        pd.assert_not_called()
        self.assertEqual((out["proposed"], out["digest_proposed"], out["numeric"], out["sentiment"], out["rerolled"]), (0, 0, 3, 4, 2))
        self.assertEqual(rollup.call_count, 2)

    def test_autopropose_switch_turns_proposals_back_on(self):
        out, pn, pd, _ = self.run_refresh(True)
        self.assertEqual((out["proposed"], out["digest_proposed"]), (2, 1))


if __name__ == "__main__":
    unittest.main()
