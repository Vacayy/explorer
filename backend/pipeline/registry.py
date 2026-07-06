"""커넥터 레지스트리 — 새 소스는 여기 등록만 하면 파이프라인에 붙는다."""
from pipeline.connectors.blog import BlogConnector
from pipeline.connectors.telegram import TelegramConnector

CONNECTORS = {
    "blog": BlogConnector,
    "telegram": TelegramConnector,
}
