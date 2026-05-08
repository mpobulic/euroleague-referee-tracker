# Ingestion Runbook

This runbook describes how to ingest data safely and recover from failures.

## Standard ingestion

Run a single round:

```bash
python -m ingestion.scheduler --season E2024 --round 20
```

Run all rounds:

```bash
python -m ingestion.scheduler --season E2024
```

## Failure behavior

- Round ingestion runs per-game tasks concurrently.
- If one or more games fail, the current run is rolled back and exits with an error.
- No partial successful commit should be considered final for that failed run.

## Retry strategy

1. Retry the same command once to rule out transient upstream API/network issues.
2. If retry fails, run the specific round again during a quieter period.
3. Check API provider availability and credentials.

## Backfill strategy

- Use season+round commands to backfill historical gaps in deterministic batches.
- Re-running ingestion is safe for auto-generated incidents because those are regenerated per game.

## Operational checks

- API health endpoint responds: `/health`
- Games exist for the target season/round.
- `analysis_complete` becomes true for ingested games.
- Incident counts are non-zero for games with candidate foul/violation events.
