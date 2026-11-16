import unittest
from unittest.mock import Mock, patch

from pipeline.postgres_chat_models import PostgreSQLChatModels


class PostgreSQLChatModelsTests(unittest.TestCase):
    def test_embedding_is_local_and_released(self):
        models = PostgreSQLChatModels()
        fake = Mock()
        with patch('fastembed.TextEmbedding', return_value=fake) as create, \
             patch('pipeline.postgres_chat_models._release_memory') as release:
            self.assertIs(models.embedding(), fake)
            self.assertIs(models.embedding(), fake)
            self.assertTrue(create.call_args.kwargs['local_files_only'])
            create.assert_called_once()
            models.release_embedding()
            release.assert_called_once()
            self.assertIsNone(models._embedding)
        with self.assertRaises(ValueError):
            models.embedding(local_files_only=False)

    def test_reranker_keeps_scores_and_releases_model(self):
        models = PostgreSQLChatModels()
        fake = Mock()
        fake.rerank.return_value = iter([0.1, 0.9])
        with patch('fastembed.rerank.cross_encoder.TextCrossEncoder', return_value=fake) as create, \
             patch('pipeline.postgres_chat_models._release_memory') as release:
            self.assertEqual(models.rerank('질문', ['자료1', '자료2']), [0.1, 0.9])
            self.assertTrue(create.call_args.kwargs['local_files_only'])
            fake.rerank.assert_called_once_with('질문', ['자료1', '자료2'], batch_size=1)
            release.assert_called_once()


if __name__ == '__main__':
    unittest.main()
