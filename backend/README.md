# AIDetect — backend

FastAPI service implementing the AI-text detection API.

## Stack

- Python 3.12, FastAPI, Pydantic v2
- Redis (optional cache + idempotency; in-memory fallback if unavailable)
- OpenRouter for LLM-as-judge (default: `claude-haiku-4-5`)
- No database — auth is a single shared token, feedback writes to `data/feedback.jsonl`,
  ground-truth datasets live in `data/ground_truth/*.parquet`.
  A real DB will be introduced once we publish API keys to third parties.

## Setup

```bash
# 1. Install deps (uv recommended)
uv sync

# 2. Configure
cp .env.example .env
# minimally set: AIDETECT_INTERNAL_TOKEN, OPENROUTER_API_KEY
# optional: COACTOR_DATABASE_URL (read-only, only for scripts/build_ground_truth.py)

# 3. (optional) Start Redis for caching
docker compose -f ../docker-compose.yml up -d redis

# 4. Run dev server
uv run uvicorn aidetect.main:app --reload --port 8010
```

API docs: <http://localhost:8010/docs>

## Layout

```
src/aidetect/
├── main.py              FastAPI app factory
├── config.py            Settings (pydantic-settings)
├── api/
│   ├── deps.py          Auth / cache dependencies
│   └── v1/
│       ├── router.py
│       ├── detections.py
│       ├── feedback.py
│       └── health.py
├── schemas/             Pydantic API schemas
├── services/
│   ├── orchestrator.py  Runs signal layers, calls aggregator
│   ├── aggregator.py    Weighted scoring
│   ├── cache.py         Redis wrapper with in-memory fallback
│   ├── feedback_log.py  Append-only JSONL feedback writer
│   └── signals/
│       ├── statistical.py    Layer A
│       ├── patterns.py       Layer B
│       └── llm_judge.py      Layer C
└── rubric/v1/           YAML-driven banned phrases, structures, prompts

data/                    (gitignored)
├── feedback.jsonl       Append-only user feedback
└── ground_truth/        Calibration datasets (parquet)
```

## Tests

```bash
uv run pytest
```

## Scripts

- `scripts/build_ground_truth.py` — pulls labelled posts from Co.Actor read-only DB.
- `scripts/synth_ai_posts.py` — generates AI samples via OpenRouter for balanced training.
- `scripts/calibrate.py` — fits aggregator weights, writes `models/aggregator_v1.json`.
