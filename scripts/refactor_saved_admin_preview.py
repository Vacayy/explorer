"""Local-only saved admin reads from the older rehearsal snapshot.

This is not live scheduler status. The DB is mounted read-only and no worker
or write endpoint is started. Observe's in-process usage queue is empty here.
"""
from fastapi import FastAPI
import uvicorn

from pipeline import observe
from routers import spine_admin

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
observe.flush = lambda: None


@app.get('/api/spine/admin/jobs')
def jobs():
    return spine_admin.jobs()


@app.get('/api/spine/admin/runs')
def runs(limit: int = 50):
    return spine_admin.runs(limit=max(1, min(limit, 500)))


@app.get('/api/spine/admin/observe')
def observation(days: int = 7):
    return observe.summary(max(1, min(days, 90)))


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
