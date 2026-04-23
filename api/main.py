"""FastAPI application entrypoint."""
from __future__ import annotations

import logging

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import games, incidents, referees, teams
from config import settings

logging.basicConfig(level=settings.log_level)
log = structlog.get_logger(__name__)

app = FastAPI(
    title="Euroleague Referee Error Tracker",
    description="AI-powered referee error detection and analytics for EuroLeague basketball.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else ["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────

API_PREFIX = "/api/v1"

app.include_router(games.router, prefix=API_PREFIX)
app.include_router(referees.router, prefix=API_PREFIX)
app.include_router(teams.router, prefix=API_PREFIX)
app.include_router(incidents.router, prefix=API_PREFIX)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=settings.app_env == "development")
