from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT, settings
from .db import Base, engine
from .routers import analytics, auth, conflicts, credentials, enrollments, ingest, integration, mocks, people
from .services import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
FRONTEND = Path(ROOT / "frontend" / "dist")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    stop = asyncio.Event()
    task = asyncio.create_task(jobs.loop(stop)) if settings.run_background_jobs else None
    yield
    stop.set()
    if task:
        await task


app = FastAPI(
    title="APAAR Registry API",
    version="0.1.0",
    description="Student-level national enrolment data layer keyed on APAAR. The web app uses only this API, "
                "the same one institution ERPs use. Authenticate with `Authorization: Bearer <token>` (staff/students) "
                "or `X-API-Key` (ERP clients). Endpoints tagged *simulated* stand in for external systems.",
    lifespan=lifespan,
)
for r in (auth, ingest, enrollments, conflicts, analytics, credentials, people, integration, mocks):
    app.include_router(r.router)


@app.get("/api/v1/health", tags=["meta"])
def health():
    return {"ok": True}


if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "mock/", "docs", "openapi.json")):
            raise HTTPException(404)
        f = FRONTEND / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
