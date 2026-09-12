"""커넥터 레지스트리 — 새 소스는 여기 등록만 하면 파이프라인에 붙는다."""
from pipeline.connectors.blog import BlogConnector
from pipeline.connectors.notes import NoteConnector
from pipeline.connectors.scrap import ScrapConnector
from pipeline.connectors.telegram import TelegramConnector
from pipeline.connectors.youtube import YouTubeConnector

CONNECTORS = {
    "blog": BlogConnector,
    "telegram": TelegramConnector,
    "note": NoteConnector,
    "youtube": YouTubeConnector,
    # 스크랩은 telegram 문서를 입력으로 삼으므로 telegram 뒤에 돈다 (CONNECTORS는 삽입 순서 유지)
    "scrap": ScrapConnector,
}
