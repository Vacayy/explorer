"""One-at-a-time local search models for the isolated PG chat worker."""
import ctypes
import gc

from config import FASTEMBED_CACHE
from pipeline.search import EMBED_MODEL
from pipeline.rerank import RERANK_BATCH_SIZE, RERANK_MODEL


def _release_memory():
    gc.collect()
    try:
        ctypes.CDLL(None).malloc_trim(0)
    except (AttributeError, OSError):
        pass  # Non-glibc systems rely on their allocator's normal cleanup.


class PostgreSQLChatModels:
    """Load only one search model at a time; caller serializes retrievals."""
    def __init__(self):
        self._embedding = None

    def embedding(self, *, local_files_only=True):
        if not local_files_only:
            raise ValueError('interactive search may not download models')
        if self._embedding is None:
            from fastembed import TextEmbedding
            self._embedding = TextEmbedding(EMBED_MODEL, cache_dir=FASTEMBED_CACHE, local_files_only=True)
        return self._embedding

    def release_embedding(self):
        self._embedding = None
        _release_memory()

    def rerank(self, query, texts):
        if not texts:
            return []
        if not RERANK_MODEL:
            return None
        enc = None
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            enc = TextCrossEncoder(RERANK_MODEL, cache_dir=FASTEMBED_CACHE, local_files_only=True)
            return [float(score) for score in enc.rerank(query, texts, batch_size=RERANK_BATCH_SIZE)]
        except Exception as exc:  # Same fallback contract as the existing reranker.
            print(f'[rerank] 비활성 — {type(exc).__name__}: {str(exc)[:120]}', flush=True)
            return None
        finally:
            enc = None
            _release_memory()


class PostgreSQLChatSearch:
    """Own the low-memory index and models for one isolated chat worker."""
    def __init__(self, connect, *, portfolio_provider=None):
        from pipeline.postgres_chat_chunks import PostgreSQLChunkSearch
        from pipeline.postgres_chunk_rag import PostgreSQLChunkRAG
        from pipeline.postgres_chat_tools import PostgreSQLChatTools
        self.models = PostgreSQLChatModels()
        self.index = PostgreSQLChunkSearch(connect, self.models.embedding,
                                           release_model=self.models.release_embedding,
                                           evict_cache_after_search=True)
        try:
            self.rag = PostgreSQLChunkRAG(self.index, self.models.rerank)
            self.tools = PostgreSQLChatTools(connect, None, chunk_rag=self.rag,
                                             portfolio_provider=portfolio_provider)
        except BaseException:
            self.index.close()
            raise

    def close(self):
        self.index.close()
