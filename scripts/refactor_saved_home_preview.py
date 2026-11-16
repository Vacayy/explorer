"""Read-only home widgets for the isolated local refactor preview.

The mounted database is the older viewer snapshot. These endpoints call only
saved-data functions, never the original routes that may initiate collection.
"""
from fastapi import FastAPI, HTTPException
import uvicorn

from models.us import UsBriefing
from pipeline.macro import get_macro
from pipeline.market_regime import get_regime
from pipeline.us_briefing import build_briefing

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get('/api/spine/macro')
def macro():
    return get_macro()


@app.get('/api/spine/market-regime')
def market_regime():
    return get_regime()


@app.get('/api/spine/us/briefing', response_model=UsBriefing)
def us_briefing(force: bool = False, trade_date: str | None = None):
    if force:
        raise HTTPException(405, 'Collection is unavailable in the read-only preview')
    return build_briefing(force=False, trade_date=trade_date)


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
