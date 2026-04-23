"""
Ingestion scheduler – orchestrates API + video ingestion runs.

Usage:
    python -m ingestion.scheduler --season E2024 --round 30
    python -m ingestion.scheduler --season E2024 --all-rounds
    python -m ingestion.scheduler --daemon          # runs nightly via APScheduler
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from db.connection import AsyncSessionFactory
from ingestion.pipeline import IngestionPipeline

log = structlog.get_logger(__name__)


async def run_round(season_code: str, round_number: int) -> None:
    async with AsyncSessionFactory() as session:
        pipeline = IngestionPipeline(session)
        await pipeline.ingest_round(season_code, round_number)


async def run_all_rounds(season_code: str) -> None:
    async with AsyncSessionFactory() as session:
        pipeline = IngestionPipeline(session)
        await pipeline.ingest_all_rounds(season_code)


async def run_daemon() -> None:
    scheduler = AsyncIOScheduler()
    # Nightly at 03:00 UTC – ingest latest round of current season
    scheduler.add_job(
        _nightly_job,
        trigger="cron",
        hour=3,
        minute=0,
        id="nightly_ingest",
    )
    scheduler.start()
    log.info("Scheduler started; running nightly at 03:00 UTC")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


async def _nightly_job() -> None:
    """Ingest the most recent round of the current Euroleague season."""
    from ingestion.euroleague_api import EuroleagueClient

    async with EuroleagueClient() as client:
        seasons = await client.get_seasons()
        if not seasons:
            log.warning("No seasons found")
            return
        # Pick current (highest year) season
        current_season = max(seasons, key=lambda s: s.get("year", 0))
        season_code = current_season.get("code") or current_season.get("seasonCode")

    # Determine latest round number heuristically from today's date
    today = datetime.utcnow()
    # Regular season runs Oct–Apr; 34 rounds; rough estimate
    season_start = datetime(today.year - 1, 10, 1) if today.month < 8 else datetime(today.year, 10, 1)
    weeks_elapsed = max(1, (today - season_start).days // 7)
    latest_round = min(weeks_elapsed, 34)

    log.info("Nightly ingest", season=season_code, round=latest_round)
    await run_round(season_code, latest_round)


def main() -> None:
    logging.basicConfig(level=settings.log_level)
    parser = argparse.ArgumentParser(description="Euroleague ingestion scheduler")
    parser.add_argument("--season", default="E2024", help="Season code, e.g. E2024")
    parser.add_argument("--round", type=int, dest="round_number", help="Single round number")
    parser.add_argument("--all-rounds", action="store_true", help="Ingest all rounds in season")
    parser.add_argument("--daemon", action="store_true", help="Run as nightly daemon")
    args = parser.parse_args()

    if args.daemon:
        asyncio.run(run_daemon())
    elif args.all_rounds:
        asyncio.run(run_all_rounds(args.season))
    elif args.round_number:
        asyncio.run(run_round(args.season, args.round_number))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
