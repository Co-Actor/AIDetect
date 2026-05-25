# AIDetect — Project Context for Claude Code

> Project-scoped CLAUDE.md for AIDetect. Loaded in any session that starts inside
> `/Users/nicksonet/myproject/memory/AIDetect/`. Extends the parent
> `/Users/nicksonet/myproject/CLAUDE.md` and overrides it where rules differ
> (e.g. Python 3.12 instead of 3.11).

## 1. What this project is

**AIDetect** — multi-signal AI text detector. Hybrid scoring: three independent
signal layers feed a calibrated aggregator.

| Layer | What it does | Latency | Source |
|---|---|---|---|
| **A. Statistical** | burstiness, type-token ratio, sentence-CV, formatting density | ~5 ms (sync) | backend / `services/` |
| **B. Pattern matching** | banned phrases, structural patterns, formatting habits | ~10 ms (sync) | `backend/src/aidetect/rubric/v1/` |
| **C. LLM-as-judge** | rubric-based scoring via OpenRouter (default `claude-haiku-4-5`) | 1–3 s (async) | OpenRouter API |

Aggregator weights are calibrated on a ground-truth dataset (Co.Actor live posts + synthetic AI + public benchmarks).

**Working title — public name not chosen yet.** Status: Phase 0 (skeleton), Phase 1 (MVP) in progress.

## 2. Layout

```
AIDetect/
├── backend/                  # FastAPI Python 3.12 — detection API, scoring engine, rubric
│   ├── src/aidetect/
│   │   ├── main.py           # FastAPI app, /v1 prefix
│   │   ├── config.py         # pydantic-settings, env-driven
│   │   ├── api/v1/           # routers: health, detections, feedback, rewrite, rubric
│   │   ├── services/         # cache, llm, scoring engine, etc.
│   │   ├── rubric/v1/        # pattern matching rules (Layer B)
│   │   └── models/           # data models
│   ├── tests/
│   ├── data/                 # feedback log, calibration data (gitignored)
│   ├── pyproject.toml        # uv-managed
│   ├── Dockerfile
│   └── .env.example
├── frontend/                 # Quasar 2 SPA (Vue 3, TypeScript)
│   ├── src/                  # views, components, stores
│   ├── quasar.config.ts
│   ├── nginx.conf            # production serving config
│   ├── package.json          # pnpm-managed
│   └── Dockerfile
├── infra/
│   ├── helm/aidetect/        # Helm chart (deploys to AKS)
│   │   ├── Chart.yaml
│   │   ├── values.yaml       # defaults
│   │   ├── values-dev.yaml   # dev overrides
│   │   └── templates/
│   └── README.md             # Azure deploy guide (copy-paste bootstrap)
├── .github/workflows/
│   └── deploy-dev.yml        # CI/CD — fires on push to development branch
├── docker-compose.yml        # local dev (backend + frontend + redis)
├── Makefile
└── CLAUDE.md                 # ← this file
```

## 3. Local development

| Command | What it does |
|---|---|
| `make install` | `uv sync` for backend + `pnpm install` for frontend |
| `make backend` | uvicorn dev server at http://localhost:8010 |
| `make frontend` | Quasar dev server at http://localhost:9000 |
| `make redis-up` | Redis in docker-compose on port 6380 |
| `make test` | `pytest` for backend |
| `make lint` | ruff + mypy for backend, eslint for frontend |
| `docker compose up --build` | full local stack (backend + frontend + redis) |

**Default ports:** backend `8010`, frontend `9000`, redis `6380` (in-memory fallback if Redis is unreachable).

## 4. Tooling / language

- **Python 3.12** for backend (`pyproject.toml` requirement — **overrides** the Python 3.11 rule from the parent CLAUDE.md).
- **Node 20** for frontend (see Dockerfile).
- **uv** for Python dependencies.
- **pnpm** for Node dependencies (npm fallback).
- **Black/isort/flake8** are replaced by **ruff** (see `[tool.ruff]` in `pyproject.toml`).
- **mypy strict** for backend.
- User-facing communication — in Russian. Code and comments — in English (rule from the parent CLAUDE.md).

## 5. Deployment pipeline

### Where things live
- **Dev deploy branch:** `development`
- **Workflow:** `.github/workflows/deploy-dev.yml`
- **Registry:** GHCR — `ghcr.io/co-actor/aidetect-backend:<sha>`, `ghcr.io/co-actor/aidetect-frontend:<sha>`
- **Auth:** GitHub Actions → `GITHUB_TOKEN` for GHCR push, Azure OIDC federated identity for `az aks get-credentials`
- **Target:** AKS cluster `aks-memory-actor` (eastus2), namespace `dev` (shared with other Co.Actor services)
- **Helm release name:** `aidetect-dev`
- **Resources:** Deployments `aidetect-dev-backend`, `aidetect-dev-frontend` + Services + Ingress
- **Domains:** `aidetect.co.actor` (frontend) + `apiaidetect.co.actor` (backend API)
- **TLS:** cert-manager + `letsencrypt-prod` ClusterIssuer, secret `aidetect-dev-tls`
- **Secrets:** Azure Key Vault `kv-aidetect-dev` → CSI driver → Opaque secret `aidetect-dev-backend-env`

### Pipeline jobs (sequential)
1. `detect-changes` — `dorny/paths-filter` detects which services changed (`backend/`, `frontend/`).
2. `build-and-push` (matrix: backend, frontend) — `docker/build-push-action` pushes images to GHCR with tags `<sha>` + `dev-latest`.
3. `deploy` — `az aks get-credentials` → `helm upgrade --install aidetect-dev` with overrides `image.tag=<sha>`, `image.registry`, `azure.backendUamiClientId`, hosts. `kubectl rollout status` waits for both deployments.

Manual trigger: Actions → Deploy to AKS (development) → Run workflow.

## 6. ⚠️ MANDATORY: verify deploy and pipeline via `gh`

**After EVERY `git push origin development` (or manual workflow trigger):**

```bash
# 1) Find the latest workflow run ID
gh run list --workflow=deploy-dev.yml --limit 5

# 2) Watch a specific run in real time
gh run watch <run-id>

# 3) Inspect run details (jobs, statuses)
gh run view <run-id>

# 4) On failure — logs from failed steps only
gh run view <run-id> --log-failed

# 5) Full logs of the entire run
gh run view <run-id> --log
```

**Shortcuts:**
```bash
# Latest run on the current branch
gh run list --branch development --limit 1
gh run view --log-failed  # without an id, uses the latest run

# Rerun a failed run
gh run rerun <run-id>
gh run rerun <run-id> --failed   # only failed jobs

# Manual trigger (workflow_dispatch)
gh workflow run deploy-dev.yml --ref development -f services=all
```

**Rule:** "push succeeded" ≠ "deploy succeeded". A successful push only means Git accepted the commit. Real verification is `gh run view` showing all 3 jobs green AND the `kubectl rollout status` smoke-check passing. Without `gh` confirmation, **the deploy is not considered complete**.

## 7. Azure infrastructure (already bootstrapped or pending)

| Resource | Name | Purpose |
|---|---|---|
| AKS cluster | `aks-memory-actor` | Shared cluster in RG `DefaultResourceGroup-EUS`, eastus2 |
| Namespace | `dev` | Shared with other Co.Actor dev services |
| Key Vault | `kv-aidetect-dev` | Runtime secrets for backend |
| Azure Cache for Redis | `redis-aidetect-dev` | Basic C0, TLS port 6380, scheme `rediss://` |
| UAMI (CI) | `id-aidetect-development-deploy` | OIDC federated with GH Actions, role: AKS Cluster User |
| UAMI (backend) | `id-aidetect-development-backend` | OIDC federated with K8s SA, role: KV Secrets User |
| Ingress controller | `ingress-nginx` (shared) | LB IP `52.254.109.26` |
| ClusterIssuer | `letsencrypt-prod` (shared) | cert-manager issues TLS automatically |

**Subscription:** `Basic` (`71ddbd6b-dfbd-4293-bfbd-155afd7b518d`), tenant `126403ee-2465-4019-8431-5a17899b6774`.

## 8. Bootstrap (`infra/README.md`)

Bootstrap commands live in `infra/README.md` (§1–§7) — copy-paste az/kubectl/gh blocks. Run once when setting up the environment.

Steps left to do manually after the README has been run through:
- DNS A records: `aidetect.co.actor` + `apiaidetect.co.actor` → `52.254.109.26`
- Make GHCR packages public (Settings → Packages) or set `GHCR_PULL_SECRET_NAME`

## 9. Secrets and config

### Backend env (config.py)
| Variable | Where it lives in prod | Required |
|---|---|---|
| `AIDETECT_INTERNAL_TOKEN` | KV → CSI mount → envFrom | yes (≥8 chars, validated by Pydantic) |
| `OPENROUTER_API_KEY` | KV → CSI mount → envFrom | yes (Layer C fails without it) |
| `REDIS_URL` | KV (Azure Cache for Redis TLS URL) | optional (in-memory fallback) |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | KV (added when Langfuse is deployed) | optional (`LANGFUSE_ENABLED=0` by default) |
| `COACTOR_DATABASE_URL` | not used at runtime | only for offline ground-truth scripts |

### Helm chart inputs (overridden via `--set` in workflow)
- `image.registry`, `image.tag` — registry / SHA
- `image.pullSecretName` — empty if packages are public, otherwise a docker-registry secret name
- `azure.backendUamiClientId` — UAMI clientId for backend SA workload identity
- `ingress.hosts.api`, `ingress.hosts.app` — hosts

## 10. Operational rules (project-specific)

- **Minimal diff** — rule from the parent CLAUDE.md. No incidental refactors in a bug-fix PR.
- **No bullet-point commit messages**, no "Generated with Claude" / Co-Authored-By trailers. One short line.
- **Before opening a PR to main:** locally `cd backend && uv run pytest && uv run ruff check . && uv run mypy src` + `cd frontend && pnpm build && pnpm lint`.
- **Every backend change ships a test.** Bug fixes must include a regression test.
- **DB migrations** (if any get introduced) — numbered files `backend/migrations/NNN_*.up.sql` + `*.down.sql`. No ad-hoc SQL.
- **Optional integrations** (Langfuse today, Stripe/OAuth/Sentry later) MUST be no-op when their env vars are empty.
- **Never merge to `main` with red tests.** Never disable a test "to make CI pass".

## 11. Sessions log

Decisions made in this session (deploy setup) live in `.claude/sessions/2026-05-25_aks-helm-deploy-setup.md` (if the session-log practice from the parent CLAUDE.md is enabled). This file captures repeatable facts about the project only — current work state lives in git.
