"""Policy ownership and pre-refactor call contracts; never invoke a real provider."""
import ast
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from pipeline import llm
from pipeline.llm_policies import TASKS, resolve, validate_configuration

ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads((Path(__file__).parent / 'fixtures/llm_policy_baseline.json').read_text())


class PolicyTests(unittest.TestCase):
    def test_preserves_all_captured_defaults(self):
        for task, old in BASELINE['policies'].items():
            with self.subTest(task=task):
                p = resolve(task, environ={})
                self.assertEqual((p.primary.model, p.primary.effort, p.timeout, p.tools),
                                 (old['model'], old['effort'], old['timeout'], tuple(old['tools'])))
                self.assertEqual((p.stream, p.schema, p.api_max_tokens),
                                 (old['stream'], old['schema'], old['api_max_tokens']))
                self.assertEqual((TASKS[task].model_env, TASKS[task].effort_env),
                                 (old['model_env'], old['effort_env']))

    def test_shared_knowledge_helpers_have_independent_policies(self):
        env = {'LLM_TASK_KNOWLEDGE_PROMOTE_MODEL': 'haiku'}
        for task in ('knowledge.check_falsifier', 'knowledge.contradiction'):
            policy = resolve(task, environ=env)
            self.assertEqual((policy.primary.model, policy.timeout), ('opus', 400))

    def test_knowledge_judges_dispatch_their_own_tasks(self):
        from pipeline import contradiction, falsifiers
        cases = [
            (lambda: contradiction._judge_stance("s", "t", "d"), "SUPPORT", "knowledge.contradiction", "SUPPORT"),
            (lambda: falsifiers._judge_triggered("c", "s", "t", "d"), "TRIGGERED", "knowledge.check_falsifier", True),
        ]
        for call, answer, task, expected in cases:
            with self.subTest(task=task), patch("pipeline.enrich.llm_engine", return_value="claude-code"), patch.object(
                llm, "run", return_value=llm.LLMResult(answer, "opus", "claude-code")
            ) as run:
                self.assertEqual(call(), expected)
                self.assertEqual(run.call_args.kwargs["task"], task)

    def test_task_override_is_local_and_legacy_settings_still_work(self):
        env = {'NARRATIVE_MODEL':'sonnet', 'LLM_TASK_NARRATIVE_GENERATE_MODEL':'haiku',
               'CODEX_FALLBACK_MODEL':'global-fallback', 'LLM_TASK_CHAT_ANSWER_FALLBACK_MODEL':'answer-fallback',
               'CHAT_SYNTH_EFFORT':'medium', 'LLM_TASK_CHAT_ANSWER_TIMEOUT':'240'}
        self.assertEqual(resolve('narrative.generate',environ=env).primary.model,'haiku')
        self.assertEqual(resolve('narrative.mega',environ=env).primary.model,'sonnet')
        self.assertEqual(resolve('narrative.diff',environ=env).primary.model,'haiku')
        answer=resolve('chat.answer',environ=env)
        self.assertEqual((answer.primary.effort,answer.timeout,answer.fallback.model),('medium',240,'answer-fallback'))
        self.assertEqual(resolve('chat.route',environ=env).fallback.model,'global-fallback')

    def test_invalid_settings_and_unknown_tasks_fail_before_provider(self):
        cases=[{'LLM_TASK_CHAT_ANSWER_TIMEOUT':'0'}, {'LLM_TASK_CHAT_ANSWER_TIMEOUT':'oops'},
               {'LLM_TASK_CHAT_ANSWER_MODEL':''}, {'LLM_TASK_CHAT_ANSWER_EFFORT':'ultra'},
               {'LLM_FALLBACK_ENGINE':'other'}, {'LLM_TASK_CHAT_ANSWR_MODEL':'haiku'}]
        for env in cases:
            with self.subTest(env=env), self.assertRaises(ValueError): validate_configuration(env)
        with patch.object(llm,'_execute') as execute:
            with self.assertRaisesRegex(ValueError,'등록되지'):
                llm.run('p',task='misspelled.task')
            execute.assert_not_called()

    def test_policies_are_immutable_and_return_new_snapshots(self):
        with self.assertRaises(TypeError): TASKS['chat.answer']=TASKS['chat.route']
        p=resolve('chat.answer',environ={})
        with self.assertRaises(FrozenInstanceError): p.timeout=1
        changed=resolve('chat.answer',environ={'LLM_TASK_CHAT_ANSWER_MODEL':'haiku'})
        self.assertEqual(p.primary.model,'sonnet')
        self.assertEqual(changed.primary.model,'haiku')

    def test_capabilities_and_disabled_fallback(self):
        # Web research falls back only to Codex's own web search (llm_policies.WEB_FALLBACK_TASKS).
        self.assertEqual(resolve('study.web',environ={}).fallback.engine,'codex-exec')
        self.assertEqual(resolve('chain.analyze',environ={}).fallback.engine,'codex-exec')
        self.assertIsNone(resolve('study.web',environ={'LLM_FALLBACK_ENGINE':'none'}).fallback)
        self.assertIsNone(resolve('document.tag',engine='api',environ={}).fallback)
        self.assertIsNone(resolve('chat.answer',environ={'LLM_FALLBACK_ENGINE':'none'}).fallback)
        with self.assertRaises(ValueError):resolve('study.web',engine='api',environ={})
        for task,kw in [('document.tag',{'on_text':lambda x:None}),('document.tag',{'images':('a',)}),
                        ('document.tag',{'json_schema':{}}),('narrative.reverify',{}),('image.read',{})]:
            with self.subTest(task=task),patch.object(llm,'llm_engine',return_value='claude-code'),patch.object(llm,'_execute') as execute:
                with self.assertRaises(ValueError):llm.run('p',task=task,**kw)
                execute.assert_not_called()

    def test_no_model_override_through_feature_api(self):
        with self.assertRaises(TypeError):llm.run('p',task='document.tag',model='opus')

    def test_api_tagging_keeps_old_token_limit(self):
        with patch.object(llm,'llm_engine',return_value='api'),patch.object(llm,'_run_api',return_value=llm.LLMResult('{}','haiku','api')) as api,patch.object(llm,'_record'):
            llm.run('p',task='document.tag')
        self.assertEqual(api.call_args.kwargs['max_tokens'],1024)


class MigrationContractTests(unittest.TestCase):
    def test_prompts_and_system_instructions_are_unchanged(self):
        for old in BASELINE['calls']:
            with self.subTest(task=old['task'],file=old['file']):
                tree=ast.parse((ROOT/old['file']).read_text())
                found=[]
                for n in ast.walk(tree):
                    if not isinstance(n,ast.Call):continue
                    task=next((k.value for k in n.keywords if k.arg=='task'),None)
                    if isinstance(task,ast.Constant) and task.value==old['task'] and ast.unparse(n.func) in {'llm.run', 'run', 'llm', 'runner or llm.run'}:
                        found.append(n)
                    elif isinstance(task,ast.Name) and old['task'] in {'narrative.generate','report.analyze','knowledge.promote'} and ast.unparse(n.func)=='llm.run':
                        found.append(n)
                self.assertEqual(len(found),1)
                n=found[0]
                self.assertEqual(hashlib.sha256(ast.dump(n.args[0]).encode()).hexdigest(),old['prompt_ast_sha256'])
                system=next((hashlib.sha256(ast.dump(k.value).encode()).hexdigest() for k in n.keywords if k.arg=='system'),None)
                self.assertEqual(system,old['system_ast_sha256'])

    def test_general_callers_cannot_specify_provider_policy(self):
        for path in (ROOT/'backend/pipeline').rglob('*.py'):
            if path.name in {'llm.py','llm_policies.py'} or 'market_analysis' in path.parts or 'weekly' in path.parts:continue
            tree=ast.parse(path.read_text())
            aliases={'llm.run','runner or llm.run'}
            for n in ast.walk(tree):
                if isinstance(n,ast.ImportFrom) and n.module=='pipeline.llm':
                    aliases.update(x.asname or x.name for x in n.names if x.name=='run')
            for n in ast.walk(tree):
                if not isinstance(n,ast.Call) or ast.unparse(n.func) not in aliases:continue
                with self.subTest(path=path,line=n.lineno):
                    keys={k.arg for k in n.keywords}
                    self.assertIn('task',keys)
                    self.assertFalse(keys & {'model','effort','timeout','job','tools'})
            self.assertNotIn('def _call_claude_code(',path.read_text())


if __name__=='__main__':unittest.main()
