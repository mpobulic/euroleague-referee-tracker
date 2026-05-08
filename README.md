# Euroleague Referee Error Tracker

AI-powered system to detect, classify, and track referee errors in EuroLeague basketball.

## Current Status

- Implemented: game/referee/play-by-play ingestion, context-based incident classification, incident persistence, API analytics endpoints, Streamlit dashboard.
- Partially implemented: video download/frame extraction utilities exist, but the production ingestion flow currently runs context-first incident analysis.
- In progress: vision-assisted incident classification, richer model-assisted validation, and broader production hardening.

## Architecture

```
┌──────────────────────────────────┐
│        Euroleague Public API     │  play-by-play, games, referees, teams
│        Video (yt-dlp / VOD)      │
└───────────────┬──────────────────┘
                │
┌───────────────▼──────────────────┐
│        Ingestion Layer           │
│  euroleague_api · pipeline ·     │
│  video_processor · scheduler     │
└───────────────┬──────────────────┘
                │
┌───────────────▼──────────────────┐
│           AI Layer               │
│  context_builder (game context)  │
│  player_detector  (YOLOv8)       │
│  call_classifier  (GPT-4o Vision)│
└───────────────┬──────────────────┘
                │
┌───────────────▼──────────────────┐   ┌─────────────────────┐
│  PostgreSQL  (SQLAlchemy ORM)    │◄──►│  Analytics          │
│  Alembic migrations              │   │  referee_stats      │
└───────────────┬──────────────────┘   │  team_bias          │
                │                      │  game_log           │
┌───────────────▼──────────────────┐   └─────────────────────┘
│      FastAPI  /api/v1            │
│  /games · /referees · /teams     │
│  /incidents                      │
└───────────────┬──────────────────┘
                │
┌───────────────▼──────────────────┐
│   Streamlit Dashboard :8501      │
│  Overview · Referees · Teams     │
│  Games · Incidents               │
└──────────────────────────────────┘
```

## Quick Start

```bash
# 1. Clone and set up environment
cp .env.example .env
# Edit .env – add OPENAI_API_KEY at minimum

# 2. Start services
docker-compose up -d

# 3. Run migrations
docker-compose exec api alembic upgrade head

# 4. Ingest a round (e.g. Round 20 of the 2024-25 season)
docker-compose run --rm ingestion python -m ingestion.scheduler --season E2024 --round 20

# 5. Open dashboard
open http://localhost:8501
# API docs at http://localhost:8000/docs
```

## What It Detects (Current)

| Error Type | Detection Method |
|---|---|
| Wrong foul call | GPT model using play-by-play context |
| Missed foul | GPT model using play-by-play context |
| Wrong/missed violation | GPT model using play-by-play context |
| Charge/block and other call quality errors | GPT model using play-by-play context |
| Video-assisted evidence extraction | Utility modules present; not default in ingestion pipeline yet |

## API Endpoints

```
GET  /api/v1/games?season=E2024&round=20
GET  /api/v1/games/{game_code}/incidents
GET  /api/v1/referees/rankings?season=E2024&min_games=5
GET  /api/v1/referees/{id}/stats
GET  /api/v1/teams/bias?season=E2024
GET  /api/v1/teams/{code}/bias
GET  /api/v1/incidents?severity=high&incident_type=wrong_foul_call
PATCH /api/v1/incidents/{id}   # human review / override
```

## AI Pipeline

**Phase 1 (context-only, active):** Play-by-play events are parsed, game context is assembled, and GPT-4o classifies candidate foul/violation events. Errors are persisted as incidents for analytics/dashboard usage.

**Phase 2 (vision, in progress):** Video can be downloaded via yt-dlp and frames can be extracted with OpenCV. Integrating this path into the default ingestion/classification flow is the next step.

## Testing

```bash
# Run all tests
python -m pytest

# Run focused suites
python -m pytest tests/test_api.py
python -m pytest tests/test_ingestion_pipeline.py
```

CI runs on every push and pull request and executes the full pytest suite.

## Project Structure

```
euroleague-referee-tracker/
├── api/             FastAPI app + routes
├── analytics/       referee_stats · team_bias · game_log
├── dashboard/       Streamlit UI
├── db/              SQLAlchemy models + Alembic migrations
├── ingestion/       API client + video processor + scheduler
├── models/          AI call classifier + player detector + context builder
├── tests/           pytest test suite
├── config.py        Centralised settings (pydantic-settings)
├── docker-compose.yml
├── Dockerfile
└── alembic.ini
```

## Roadmap

- **Phase 1** ✅ API ingestion + GPT-4o classification + Streamlit dashboard
- **Phase 2** Video pipeline: YOLOv8 frame analysis, frame-level evidence
- **Phase 3** Fine-tune dedicated classifier on labelled EuroLeague data
- **Phase 4** Live monitoring, WebSocket alerts, React frontend
- **Phase 5** Community incident reporting, public API, model retraining loop
