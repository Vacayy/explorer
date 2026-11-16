"""Read season results from the older, read-only local preview snapshot."""
from fastapi import FastAPI
import uvicorn
from copy import deepcopy
from datetime import date
from threading import Lock
from models.earnings_season import SeasonOverview
from pipeline.earnings_chain import compute_core, season_overview, sector_detail

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
_cache = {}
_cache_lock = Lock()


def cached_core(conn, season):
    """Cache only recalculation of this fixed read-only snapshot for the day."""
    key = (date.today(), season)
    with _cache_lock:
        if key not in _cache:
            result = compute_core(conn, season, persist=False)
            for previous in list(_cache):
                if previous[0] != key[0]:
                    del _cache[previous]
            if len(_cache) >= 8:
                del _cache[next(iter(_cache))]
            _cache[key] = result
        return deepcopy(_cache[key])


@app.get('/api/spine/transcript/season', response_model=SeasonOverview)
def season_view(season: str | None = None):
    return season_overview(season, persist_core=False, recompute_core=cached_core)


@app.get('/api/spine/transcript/season/sector/{key}')
def sector_view(key: str, season: str | None = None):
    return sector_detail(key, season, persist_core=False, recompute_core=cached_core)


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
