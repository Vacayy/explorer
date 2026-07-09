import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DART_API_KEY = os.getenv("DART_API_KEY", "")
DB_PATH = Path(__file__).resolve().parent / "db" / "stock_explorer.db"

# 가설·메모 vault (소유권 분할: notes/=사람 원본, entities/=DB 투영 — 수정 무시)
VAULT_PATH = Path(os.getenv("VAULT_PATH", str(Path(__file__).resolve().parent.parent / "vault")))

# 수집 미디어 (텔레그램 이미지 등) — CDN URL 만료 대비 로컬 보관, /media로 서빙
MEDIA_PATH = Path(os.getenv("MEDIA_PATH", str(Path(__file__).resolve().parent.parent / "media")))

# Cache TTL in seconds
CACHE_TTL_STOCK_PRICES = 86400       # 1 day
CACHE_TTL_FINANCIALS = 7 * 86400     # 7 days
CACHE_TTL_DISCLOSURES = 86400        # 1 day
CACHE_TTL_BUSINESS = 30 * 86400      # 30 days
