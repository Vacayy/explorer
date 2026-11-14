"""Provider failures must not mix answers, lose schemas, or hide the actual engine."""
import json
import os
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pipeline import llm, enrich


class FailoverTests(unittest.TestCase):
    def setUp(self):
        for patcher in (
            patch.dict(os.environ, {"LLM_FALLBACK_ENGINE": "codex-exec", "CODEX_FALLBACK_MODEL": "test-codex"}),
            patch.object(llm, 'llm_engine', return_value='claude-code'),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.record = patch.object(llm, '_record').start()
        self.addCleanup(patch.stopall)

    def test_success_never_calls_fallback(self):
        result = llm.LLMResult('ok', 'haiku', 'claude-code')
        with patch.object(llm, '_run_claude_code', return_value=result), patch.object(llm, '_run_codex') as fallback:
            self.assertIs(llm.run('prompt', task='document.tag'), result)
        fallback.assert_not_called()
        self.assertEqual(self.record.call_count, 1)

    def test_failure_timeout_and_missing_binary_fall_back_once(self):
        for error in (RuntimeError('usage limit'), subprocess.TimeoutExpired('claude', 1), FileNotFoundError('claude'), ValueError('bad envelope')):
            self.record.reset_mock()
            result = llm.LLMResult('answer', 'test-codex', 'codex-exec')
            with self.subTest(error=error), patch.object(llm, '_run_claude_code', side_effect=error), patch.object(llm, '_run_codex', return_value=result) as fallback:
                self.assertIs(llm.run('prompt', task='narrative.generate', system='rules'), result)
            fallback.assert_called_once()
            self.assertEqual(fallback.call_args.kwargs['system'], 'rules')
            self.assertEqual(fallback.call_args.kwargs['timeout'], 400)
            self.assertEqual([c.args[2] for c in self.record.call_args_list], ['claude-code', 'codex-exec'])
            self.assertIsNotNone(self.record.call_args_list[0].args[-1])
            self.assertIsNone(self.record.call_args_list[1].args[-1])

    def test_both_failures_reported_and_recorded(self):
        with patch.object(llm, '_run_claude_code', side_effect=RuntimeError('primary')), patch.object(llm, '_run_codex', side_effect=RuntimeError('secondary')):
            with self.assertRaisesRegex(RuntimeError, 'primary.*secondary'):
                llm.run('p', task='document.tag')
        self.assertEqual(self.record.call_count, 2)
        self.assertTrue(all(c.args[-1] for c in self.record.call_args_list))

    def test_partial_stream_is_not_replayed(self):
        def primary(prompt, **kw):
            kw['on_text']('partial')
            raise RuntimeError('disconnected')
        chunks = []
        with patch.object(llm, '_run_claude_code', side_effect=primary), patch.object(llm, '_run_codex') as fallback:
            with self.assertRaises(RuntimeError):
                llm.run('p', task='chat.answer', on_text=chunks.append)
        self.assertEqual(chunks, ['partial'])
        fallback.assert_not_called()

    def test_pre_stream_failure_publishes_completed_fallback(self):
        chunks = []
        with patch.object(llm, '_run_claude_code', side_effect=RuntimeError('offline')), patch.object(llm, '_run_codex', return_value=llm.LLMResult('replacement', 'test-codex', 'codex-exec')):
            result = llm.run('p', task='chat.answer', on_text=chunks.append)
        self.assertEqual(chunks, [result.text])

    def test_disabled_and_tool_evidence_calls_do_not_switch(self):
        for tools, setting in [((), 'none'), (('WebSearch', 'WebFetch'), 'codex-exec'), (('Read',), 'codex-exec')]:
            with patch.dict(os.environ, {'LLM_FALLBACK_ENGINE': setting}), patch.object(llm, '_run_claude_code', side_effect=RuntimeError('offline')), patch.object(llm, '_run_codex') as fallback:
                with self.assertRaises(RuntimeError):
                    llm.run('p', task='study.web' if tools else 'document.tag')
                fallback.assert_not_called()

    def test_schema_and_images_forwarded(self):
        for options in ({'task':'narrative.reverify', 'json_schema': {'type':'object'}}, {'task':'image.read', 'images':('/image.png',)}):
            with patch.object(llm, '_run_claude_code', side_effect=RuntimeError('offline')), patch.object(llm, '_run_codex', return_value=llm.LLMResult('{}', 'test-codex', 'codex-exec')) as fallback:
                llm.run('p', **options)
            for key in options.keys() - {'task'}:
                self.assertEqual(fallback.call_args.kwargs[key], options[key])

    def test_invalid_options_do_not_call_any_provider(self):
        with patch.object(llm, '_run_claude_code') as primary, patch.object(llm, '_run_codex') as fallback:
            with self.assertRaises(ValueError):
                llm.run('p', task='narrative.reverify', json_schema={}, on_text=lambda x: None)
            primary.assert_not_called()
            fallback.assert_not_called()

    def test_enrichment_records_the_actual_fallback_model(self):
        with patch.object(llm, 'run', return_value=llm.LLMResult('{"summary":"ok"}','test-codex','codex-exec')) as run:
            result = enrich._enrich_llm('title', 'body')
        self.assertEqual(result['model'], 'codex-exec/test-codex')
        self.assertEqual(run.call_args.kwargs['task'], 'document.tag')


class CodexAdapterTests(unittest.TestCase):
    def invoke(self, *, event='turn.completed', text='{"ok":true}', item=None, rc=0, schema=None):
        def execute(args, **kw):
            self.assertIn('--ignore-user-config', args)
            self.assertIn('shell_tool', args)
            self.assertIn('read-only', args)
            self.assertIn('web_search="disabled"', args)
            self.assertIn('RULES', kw['input'])
            self.assertEqual(kw['timeout'], 9)
            self.assertTrue(kw['cwd'].name.startswith('explorer-codex-'))
            if schema:
                actual = json.loads(Path(args[args.index('--output-schema')+1]).read_text())
                self.assertEqual(actual['required'], ['ok'])
            Path(args[args.index('-o')+1]).write_text(text)
            events = [{'type':event, 'usage':{'input_tokens':12,'cached_input_tokens':4,'output_tokens':3}}]
            if item:
                events.append({'type':'item.completed','item':{'type':item}})
            return SimpleNamespace(returncode=rc, stdout='\n'.join(map(json.dumps,events)), stderr='error')
        with patch.object(llm.shutil, 'which', return_value='/codex'), patch.object(llm.subprocess, 'run', side_effect=execute):
            return llm._run_codex('INPUT',system='RULES',model='test-codex',effort='low',timeout=9,json_schema=schema)

    def test_usage_and_schema(self):
        schema = {'type':'object','properties':{'ok':{'type':'boolean'}}}
        result = self.invoke(schema=schema)
        self.assertEqual(result.engine, 'codex-exec')
        self.assertEqual(result.model, 'test-codex')
        self.assertEqual(result.usage, {'input':12,'cache_read':4,'output':3})
        self.assertIsNone(result.cost_usd)
        self.assertNotIn('required', schema)

    def test_rejects_incomplete_empty_failed_and_tool_results(self):
        for kw in ({'event':'turn.failed'}, {'event':'thread.started'}, {'text':' '}, {'item':'mcp_tool_call'}, {'rc':1}):
            with self.subTest(kw=kw), self.assertRaises(RuntimeError):
                self.invoke(**kw)

class MigratedCallTests(unittest.TestCase):
    def test_json_and_text_helpers_keep_existing_return_shapes(self):
        from pipeline import canon, doc_causal, worldview, investor_lens, stock_brief, consolidation, falsifiers, upside_model
        for call in (canon._call, doc_causal._call, worldview._call_json_sonnet,
                     investor_lens._call_json_lens, stock_brief._call_json_brief,
                     upside_model._call_opus):
            with self.subTest(call=call.__module__), patch.object(llm, 'run', return_value=llm.LLMResult('{"ok":true}', 'test-codex', 'codex-exec')) as run:
                self.assertEqual(call('p'), {'ok':True})
                run.assert_called_once()
        for call in (lambda prompt: consolidation._call_knowledge(prompt, task="knowledge.promote"), falsifiers._call_falsifier_opus):
            with patch.object(llm, 'run', return_value=llm.LLMResult('answer', 'test-codex', 'codex-exec')):
                self.assertEqual(call('p'), 'answer')

    def test_envelope_failures_reach_codex(self):
        for output in ('[]', 'bad json', '{"is_error":true,"subtype":"limit"}', '{"result":""}'):
            with self.subTest(output=output), patch.dict(os.environ, {'LLM_FALLBACK_ENGINE':'codex-exec'}), patch.object(llm, 'llm_engine', return_value='claude-code'), patch.object(llm, '_claude_bin', return_value='claude'), patch.object(llm.subprocess, 'run', return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')), patch.object(llm, '_run_codex', return_value=llm.LLMResult('ok','test-codex','codex-exec')) as fallback, patch.object(llm, '_record'):
                self.assertEqual(llm.run('p', task='document.tag').engine, 'codex-exec')
                fallback.assert_called_once()

    def test_legacy_vision_passes_explicit_image_and_cleans_up(self):
        import tempfile
        from pipeline import vision
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'sample.png'
            source.write_bytes(b'fixture')
            runtime = root / 'runtime'
            seen = []
            def run(prompt, **kw):
                image = Path(kw['images'][0])
                self.assertTrue(image.is_relative_to(runtime))
                self.assertEqual(image.read_bytes(), b'fixture')
                self.assertIn(str(image.relative_to(runtime)), prompt)
                seen.append(image)
                return llm.LLMResult('{"events":[]}', 'test-codex', 'codex-exec')
            with patch.object(vision, 'MEDIA_PATH', root), patch.object(llm, 'RUNTIME_DIR', runtime), patch.object(llm, 'run', side_effect=run):
                self.assertEqual(vision._analyze_image('sample.png', '2026-11-11'), {'events':[]})
            self.assertFalse(seen[0].exists())
            self.assertTrue(source.exists())


if __name__ == '__main__':
    unittest.main()
