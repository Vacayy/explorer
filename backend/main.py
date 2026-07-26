from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config import MEDIA_PATH
from database import init_db
from routers import companies, financials, disclosures, ir_notes, stock_prices, business, industries, onchain, kpi
from routers import watchlist, screener, signals, catalysts, compare, consensus, index_data
from routers import telegram_feed
from routers import blog_feed
from routers import spine_feed, spine_signals, spine_home, spine_ask, spine_follows, spine_actions, spine_doc, spine_digests, spine_keywords, spine_sources
from routers import spine_brief, spine_conversations, spine_person, spine_knowledge, spine_approvals
from routers import spine_quotes, spine_sector_map, spine_feature_days, spine_company, spine_narrative, spine_research, spine_report, spine_admin
from routers import spine_causal
from routers import spine_transcript
from routers import spine_trade
from routers import spine_questions

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
app.include_router(spine_quotes.router)
app.include_router(spine_sector_map.router)
app.include_router(spine_feature_days.router)
app.include_router(spine_company.router)
app.include_router(spine_narrative.router)
app.include_router(spine_research.router)
app.include_router(spine_report.router)
app.include_router(spine_admin.router)
app.include_router(spine_causal.router)
app.include_router(spine_causal.beneficiary_router)
# spine_sources에 youtube 추가됨 (별도 등록 불필요 — 이미 include됨)
app.include_router(spine_feed.router)
app.include_router(spine_signals.router)
app.include_router(spine_home.router)
app.include_router(spine_ask.router)
app.include_router(spine_follows.router)
app.include_router(spine_actions.router)
app.include_router(spine_doc.router)
app.include_router(spine_digests.router)
app.include_router(spine_keywords.router)
app.include_router(spine_sources.router)
app.include_router(spine_brief.router)
app.include_router(spine_conversations.router)
app.include_router(spine_person.router)
app.include_router(spine_knowledge.router)
app.include_router(spine_approvals.router)
app.include_router(spine_approvals.agent_router)
app.include_router(spine_transcript.router)
app.include_router(spine_trade.router)
app.include_router(spine_questions.router)


MEDIA_PATH.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_PATH)), name="media")


@app.on_event("startup")
def startup():
    init_db()
    # 텔레그램 봇 양방향 (토큰·chat_id 설정 시에만, TELEGRAM_POLLING=0으로 비활성)
    from pipeline.bot import start_bot
    start_bot()


@app.get("/api/health")
def health():
    return {"status": "ok"}
