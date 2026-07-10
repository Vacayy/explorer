from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config import MEDIA_PATH
from database import init_db
from routers import companies, financials, disclosures, ir_notes, stock_prices, business, industries, onchain, kpi
from routers import watchlist, screener, signals, catalysts, compare, consensus, index_data
from routers import telegram_feed
from routers import blog_feed
from routers import spine_feed, spine_signals, spine_home, spine_ask, spine_follows, spine_actions, spine_doc

app = FastAPI(title="Stock Explorer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(companies.router)
app.include_router(financials.router)
app.include_router(disclosures.router)
app.include_router(ir_notes.router)
app.include_router(stock_prices.router)
app.include_router(business.router)
app.include_router(industries.router)
app.include_router(onchain.router)
app.include_router(kpi.router)
app.include_router(watchlist.router)
app.include_router(screener.router)
app.include_router(signals.router)
app.include_router(catalysts.router)
app.include_router(compare.router)
app.include_router(consensus.router)
app.include_router(index_data.router)
app.include_router(telegram_feed.router)
app.include_router(blog_feed.router)
app.include_router(spine_feed.router)
app.include_router(spine_signals.router)
app.include_router(spine_home.router)
app.include_router(spine_ask.router)
app.include_router(spine_follows.router)
app.include_router(spine_actions.router)
app.include_router(spine_doc.router)


MEDIA_PATH.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_PATH)), name="media")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}
