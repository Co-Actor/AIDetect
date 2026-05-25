# Azure AKS deploy — `development` environment

Деплой AIDetect (backend + frontend) в существующий кластер `aks-memory-actor` в shared namespace `dev`. Образы хранятся в **GHCR** (`ghcr.io/co-actor/aidetect-*`), секреты приложения — в Azure Key Vault через CSI driver, runtime-доступ к KV у backend через Workload Identity.

## Архитектура

```
GitHub Co-Actor/AIDetect (development branch)
        │
        │  push → GitHub Actions
        │   ├─ docker login ghcr.io (GITHUB_TOKEN)  → push aidetect-backend / aidetect-frontend
        │   └─ azure/login@v2 OIDC                  → az aks get-credentials → helm upgrade
        ▼
Azure subscription "Basic" (71ddbd6b-dfbd-4293-bfbd-155afd7b518d)
├── Key Vault kv-aidetect-dev                 ← runtime secrets for backend
├── Identity id-aidetect-development-deploy   ← CI: AKS Cluster User
├── Identity id-aidetect-development-backend  ← runtime: KV Secrets User
└── AKS aks-memory-actor (eastus2, RG DefaultResourceGroup-EUS)
    └── namespace dev (shared)
        ├── ServiceAccount aidetect-dev-backend  (federated → KV via WI)
        ├── ServiceAccount aidetect-dev-frontend (no KV access)
        ├── Deployment + Service: aidetect-dev-backend, aidetect-dev-frontend
        ├── SecretProviderClass: aidetect-dev-backend (CSI → KV → Opaque secret)
        ├── (optional) Secret ghcr-pull-secret  — only if GHCR package is private
        └── Ingress: apiaidetect.co.actor, aidetect.co.actor

External (existing on cluster, untouched):
├── ingress-nginx (LB IP 52.254.109.26)
└── cert-manager (ClusterIssuer letsencrypt-prod)
```

Шаги ниже — **разовый bootstrap**. После настройки push в `development` сам деплоит через GitHub Actions.

## ⚡ Быстрый путь — через скрипты

В `infra/scripts/` лежат идемпотентные скрипты, которые автоматизируют шаги §1–§4 этого README:

```bash
# 1. Создаёт KV + Redis + 2 UAMI + federated creds + role assignments.
#    Печатает значения для следующих шагов.
bash infra/scripts/01-bootstrap-azure.sh

# 2. Применяет in-cluster Role + RoleBinding для CI principal
#    (id берётся из вывода предыдущего шага).
bash infra/scripts/02-setup-cluster-rbac.sh <CI_PRINCIPAL_ID>

# 3. Заливает 3 секрета в KV (REDIS_URL, OPENROUTER_API_KEY, AIDETECT_INTERNAL_TOKEN).
#    Принимает REDIS_URL первым аргументом или спросит интерактивно.
bash infra/scripts/03-import-secrets.sh "<REDIS_URL>"

# 4. Создаёт GitHub environment 'development' и 12 переменных через gh CLI.
bash infra/scripts/04-setup-github-vars.sh <AZURE_CLIENT_ID> <BACKEND_UAMI_CLIENT_ID>
```

После прогона остаётся только:
- настроить DNS (см. §7)
- сделать GHCR пакеты public после первого build (см. §5)
- push в `development` запустит первый деплой

Langfuse-сервер разворачивается отдельно — когда будут готовы ключи, см. инструкцию в выводе `03-import-secrets.sh`.

Дальше — раскрытие что делает каждый скрипт под капотом, если нужно ручное управление.


## Уже есть на кластере

- ✅ AKS `aks-memory-actor` с OIDC issuer + Workload Identity
- ✅ Addon `azure-keyvault-secrets-provider` (CSI driver)
- ✅ `ingress-nginx-controller` (LB `52.254.109.26`)
- ✅ `cert-manager` ClusterIssuer `letsencrypt-prod`
- ✅ Namespace `dev`

## Что нужно сделать один раз

### 1. Создать Key Vault + Azure Cache for Redis

```bash
SUB="71ddbd6b-dfbd-4293-bfbd-155afd7b518d"
RG="DefaultResourceGroup-EUS"
LOC="eastus2"
KV="kv-aidetect-dev"
REDIS="redis-aidetect-dev"

az account set --subscription "$SUB"

# Key Vault (RBAC mode)
az keyvault show -n "$KV" >/dev/null 2>&1 || \
  az keyvault create -n "$KV" -g "$RG" -l "$LOC" --enable-rbac-authorization true -o none

# Azure Cache for Redis — Basic C0 (250 MB, ~$16/mo). Создание занимает ~15–20 минут.
az redis show -n "$REDIS" -g "$RG" >/dev/null 2>&1 || \
  az redis create -n "$REDIS" -g "$RG" -l "$LOC" --sku Basic --vm-size c0 -o none

# Получить hostname и primary key
REDIS_HOST=$(az redis show -n "$REDIS" -g "$RG" --query hostName -o tsv)
REDIS_KEY=$(az redis list-keys -n "$REDIS" -g "$RG" --query primaryKey -o tsv)
REDIS_URL="rediss://:${REDIS_KEY}@${REDIS_HOST}:6380/0"
echo "REDIS_URL = $REDIS_URL"
```

Важно: Azure Cache for Redis по умолчанию слушает TLS-порт `6380` со схемой `rediss://`. Plain `6379` отключён — backend подключится по TLS автоматически (redis-py поддерживает `rediss://`).

### 2. Создать identities + federated credentials

```bash
SUB="71ddbd6b-dfbd-4293-bfbd-155afd7b518d"
TENANT="126403ee-2465-4019-8431-5a17899b6774"
RG="DefaultResourceGroup-EUS"
LOC="eastus2"
AKS="aks-memory-actor"
KV="kv-aidetect-dev"
NS="dev"
GH_REPO="Co-Actor/AIDetect"
GH_ENV="development"
RELEASE="aidetect-dev"

az account set --subscription "$SUB"

KV_ID=$(az keyvault show -n "$KV" --query id -o tsv)
AKS_ID=$(az aks show -n "$AKS" -g "$RG" --query id -o tsv)
AKS_OIDC=$(az aks show -n "$AKS" -g "$RG" --query oidcIssuerProfile.issuerUrl -o tsv)

# CI identity (GitHub Actions OIDC → AKS only; GHCR push uses GITHUB_TOKEN)
CI_UAMI="id-aidetect-${GH_ENV}-deploy"
az identity show -n "$CI_UAMI" -g "$RG" >/dev/null 2>&1 || \
  az identity create -n "$CI_UAMI" -g "$RG" -l "$LOC" -o none
CI_CLIENT=$(az identity show -n "$CI_UAMI" -g "$RG" --query clientId -o tsv)
CI_PRINCIPAL=$(az identity show -n "$CI_UAMI" -g "$RG" --query principalId -o tsv)

az identity federated-credential show -n "gh-${GH_ENV}" --identity-name "$CI_UAMI" -g "$RG" >/dev/null 2>&1 || \
az identity federated-credential create -n "gh-${GH_ENV}" --identity-name "$CI_UAMI" -g "$RG" \
  --issuer "https://token.actions.githubusercontent.com" \
  --subject "repo:${GH_REPO}:environment:${GH_ENV}" \
  --audiences "api://AzureADTokenExchange" -o none

# Cluster User role is enough for `az aks get-credentials` + kubeconfig use.
# For helm-driven changes we additionally need RBAC inside the cluster (separate step below).
az role assignment create --assignee "$CI_PRINCIPAL" --role "Azure Kubernetes Service Cluster User Role" --scope "$AKS_ID" -o none 2>/dev/null || true

# Runtime identity for backend SA (KV access via Workload Identity)
SA_NAME="${RELEASE}-backend"
SVC_UAMI="id-aidetect-${GH_ENV}-backend"
az identity show -n "$SVC_UAMI" -g "$RG" >/dev/null 2>&1 || \
  az identity create -n "$SVC_UAMI" -g "$RG" -l "$LOC" -o none
SVC_CLIENT=$(az identity show -n "$SVC_UAMI" -g "$RG" --query clientId -o tsv)
SVC_PRINCIPAL=$(az identity show -n "$SVC_UAMI" -g "$RG" --query principalId -o tsv)

az identity federated-credential show -n "k8s-backend" --identity-name "$SVC_UAMI" -g "$RG" >/dev/null 2>&1 || \
az identity federated-credential create -n "k8s-backend" --identity-name "$SVC_UAMI" -g "$RG" \
  --issuer "$AKS_OIDC" \
  --subject "system:serviceaccount:${NS}:${SA_NAME}" \
  --audiences "api://AzureADTokenExchange" -o none

az role assignment create --assignee "$SVC_PRINCIPAL" --role "Key Vault Secrets User" --scope "$KV_ID" -o none 2>/dev/null || true

# Grant yourself Key Vault Administrator to write secrets
ME=$(az ad signed-in-user show --query id -o tsv)
az role assignment create --assignee "$ME" --role "Key Vault Administrator" --scope "$KV_ID" -o none 2>/dev/null || true

cat <<EOF

==> GitHub repo variables (Settings → Environments → development):
  AZURE_CLIENT_ID = $CI_CLIENT
  BACKEND_UAMI_CLIENT_ID = $SVC_CLIENT

EOF
```

### 3. Дать CI in-cluster права для Helm

Cluster User role даёт только право получить kubeconfig. Чтобы Helm мог создавать/обновлять ресурсы — нужны in-cluster RBAC. Самый чистый способ — namespace-scoped role:

```bash
# Достань principalId CI identity (если потерян)
CI_PRINCIPAL=$(az identity show -n id-aidetect-development-deploy -g DefaultResourceGroup-EUS --query principalId -o tsv)

kubectl apply -n dev -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: aidetect-dev-deployer
  namespace: dev
rules:
  - apiGroups: [""]
    resources: ["services", "serviceaccounts", "configmaps", "secrets", "pods"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["secrets-store.csi.x-k8s.io"]
    resources: ["secretproviderclasses"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: aidetect-dev-deployer
  namespace: dev
subjects:
  - kind: User
    name: ${CI_PRINCIPAL}      # principalId of id-aidetect-development-deploy
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: aidetect-dev-deployer
  apiGroup: rbac.authorization.k8s.io
EOF
```

(Если предпочтительно — назначь `Azure Kubernetes Service RBAC Cluster Admin` на `$AKS_ID` для CI principal и пропусти этот шаг. Дороже по правам, проще по сетапу.)

### 4. Добавить GitHub variables

Repo `Co-Actor/AIDetect` → Settings → Environments → New environment `development` → Variables (не secrets — это не чувствительные данные):

| Variable | Value |
|---|---|
| `AZURE_CLIENT_ID` | CI UAMI clientId (вывод скрипта) |
| `AZURE_TENANT_ID` | `126403ee-2465-4019-8431-5a17899b6774` |
| `AZURE_SUBSCRIPTION_ID` | `71ddbd6b-dfbd-4293-bfbd-155afd7b518d` |
| `AKS_NAME` | `aks-memory-actor` |
| `AKS_RESOURCE_GROUP` | `DefaultResourceGroup-EUS` |
| `K8S_NAMESPACE` | `dev` |
| `HELM_RELEASE` | `aidetect-dev` |
| `IMAGE_NAMESPACE` | `co-actor` (lowercase GitHub org/owner) |
| `BACKEND_UAMI_CLIENT_ID` | backend runtime UAMI clientId |
| `GHCR_PULL_SECRET_NAME` | `""` если пакеты публичные, иначе имя docker-registry секрета (см. §5) |
| `API_HOST` | `apiaidetect.co.actor` |
| `APP_HOST` | `aidetect.co.actor` |

### 5. (Опционально) GHCR pull secret если пакеты приватные

После первого push образа `ghcr.io/co-actor/aidetect-backend` он по умолчанию приватный. Два пути:

**Вариант А — сделать пакет публичным (проще)**
GitHub → Packages → aidetect-backend → Settings → Change visibility → Public. То же для `aidetect-frontend`. Тогда AKS не нужен imagePullSecret, переменную `GHCR_PULL_SECRET_NAME` оставь пустой.

**Вариант Б — приватные пакеты + imagePullSecret**
Создай Personal Access Token (classic) с scope `read:packages`, потом:
```bash
kubectl create secret docker-registry ghcr-pull-secret \
  --namespace dev \
  --docker-server=ghcr.io \
  --docker-username=<your-github-username> \
  --docker-password=<PAT-with-read:packages> \
  --docker-email=<your-email>
```
Установи `GHCR_PULL_SECRET_NAME=ghcr-pull-secret` в GitHub vars.

### 6. Импортировать секреты в Key Vault

Backend ожидает 3 обязательных ключа (см. `infra/helm/aidetect/values.yaml` → `backend.secretEnvKeys`):

| Helm key | KV secret name | Описание |
|---|---|---|
| `OPENROUTER_API_KEY` | `aidetect-dev-backend-OPENROUTER-API-KEY` | OpenRouter API key для LLM-as-judge |
| `AIDETECT_INTERNAL_TOKEN` | `aidetect-dev-backend-AIDETECT-INTERNAL-TOKEN` | Internal API token (≥8 chars; скрипт сгенерирует, если оставить пустым) |
| `REDIS_URL` | `aidetect-dev-backend-REDIS-URL` | TLS URL Azure Cache for Redis: `rediss://:<key>@<host>:6380/0` |

Имя секрета в KV = `aidetect-dev-backend-<KEY-WITH-HYPHENS>`. Запись:

```bash
KV="kv-aidetect-dev"
az keyvault secret set --vault-name "$KV" -n aidetect-dev-backend-OPENROUTER-API-KEY --value '<openrouter-api-key>'
az keyvault secret set --vault-name "$KV" -n aidetect-dev-backend-AIDETECT-INTERNAL-TOKEN --value '<internal-token>'
az keyvault secret set --vault-name "$KV" -n aidetect-dev-backend-REDIS-URL --value "$REDIS_URL"   # из шага §1
```

Langfuse keys добавляются позже, когда Langfuse-сервер развёрнут отдельно:
1. `az keyvault secret set` для `LANGFUSE_PUBLIC_KEY` и `LANGFUSE_SECRET_KEY`
2. Добавить эти keys в `backend.secretEnvKeys` в `values.yaml`
3. Поменять `LANGFUSE_ENABLED` в `backend.env` на `"1"`

Проверка:
```bash
az keyvault secret list --vault-name kv-aidetect-dev --query "[].name" -o tsv
```

Если набор ключей меняется — обнови `backend.secretEnvKeys` в `infra/helm/aidetect/values.yaml` и положи новые секреты в KV (имя по схеме выше).

### 7. DNS — направить хосты на ingress IP

LB IP кластера: **`52.254.109.26`** (shared ingress-nginx).

В DNS-провайдере для `co.actor`:

```
apiaidetect.co.actor   A   52.254.109.26
aidetect.co.actor       A   52.254.109.26
```

После того как DNS разрешится, cert-manager автоматически выпустит Let's Encrypt сертификаты.

### 8. Первый деплой

После всех шагов выше — пуш в `development` запустит workflow:

```bash
git push origin development
```

Workflow:
1. `detect-changes` определяет какие сервисы изменились
2. `build-and-push` — параллельно собирает + пушит `aidetect-backend` и `aidetect-frontend` в `ghcr.io/co-actor` (tag = `sha` + `dev-latest`)
3. `deploy` — Azure OIDC login → `az aks get-credentials` → `helm upgrade --install aidetect-dev ./infra/helm/aidetect -n dev -f values-dev.yaml --set image.tag=$SHA --set image.registry=ghcr.io/co-actor ...`
4. `kubectl rollout status` ждёт что оба deployment стали Ready

Ручной запуск со всеми сервисами: Actions → Deploy to AKS (development) → Run workflow → services: `all`.

## Per-deploy flow (после bootstrap)

```
git checkout development
# работа
git commit -am "…"
git push origin development
```

→ GitHub Actions поднимает образы в GHCR и катит Helm в AKS.

## Troubleshooting

**Pod `ImagePullBackOff` от GHCR**
Пакет приватный — нужен либо imagePullSecret (§5 вариант Б), либо сделать пакет public (§5 вариант А).

```bash
kubectl describe pod -n dev -l app.kubernetes.io/instance=aidetect-dev
```

**Pod `ContainerCreating` с ошибкой secrets**
CSI driver не достучался до KV. Проверь:
- ServiceAccount `aidetect-dev-backend` имеет аннотацию `azure.workload.identity/client-id` с правильным UAMI clientId
- У UAMI есть роль `Key Vault Secrets User` на скоупе KV
- Federated credential subject = `system:serviceaccount:dev:aidetect-dev-backend`

```bash
kubectl describe pod -n dev -l app.kubernetes.io/instance=aidetect-dev
kubectl logs -n kube-system -l app=secrets-store-csi-driver -c secrets-store --tail=50
```

**TLS cert не выпускается**
- `dig apiaidetect.co.actor` — резолвится в 52.254.109.26?
- `kubectl get certificate -n dev`
- `kubectl describe certificate aidetect-dev-tls -n dev`

**Ingress 502/503**
Readiness probe падает. Проверь:
```bash
kubectl get pods -n dev -l app.kubernetes.io/instance=aidetect-dev
kubectl logs -n dev deploy/aidetect-dev-backend --tail=100
kubectl exec -n dev deploy/aidetect-dev-backend -- curl -sf localhost:8010/v1/healthz
```

**Helm upgrade падает с `forbidden`**
RBAC в кластере не достаточно — выполни §3 (Role + RoleBinding) или назначь `Azure Kubernetes Service RBAC Cluster Admin` на CI principal.

**Build frontend падает в CI**
Dockerfile ожидает `VITE_API_BASE_URL`. Передаётся через `API_HOST` GitHub variable в `build_args`. Проверь что `API_HOST` задан в environment `development`.

## Локальная отладка Helm

```bash
# Lint
helm lint infra/helm/aidetect

# Рендер с dev-overrides без применения
helm template aidetect-dev infra/helm/aidetect \
  -n dev \
  -f infra/helm/aidetect/values-dev.yaml \
  --set image.tag=local \
  --set azure.backendUamiClientId=00000000-0000-0000-0000-000000000000

# Dry-run применения
helm upgrade --install aidetect-dev infra/helm/aidetect \
  -n dev \
  -f infra/helm/aidetect/values-dev.yaml \
  --set image.tag=$(git rev-parse HEAD) \
  --set azure.backendUamiClientId=<UAMI_CLIENT_ID> \
  --dry-run --debug
```

## Tearing down

```bash
helm uninstall aidetect-dev -n dev
kubectl delete role aidetect-dev-deployer -n dev
kubectl delete rolebinding aidetect-dev-deployer -n dev
# (если делал) kubectl delete secret ghcr-pull-secret -n dev

az identity delete -n id-aidetect-development-deploy -g DefaultResourceGroup-EUS
az identity delete -n id-aidetect-development-backend -g DefaultResourceGroup-EUS
az keyvault delete -n kv-aidetect-dev -g DefaultResourceGroup-EUS
az keyvault purge -n kv-aidetect-dev
```

## Cost (estimated, dev)

| Resource | $/month |
|---|---|
| GHCR storage (private packages) | $0 (free tier для org) |
| Key Vault (low ops) | <$1 |
| Azure Cache for Redis Basic C0 (250 MB) | ~$16 |
| Compute (shared nodepool) | $0 marginal |
| Egress | <$5 |
| **Total** | **~$22/mo** |

(AKS control plane уже оплачен; Langfuse cloud — free tier 50K events/мес; ACR не используем.)

## Tear down Redis отдельно

```bash
az redis delete -n redis-aidetect-dev -g DefaultResourceGroup-EUS -y
```
