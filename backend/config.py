import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DART_API_KEY = os.getenv("DART_API_KEY", "")
DB_PATH = Path(__file__).resolve().parent / "db" / "stock_explorer.db"

# Cache TTL in seconds
CACHE_TTL_STOCK_PRICES = 86400       # 1 day
CACHE_TTL_FINANCIALS = 7 * 86400     # 7 days
CACHE_TTL_DISCLOSURES = 86400        # 1 day
CACHE_TTL_BUSINESS = 30 * 86400      # 30 days
