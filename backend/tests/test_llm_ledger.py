"""claude -p 직접 호출도 llm_calls 원장에 남는다.

내러티브(opus, 주 13~24편)·세계관·리포트 등은 enrich._call_claude_code나 subprocess를 직접 불러
원장에 잡히지 않았다 — 비용 화면에 가장 큰 항목이 보이지 않았다.
"""
import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from pipeline import enrich, llm

ENVELOPE = {"result": '{"ok": 1}', "total_cost_usd": 0.42, "duration_ms": 1234,
            "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 5}}


class LedgerTests(unittest.TestCase):
    def call(self, proc):
        with patch.object(enrich.subprocess, "run", return_value=proc), \
             patch.object(enrich, "_claude_bin", return_value="claude"), \
             patch.object(llm, "_record") as rec:
            try:
                out = enrich._call_claude_code("p", model="opus", timeout=5)
            except RuntimeError:
                out = None
        return out, rec.call_args

    def test_success_is_recorded_with_usage_and_caller(self):
        out, call = self.call(MagicMock(returncode=0, stdout=json.dumps(ENVELOPE), stderr=""))
        self.assertEqual(out, '{"ok": 1}')
        job, model, engine, effort, res, _ms, err = call.args
        self.assertTrue(job.endswith("test_llm_ledger"))   # 호출 모듈 이름(실행 방식에 따라 tests. 접두어 유무)
        self.assertEqual((model, engine, err), ("opus", "claude-code", None))
        self.assertEqual(res.cost_usd, 0.42)
        self.assertEqual(res.usage["input"], 100)

    def test_failure_is_recorded(self):
        out, call = self.call(MagicMock(returncode=1, stdout="usage limit", stderr=""))
        self.assertIsNone(out)
        self.assertIsNone(call.args[4])
        self.assertIn("rc=1", call.args[6])

    def test_narrative_call_goes_through_the_ledger(self):
        from pipeline import narrative
        with patch.object(enrich.subprocess, "run", return_value=MagicMock(returncode=0, stdout=json.dumps(ENVELOPE), stderr="")), \
             patch.object(enrich, "_claude_bin", return_value="claude"), \
             patch.object(llm, "_record") as rec:
            self.assertEqual(narrative._call("p"), {"ok": 1})
        self.assertEqual(rec.call_args.args[0], "narrative")


if __name__ == "__main__":
    unittest.main()
