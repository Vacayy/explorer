import json as _json

from fastapi import APIRouter

def _httpx():
    import httpx
    return httpx

router = APIRouter(prefix="/api/onchain", tags=["onchain"])

HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"
POLYMARKET_URL = "https://gamma-api.polymarket.com/events"

# Top crypto assets to track (by typical volume)
TOP_ASSETS = ["BTC", "ETH", "SOL", "HYPE", "XRP"]

# Stock tokens available on Hyperliquid spot
STOCK_TOKENS = {
    "TSLA", "NVDA", "GOOGL", "AAPL", "AMZN", "META", "MSFT",
    "SPY", "QQQ", "MSTR", "AVGO", "ORCL", "MU", "GLD", "QQQM",
}

POLYMARKET_CATEGORIES = [
    {"slug": "finance", "label": "Finance"},
    {"slug": "economy", "label": "Economy"},
    {"slug": "tech", "label": "Tech"},
    {"slug": "geopolitics", "label": "Geopolitics"},
]


@router.get("/hyperliquid")
async def get_hyperliquid_data():
    """Fetch crypto perps + tokenized stock spot data from Hyperliquid."""
    async with _httpx().AsyncClient(timeout=10) as client:
        perp_resp = await client.post(HYPERLIQUID_URL, json={"type": "metaAndAssetCtxs"})
        perp_resp.raise_for_status()
        perp_data = perp_resp.json()

        spot_resp = await client.post(HYPERLIQUID_URL, json={"type": "spotMetaAndAssetCtxs"})
        spot_resp.raise_for_status()
        spot_data = spot_resp.json()

    # --- Perps ---
    meta = perp_data[0]["universe"]
    ctxs = perp_data[1]

    assets = []
    for m, c in zip(meta, ctxs):
        name = m["name"]
        vol = float(c.get("dayNtlVlm", 0))
        mark_px = float(c.get("markPx", 0))
        prev_day_px = float(c.get("prevDayPx", 0))
        change_pct = ((mark_px - prev_day_px) / prev_day_px * 100) if prev_day_px else 0
        assets.append({
            "name": name,
            "markPx": mark_px,
            "prevDayPx": prev_day_px,
            "changePct": round(change_pct, 2),
            "funding": c.get("funding"),
            "openInterest": float(c.get("openInterest", 0)),
            "dayNtlVlm": vol,
        })

    top_by_name = [a for a in assets if a["name"] in TOP_ASSETS]
    top_by_name.sort(key=lambda x: TOP_ASSETS.index(x["name"]))

    assets.sort(key=lambda x: x["dayNtlVlm"], reverse=True)
    top_by_volume = assets[:10]

    # --- Spot stocks ---
    spot_tokens = spot_data[0].get("tokens", [])
    spot_universe = spot_data[0].get("universe", [])
    spot_ctxs = spot_data[1]
    token_map = {t["index"]: t["name"] for t in spot_tokens}

    stocks = []
    for i, (u, c) in enumerate(zip(spot_universe, spot_ctxs)):
        pair_tokens = u.get("tokens", [])
        for pt in pair_tokens:
            name = token_map.get(pt, "")
            if name in STOCK_TOKENS:
                mid_px = c.get("midPx")
                mark_px = c.get("markPx")
                prev_day = c.get("prevDayPx")
                price = float(mid_px) if mid_px else (float(mark_px) if mark_px else 0)
                prev = float(prev_day) if prev_day else 0
                change_pct = ((price - prev) / prev * 100) if prev else 0
                stocks.append({
                    "name": name,
                    "midPx": float(mid_px) if mid_px else None,
                    "markPx": float(mark_px) if mark_px else None,
                    "changePct": round(change_pct, 2),
                    "dayNtlVlm": float(c.get("dayNtlVlm", 0)),
                })

    stocks.sort(key=lambda x: x["dayNtlVlm"], reverse=True)

    return {
        "featured": top_by_name,
        "top_volume": top_by_volume,
        "stocks": stocks,
    }


@router.get("/polymarket")
async def get_polymarket_data():
    """Fetch top prediction market events by category from Polymarket."""
    results = {}
    async with _httpx().AsyncClient(timeout=10) as client:
        for cat in POLYMARKET_CATEGORIES:
            resp = await client.get(
                POLYMARKET_URL,
                params={
                    "limit": 3,
                    "active": "true",
                    "closed": "false",
                    "tag_slug": cat["slug"],
                    "order": "volume",
                    "ascending": "false",
                },
            )
            resp.raise_for_status()
            events = resp.json()

            parsed = []
            for ev in events:
                markets = []
                for m in ev.get("markets", [])[:5]:
                    prices = m.get("outcomePrices", "[]")
                    if isinstance(prices, str):
                        prices = _json.loads(prices)
                    yes_price = float(prices[0]) if prices and prices[0] else None
                    markets.append({
                        "question": m.get("question"),
                        "yesPrice": yes_price,
                        "volume": float(m.get("volumeNum", 0)),
                    })
                parsed.append({
                    "title": ev.get("title"),
                    "slug": ev.get("slug"),
                    "volume": float(ev.get("volume", 0)),
                    "markets": markets,
                })
            results[cat["slug"]] = {
                "label": cat["label"],
                "events": parsed,
            }

    return results
