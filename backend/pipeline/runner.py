"""파이프라인 실행: 커넥터 하나를 돌려 척추에 적재한다."""
from pipeline.base import SourceConnector
from pipeline.store import store_document


def run_source(connector: SourceConnector) -> dict:
    stats = {"refs": 0, "docs": 0, "new": 0, "updated": 0, "unchanged": 0}
    for ref in connector.discover():
        stats["refs"] += 1
        for doc in connector.fetch(ref):
            r = store_document(doc)
            stats["docs"] += 1
            stats[r["status"]] += 1
            # 선택적 훅 — 적재된 doc_id를 커넥터가 자기 원장에 되쓴다 (예: scrap_links)
            hook = getattr(connector, "after_store", None)
            if hook:
                try:
                    hook(doc, r)
                except Exception:  # noqa: BLE001 — 부가 기록 실패가 수집을 막지 않는다
                    pass
    return stats
