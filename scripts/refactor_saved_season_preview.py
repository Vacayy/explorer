"""Read season results from the older, read-only local preview snapshot."""
from fastapi import FastAPI
import uvicorn
from models.earnings_season import SeasonOverview
from pipeline.earnings_chain import season_overview, sector_detail

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get('/api/spine/transcript/season', response_model=SeasonOverview)
def season_view(season: str | None = None):
    return season_overview(season, persist_core=False)


@app.get('/api/spine/transcript/season/sector/{key}')
def sector_view(key: str, season: str | None = None):
    return sector_detail(key, season, persist_core=False)


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
