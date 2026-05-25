# AIDetect — Project Context for Claude Code

> Этот файл — project-scoped CLAUDE.md для AIDetect. Загружается в любой сессии,
> которая стартует внутри `/Users/nicksonet/myproject/memory/AIDetect/`. Дополняет
> глобальный `/Users/nicksonet/myproject/CLAUDE.md` и переопределяет его там, где
> правила различаются (например, Python 3.12 вместо 3.11).

## 1. Что за проект

**AIDetect** — multi-signal AI text detector. Гибридный скоринг: три независимых
сигнальных слоя кормят калиброванный агрегатор.

| Layer | Что делает | Latency | Источник |
|---|---|---|---|
| **A. Statistical** | burstiness, type-token ratio, sentence-CV, formatting density | ~5 ms (sync) | backend / `services/` |
| **B. Pattern matching** | banned phrases, structural patterns, formatting habits | ~10 ms (sync) | `backend/src/aidetect/rubric/v1/` |
| **C. LLM-as-judge** | rubric-based scoring через OpenRouter (по умолчанию `claude-haiku-4-5`) | 1–3 s (async) | OpenRouter API |

Веса агрегатора калибруются на ground-truth датасете (Co.Actor live posts + synthetic AI + public benchmarks).

**Working title — публичное имя пока не выбрано.** Статус: Phase 0 (skeleton), Phase 1 (MVP) в работе.

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
│   ├── scripts/              # idempotent bootstrap (01..04)
│   └── README.md             # Azure deploy guide
├── .github/workflows/
│   └── deploy-dev.yml        # CI/CD — fires on push to development branch
├── docker-compose.yml        # local dev (backend + frontend + redis)
├── Makefile
└── CLAUDE.md                 # ← this file
```

## 3. Local development

| Команда | Что делает |
|---|---|
| `make install` | `uv sync` для backend + `pnpm install` для frontend |
| `make backend` | uvicorn dev server на http://localhost:8010 |
| `make frontend` | Quasar dev server на http://localhost:9000 |
| `make redis-up` | Redis в docker-compose на port 6380 |
| `make test` | `pytest` для backend |
| `make lint` | ruff + mypy для backend, eslint для frontend |
| `docker compose up --build` | весь стек локально (backend + frontend + redis) |

**Default ports:** backend `8010`, frontend `9000`, redis `6380` (in-memory fallback если Redis не запущен).

## 4. Tooling / language

- **Python 3.12** для backend (требование `pyproject.toml`, **переопределяет** правило Python 3.11 из родительского CLAUDE.md).
- **Node 20** для frontend (см. Dockerfile).
- **uv** для Python зависимостей.
- **pnpm** для Node зависимостей (с npm fallback).
- **Black/isort/flake8** заменяем на **ruff** (см. `[tool.ruff]` в `pyproject.toml`).
- **mypy strict** для backend.
- Коммуникация с пользователем — на русском. Код и комментарии — на английском (правило из родительского CLAUDE.md).

## 5. Deployment pipeline

### Где что
- **Ветка для dev-деплоя:** `development`
- **Workflow:** `.github/workflows/deploy-dev.yml`
- **Registry:** GHCR — `ghcr.io/co-actor/aidetect-backend:<sha>`, `ghcr.io/co-actor/aidetect-frontend:<sha>`
- **Auth:** GitHub Actions → `GITHUB_TOKEN` для GHCR push, Azure OIDC federated identity для `az aks get-credentials`
- **Target:** AKS cluster `aks-memory-actor` (eastus2), namespace `dev` (shared с другими сервисами Co.Actor)
- **Helm release name:** `aidetect-dev`
- **Resources:** Deployments `aidetect-dev-backend`, `aidetect-dev-frontend` + Services + Ingress
- **Domains:** `aidetect.co.actor` (frontend) + `apiaidetect.co.actor` (backend API)
- **TLS:** cert-manager + `letsencrypt-prod` ClusterIssuer, secret `aidetect-dev-tls`
- **Secrets:** Azure Key Vault `kv-aidetect-dev` → CSI driver → Opaque secret `aidetect-dev-backend-env`

### Pipeline jobs (последовательно)
1. `detect-changes` — `dorny/paths-filter` определяет какие сервисы изменились (`backend/`, `frontend/`).
2. `build-and-push` (matrix: backend, frontend) — `docker/build-push-action` пушит образы в GHCR с тегами `<sha>` + `dev-latest`.
3. `deploy` — `az aks get-credentials` → `helm upgrade --install aidetect-dev` с подстановкой `image.tag=<sha>`, `image.registry`, `azure.backendUamiClientId`, hosts. `kubectl rollout status` ждёт оба deployment.

Ручной запуск: Actions → Deploy to AKS (development) → Run workflow.

## 6. ⚠️ MANDATORY: проверять деплой и пайплайн через `gh`

**После КАЖДОГО `git push origin development` (или ручного запуска workflow):**

```bash
# 1) Найти ID последнего запуска workflow
gh run list --workflow=deploy-dev.yml --limit 5

# 2) Проследить за конкретным запуском в реальном времени
gh run watch <run-id>

# 3) Посмотреть детали запуска (jobs, статусы)
gh run view <run-id>

# 4) Если упало — логи только провалившихся шагов
gh run view <run-id> --log-failed

# 5) Полные логи всего запуска
gh run view <run-id> --log
```

**Шорткаты:**
```bash
# Последний запуск на текущей ветке
gh run list --branch development --limit 1
gh run view --log-failed  # без id берёт последний

# Перезапустить упавший
gh run rerun <run-id>
gh run rerun <run-id> --failed   # только упавшие jobs

# Ручной запуск (workflow_dispatch)
gh workflow run deploy-dev.yml --ref development -f services=all
```

**Правило:** «push прошёл» ≠ «деплой прошёл». Push успешен — это лишь то, что Git принял коммит. Реальная проверка — `gh run view` показывает все 3 job'а зелёными И `kubectl rollout status` в smoke-check прошёл. Без `gh` подтверждения **деплой не считается завершённым**.

## 7. Azure infrastructure (already bootstrapped or pending)

| Ресурс | Имя | Назначение |
|---|---|---|
| AKS cluster | `aks-memory-actor` | Shared cluster в RG `DefaultResourceGroup-EUS`, eastus2 |
| Namespace | `dev` | Shared с другими Co.Actor dev сервисами |
| Key Vault | `kv-aidetect-dev` | Runtime secrets для backend |
| Azure Cache for Redis | `redis-aidetect-dev` | Basic C0, TLS port 6380, схема `rediss://` |
| UAMI (CI) | `id-aidetect-development-deploy` | OIDC federated с GH Actions, role: AKS Cluster User |
| UAMI (backend) | `id-aidetect-development-backend` | OIDC federated с K8s SA, role: KV Secrets User |
| Ingress controller | `ingress-nginx` (shared) | LB IP `52.254.109.26` |
| ClusterIssuer | `letsencrypt-prod` (shared) | Cert-manager автоматически выписывает TLS |

**Subscription:** `Basic` (`71ddbd6b-dfbd-4293-bfbd-155afd7b518d`), tenant `126403ee-2465-4019-8431-5a17899b6774`.

## 8. Bootstrap scripts (`infra/scripts/`)

Идемпотентные, прогоняются в порядке:

```bash
bash infra/scripts/01-bootstrap-azure.sh         # KV + Redis + 2 UAMI + roles. ~20 мин (Redis долго).
bash infra/scripts/02-setup-cluster-rbac.sh <CI_PRINCIPAL>
bash infra/scripts/03-import-secrets.sh "<REDIS_URL>"
bash infra/scripts/04-setup-github-vars.sh <AZURE_CLIENT_ID> <BACKEND_UAMI_CLIENT_ID>
```

После прогона остаётся вручную:
- DNS A-записи: `aidetect.co.actor` + `apiaidetect.co.actor` → `52.254.109.26`
- Сделать GHCR пакеты public (Settings → Packages) или передать `GHCR_PULL_SECRET_NAME`

## 9. Secrets and config

### Backend env (config.py)
| Variable | Где живёт в проде | Обязательно |
|---|---|---|
| `AIDETECT_INTERNAL_TOKEN` | KV → CSI mount → envFrom | да (≥8 chars, валидируется Pydantic) |
| `OPENROUTER_API_KEY` | KV → CSI mount → envFrom | да (без него Layer C падает) |
| `REDIS_URL` | KV (Azure Cache for Redis TLS URL) | опционально (in-memory fallback) |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | KV (добавляется когда Langfuse развёрнут) | опционально (`LANGFUSE_ENABLED=0` по умолчанию) |
| `COACTOR_DATABASE_URL` | не используется в runtime API | только для offline ground-truth скриптов |

### Helm chart inputs (override via `--set` в workflow)
- `image.registry`, `image.tag` — registry/SHA
- `image.pullSecretName` — пусто если пакеты public, иначе имя docker-registry secret
- `azure.backendUamiClientId` — UAMI clientId для backend SA workload identity
- `ingress.hosts.api`, `ingress.hosts.app` — хосты

## 10. Operational rules (project-specific)

- **Минимальный диff** — правило из родительского CLAUDE.md. Никаких лишних рефакторингов в bugfix-PR.
- **Никаких bullet-point коммитов**, никаких "Generated with Claude" / Co-Authored-By подписей. Одна короткая строка.
- **Перед PR на main:** локально `cd backend && uv run pytest && uv run ruff check . && uv run mypy src` + `cd frontend && pnpm build && pnpm lint`.
- **Каждое изменение бэкенда требует теста.** Если фикс — обязательно регрессионный тест.
- **DB migrations** (если появятся) — нумерованные файлы `backend/migrations/NNN_*.up.sql` + `*.down.sql`. Никаких ad-hoc SQL.
- **Optional integrations** (Langfuse сейчас, Stripe/OAuth/Sentry в будущем) MUST be no-op когда env vars пустые.
- **Никогда не мерджи в `main` с красными тестами.** Никогда не отключай тест чтобы "пройти CI".

## 11. Sessions log

Решения по этой сессии (организация деплоя): `.claude/sessions/2026-05-25_aks-helm-deploy-setup.md` (если включена практика session log из родительского CLAUDE.md). Этот файл фиксирует только повторяемые факты о проекте — текущее состояние работы хранится в git.
