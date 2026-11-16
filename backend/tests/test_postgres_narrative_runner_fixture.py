import unittest
from contextlib import contextmanager
from unittest.mock import patch

from pipeline.postgres_narrative_runner_fixture import run_fixture_narrative


class Connection:
    def __init__(self):
        self.updates=[]

    def execute(self, sql, params=None):
        if sql.startswith('UPDATE ingest_narrative_claims'):
            self.updates.append(params)
        return self

    def fetchone(self):
        return ('refactor_fixture_stage',)


class NarrativeRunnerTests(unittest.TestCase):
    def test_generator_failure_marks_external_outcome_unknown(self):
        source=Connection()
        stage=Connection()

        @contextmanager
        def factory():
            yield source

        @contextmanager
        def stage_factory():
            yield stage

        def fail(_):
            raise RuntimeError('fixture generator failed')

        with patch('pipeline.postgres_narrative_runner_fixture._guard'), \
             patch('pipeline.postgres_narrative_runner_fixture.claim_narrative',return_value='token'), \
             patch('pipeline.postgres_narrative_runner_fixture.prepare_fixture_narrative',return_value={'status':'ready','prompt':'fixture'}), \
             patch('pipeline.postgres_narrative_runner_fixture.commit_staged_narrative') as commit:
            with self.assertRaisesRegex(RuntimeError,'fixture generator failed'):
                run_fixture_narrative(factory,stage_factory,'refactor_fixture_stage','topic',embedder=lambda _: [],generate=fail)
        self.assertEqual(source.updates,[('unknown','topic','token')])
        commit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
