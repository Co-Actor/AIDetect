# AIDetect

Multi-signal AI text detector. Hybrid scoring: statistical signals + pattern matching + LLM-as-judge with calibrated rubric.

> Working title. Public/commercial name TBD.

## Layout

```
AIDetect/
├── backend/          # FastAPI service: detection API, scoring engine, rubric
├── frontend/         # Quasar 2 SPA: web UI for the detector
├── docker-compose.yml
└── Makefile          # convenience commands
```

Each subproject has its own README with setup instructions.

## Quick start (local dev)

```bash
# backend (terminal 1) — serves on http://localhost:8010
cd backend
cp .env.example .env        # set AIDETECT_INTERNAL_TOKEN and OPENROUTER_API_KEY
uv sync                     # or: pip install -e ".[dev]"
uv run uvicorn aidetect.main:app --reload --port 8010

# frontend (terminal 2) — serves on http://localhost:9000
cd frontend
cp .env.example .env
pnpm install                # or: npm install
pnpm dev
```

Default ports: backend `8010`, frontend `9000`, redis `6380` (Redis is optional —
the cache falls back to in-memory if unreachable).

Or use Docker Compose:

```bash
docker compose up --build
```

## Architecture

Three independent signal layers feed a calibrated aggregator:

- **Layer A — Statistical** (sync, ~5ms): burstiness, TTR, sentence-CV, formatting density.
- **Layer B — Pattern matching** (sync, ~10ms): banned phrases, structural patterns, formatting habits. Driven by `backend/src/aidetect/rubric/v1/`.
- **Layer C — LLM-as-judge** (async, 1-3s): rubric-based scoring via OpenRouter (default `claude-haiku-4-5`).

Aggregator weights are calibrated on a ground-truth dataset (Co.Actor live posts + synthetic AI + public benchmarks).

## Status

Phase 0: skeleton. Phase 1 (MVP): in progress.
