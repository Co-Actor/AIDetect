# Azure AKS deploy — `development` environment

Деплой AIDetect (backend + frontend) в существующий кластер `aks-memory-actor` в shared namespace `dev`. Архитектура повторяет паттерн publora.com: GitHub OIDC → ACR → Helm на AKS, секреты через Key Vault + CSI driver, Workload Identity для backend.

## Архитектура

```
GitHub Co-Actor/AIDetect (development branch)
        │
        │  push → GitHub Actions OIDC
        ▼
Azure subscription "Basic" (71ddbd6b-dfbd-4293-bfbd-155afd7b518d)
├── ACR aidetectacrdev.azurecr.io            ← images (backend, frontend)
├── Key Vault kv-aidetect-dev                 ← runtime secrets for backend
├── Identity id-aidetect-development-deploy   ← CI: AcrPush + AKS Cluster Admin
├── Identity id-aidetect-development-backend  ← runtime: KV Secrets User
└── AKS aks-memory-actor (eastus2, RG DefaultResourceGroup-EUS)
    └── namespace dev (shared with other dev services)
        ├── ServiceAccount aidetect-dev-backend  (federated → KV via WI)
        ├── ServiceAccount aidetect-dev-frontend (no KV access)
        ├── Deployment + Service: aidetect-dev-backend, aidetect-dev-frontend
        ├── SecretProviderClass: aidetect-dev-backend (CSI → KV → Opaque secret)
        └── Ingress: api.aidetect.co.actor, aidetect.co.actor

External (existing on cluster, untouched):
├── ingress-nginx (LB IP 52.254.109.26)
└── cert-manager (ClusterIssuer letsencrypt-prod)
```

Шаги ниже — **разовый** Azure bootstrap. После прогона push в `development` уже сам всё деплоит через GitHub Actions.

## Уже есть на кластере

- ✅ AKS `aks-memory-actor` с OIDC issuer + Workload Identity (см. publora-dev)
- ✅ Addon `azure-keyvault-secrets-provider` (CSI driver) на всех нодах
- ✅ `ingress-nginx-controller` (LB `52.254.109.26`)
- ✅ `cert-manager` ClusterIssuer `letsencrypt-prod`
- ✅ Namespace `dev` (используем общий)

## Что нужно сделать один раз

### 1. Создать ACR и Key Vault

```bash
SUB="71ddbd6b-dfbd-4293-bfbd-155afd7b518d"
RG="DefaultResourceGroup-EUS"
LOC="eastus2"
AKS="aks-memory-actor"
ACR="aidetectacrdev"
KV="kv-aidetect-dev"
NS="dev"

az account set --subscription "$SUB"

# ACR (Basic SKU; admin disabled — auth через AAD)
az acr show -n "$ACR" >/dev/null 2>&1 || \
  az acr create -n "$ACR" -g "$RG" -l "$LOC" --sku Basic --admin-enabled false -o none

# Attach ACR to AKS (kubelet identity pull)
az aks update -n "$AKS" -g "$RG" --attach-acr "$ACR" -o none

# Key Vault (RBAC mode)
az keyvault show -n "$KV" >/dev/null 2>&1 || \
  az keyvault create -n "$KV" -g "$RG" -l "$LOC" --enable-rbac-authorization true -o none
```

### 2. Создать identities + federated credentials

```bash
SUB="71ddbd6b-dfbd-4293-bfbd-155afd7b518d"
TENANT="126403ee-2465-4019-8431-5a17899b6774"
RG="DefaultResourceGroup-EUS"
LOC="eastus2"
AKS="aks-memory-actor"
ACR="aidetectacrdev"
KV="kv-aidetect-dev"
NS="dev"
GH_REPO="Co-Actor/AIDetect"
GH_ENV="development"
RELEASE="aidetect-dev"

az account set --subscription "$SUB"

ACR_ID=$(az acr show -n "$ACR" --query id -o tsv)
KV_ID=$(az keyvault show -n "$KV" --query id -o tsv)
AKS_ID=$(az aks show -n "$AKS" -g "$RG" --query id -o tsv)
AKS_OIDC=$(az aks show -n "$AKS" -g "$RG" --query oidcIssuerProfile.issuerUrl -o tsv)

# CI identity (GitHub Actions OIDC)
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

az role assignment create --assignee "$CI_PRINCIPAL" --role "AcrPush" --scope "$ACR_ID" -o none 2>/dev/null || true
az role assignment create --assignee "$CI_PRINCIPAL" --role "Azure Kubernetes Service Cluster Admin Role" --scope "$AKS_ID" -o none 2>/dev/null || true

# Runtime identity for backend SA (KV access via WI)
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

### 3. Добавить GitHub variables

Repo `Co-Actor/AIDetect` → Settings → Environments → New environment `development` → Variables (NOT secrets — не чувствительные):

| Variable | Value |
|---|---|
| `AZURE_CLIENT_ID` | CI UAMI clientId (вывод скрипта) |
| `AZURE_TENANT_ID` | `126403ee-2465-4019-8431-5a17899b6774` |
| `AZURE_SUBSCRIPTION_ID` | `71ddbd6b-dfbd-4293-bfbd-155afd7b518d` |
| `ACR_LOGIN_SERVER` | `aidetectacrdev.azurecr.io` |
| `AKS_NAME` | `aks-memory-actor` |
| `AKS_RESOURCE_GROUP` | `DefaultResourceGroup-EUS` |
| `K8S_NAMESPACE` | `dev` |
| `HELM_RELEASE` | `aidetect-dev` |
| `BACKEND_UAMI_CLIENT_ID` | backend runtime UAMI clientId (вывод скрипта) |
| `API_HOST` | `api.aidetect.co.actor` |
| `APP_HOST` | `aidetect.co.actor` |

### 4. Импортировать секреты в Key Vault

Backend ожидает 4 ключа (см. `infra/helm/aidetect/values.yaml` → `backend.secretEnvKeys`):

| Helm key | KV secret name | Описание |
|---|---|---|
| `OPENROUTER_API_KEY` | `aidetect-dev-backend-OPENROUTER-API-KEY` | OpenRouter API key для LLM-as-judge |
| `AIDETECT_INTERNAL_TOKEN` | `aidetect-dev-backend-AIDETECT-INTERNAL-TOKEN` | Internal API token |
| `REDIS_URL` | `aidetect-dev-backend-REDIS-URL` | `redis://host:6379/0` (managed Redis) |
| `OPENAI_API_KEY` | `aidetect-dev-backend-OPENAI-API-KEY` | OpenAI API key (опционально) |

Имя секрета в KV = `aidetect-dev-backend-<KEY-WITH-HYPHENS>`. Запись:

```bash
KV="kv-aidetect-dev"
az keyvault secret set --vault-name "$KV" -n aidetect-dev-backend-OPENROUTER-API-KEY --value 'sk-or-...'
az keyvault secret set --vault-name "$KV" -n aidetect-dev-backend-AIDETECT-INTERNAL-TOKEN --value '...'
az keyvault secret set --vault-name "$KV" -n aidetect-dev-backend-REDIS-URL --value 'redis://...'
az keyvault secret set --vault-name "$KV" -n aidetect-dev-backend-OPENAI-API-KEY --value 'sk-...'
```

Проверка:
```bash
az keyvault secret list --vault-name kv-aidetect-dev --query "[].name" -o tsv
```

Если состав ключей меняется — обновить список в `infra/helm/aidetect/values.yaml` → `backend.secretEnvKeys` и положить соответствующие секреты в KV (имя по схеме выше).

### 5. DNS — направить хосты на ingress IP

LB IP кластера: **`52.254.109.26`** (shared ingress-nginx).

В DNS-провайдере для `co.actor`:

```
api.aidetect.co.actor   A   52.254.109.26
aidetect.co.actor       A   52.254.109.26
```

После того как DNS разрешится, cert-manager автоматически выпустит Let's Encrypt сертификаты.

### 6. Первый деплой

После всех шагов выше — пуш в `development` запустит workflow:

```bash
git push origin development
```

Workflow:
1. `detect-changes` определяет какие сервисы изменились
2. `build-and-push` — параллельно собирает + пушит backend и frontend в ACR (tag = `sha` + `dev-latest`)
3. `deploy` — `helm upgrade --install aidetect-dev ./infra/helm/aidetect -n dev -f values-dev.yaml --set image.tag=$SHA ...`
4. `kubectl rollout status` ждёт что оба deployment стали Ready

Ручной запуск со всеми сервисами: Actions → Deploy to AKS (development) → Run workflow → services: `all`.

## Per-deploy flow (после bootstrap)

```
git checkout development
# работа
git commit -am "…"
git push origin development
```

→ GitHub Actions поднимает образы и катит Helm

## Troubleshooting

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
- `dig api.aidetect.co.actor` — резолвится в 52.254.109.26?
- `kubectl get certificate -n dev`
- `kubectl describe certificate aidetect-dev-tls -n dev`

**Ingress 502/503**
Readiness probe падает. Проверь:
```bash
kubectl get pods -n dev -l app.kubernetes.io/instance=aidetect-dev
kubectl logs -n dev deploy/aidetect-dev-backend --tail=100
kubectl exec -n dev deploy/aidetect-dev-backend -- curl -sf localhost:8010/v1/healthz
```

**Build frontend падает в CI**
Dockerfile ожидает `VITE_API_BASE_URL`. Передаётся через `API_HOST` GitHub variable в `build_args`. Проверь что `API_HOST` задан в environment `development`.

## Локальная отладка Helm

```bash
# Лит
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

az identity delete -n id-aidetect-development-deploy -g DefaultResourceGroup-EUS
az identity delete -n id-aidetect-development-backend -g DefaultResourceGroup-EUS
az keyvault delete -n kv-aidetect-dev -g DefaultResourceGroup-EUS
az keyvault purge -n kv-aidetect-dev
az acr delete -n aidetectacrdev -y
```

## Cost (estimated, dev)

| Resource | $/month |
|---|---|
| ACR Basic | $5 |
| Key Vault (low ops) | <$1 |
| Compute (на shared nodepool, без выделенного пула) | $0 marginal |
| Egress | <$5 |
| **Total** | **~$10/mo** |

(AKS control plane уже оплачен в составе кластера publora; Redis — внешний, не часть этого стека.)
