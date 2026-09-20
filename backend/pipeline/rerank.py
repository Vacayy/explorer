"""로컬 크로스인코더 리랭커 — LLM 0 (docs/specs/chat-retrieval.md, D-132).

- 모델: jinaai/jina-reranker-v2-base-multilingual (fastembed, 1.1GB). 실측 한국어 쌍 판별 정상, 40쌍 1.4초.
- `RERANK_MODEL=""` 로 비활성. import·로드 실패 시 None을 돌려 호출부가 RRF 순으로 degrade.
- 준비된 로컬 캐시만 lazy 로드한다. 캐시가 없으면 원래 검색 순서를 유지하며 요청 중 다운로드하지 않는다.
"""
import os
import threading

RERANK_MODEL = os.getenv("RERANK_MODEL", "jinaai/jina-reranker-v2-base-multilingual")

_enc = None
_failed = False
_lock = threading.Lock()


def available() -> bool:
    return bool(RERANK_MODEL) and not _failed


def _get():
    global _enc, _failed
    if _enc is not None or _failed or not RERANK_MODEL:
        return _enc
    with _lock:
        if _enc is None and not _failed:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
                _enc = TextCrossEncoder(RERANK_MODEL, local_files_only=True)
            except Exception as e:  # noqa: BLE001 — 미가용은 조용히 degrade하되 이유는 남긴다
                _failed = True
                print(f"[rerank] 비활성 — {type(e).__name__}: {str(e)[:120]}", flush=True)
    return _enc


def rerank(query: str, texts: list[str]) -> list[float] | None:
    """(query, text) 쌍 점수. 미가용이면 None."""
    if not texts:
        return []
    enc = _get()
    if enc is None:
        return None
    try:
        return [float(s) for s in enc.rerank(query, texts)]
    except Exception as e:  # noqa: BLE001
        print(f"[rerank] 실패 — {type(e).__name__}: {str(e)[:120]}", flush=True)
        return None
