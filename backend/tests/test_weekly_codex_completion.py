import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from models.weekly_reader import FactualReview, ReaderBrief
from pipeline.weekly.codex_completion import output_schema, run


class CodexCompletionTest(unittest.TestCase):
    def test_strict_schema_keeps_original_unchanged(self):
        original = ReaderBrief.model_json_schema()
        strict = output_schema(original)
        self.assertEqual(set(strict["required"]), set(strict["properties"]))
        self.assertEqual(set(strict["$defs"]["Paragraph"]["required"]), set(strict["$defs"]["Paragraph"]["properties"]))
        self.assertIn("default", original["properties"]["schema_version"])
        self.assertNotIn("default", strict["properties"]["schema_version"])

    def invoke(self, item_type="agent_message"):
        def execute(args, **kwargs):
            self.assertEqual(kwargs["cwd"].name.split('-')[0], "weekly")
            self.assertIn("--ignore-user-config", args)
            self.assertIn("read-only", args)
            self.assertIn('web_search="disabled"', args)
            self.assertIn("shell_tool", args)
            Path(args[args.index('-o')+1]).write_text('{"assessment":"확인","issues":[]}')
            events = [{"type":"item.completed","item":{"type":item_type}},
                      {"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":20,"output_tokens":8}}]
            return SimpleNamespace(returncode=0, stdout='\n'.join(json.dumps(x) for x in events))
        with patch('pipeline.weekly.codex_completion.shutil.which', return_value='/test/codex'), patch('pipeline.weekly.codex_completion.subprocess.run', side_effect=execute):
            return run('자료', system='지침', model='test-model', effort='medium', timeout=30, job='test', json_schema=FactualReview.model_json_schema())

    def test_records_actual_provider_and_rejects_tool_use(self):
        result = self.invoke()
        self.assertEqual(result['engine'], 'codex-exec')
        self.assertEqual(result['model'], 'test-model')
        self.assertIsNone(result['cost_usd'])
        self.assertEqual(result['usage']['cache_read'], 20)
        FactualReview.model_validate_json(result['text'])
        with self.assertRaisesRegex(ValueError, '도구'):
            self.invoke('web_search')
