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
    return stats
