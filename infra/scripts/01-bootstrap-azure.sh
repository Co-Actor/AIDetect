#!/usr/bin/env bash
#
# Bootstrap Azure resources for AIDetect dev:
#   - Key Vault                (kv-aidetect-dev)
#   - Azure Cache for Redis    (redis-aidetect-dev, Basic C0)
#   - CI UAMI                  (id-aidetect-development-deploy) + federated cred for GitHub Actions OIDC
#   - Backend runtime UAMI     (id-aidetect-development-backend) + federated cred for K8s SA + KV Secrets User role
#   - Grants caller "Key Vault Administrator" so they can write secrets
#
# Idempotent — re-running is safe.
#
# Prints values that need to be added as GitHub environment variables.
#
# Usage:  bash infra/scripts/01-bootstrap-azure.sh

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────
SUB="${SUB:-71ddbd6b-dfbd-4293-bfbd-155afd7b518d}"
TENANT="${TENANT:-126403ee-2465-4019-8431-5a17899b6774}"
RG="${RG:-DefaultResourceGroup-EUS}"
LOC="${LOC:-eastus2}"
AKS="${AKS:-aks-memory-actor}"
KV="${KV:-kv-aidetect-dev}"
REDIS="${REDIS:-redis-aidetect-dev}"
NS="${NS:-dev}"
GH_REPO="${GH_REPO:-Co-Actor/AIDetect}"
GH_ENV="${GH_ENV:-development}"
RELEASE="${RELEASE:-aidetect-dev}"
# ──────────────────────────────────────────────────────────────────────────

echo "==> Setting subscription: $SUB"
az account set --subscription "$SUB"

# ─── 1. Key Vault ─────────────────────────────────────────────────────────
echo "==> Creating Key Vault $KV (idempotent)..."
az keyvault show -n "$KV" >/dev/null 2>&1 || \
  az keyvault create -n "$KV" -g "$RG" -l "$LOC" --enable-rbac-authorization true -o none

# Grant caller Key Vault Administrator so secrets can be written
ME=$(az ad signed-in-user show --query id -o tsv)
KV_ID=$(az keyvault show -n "$KV" --query id -o tsv)
az role assignment create --assignee "$ME" --role "Key Vault Administrator" --scope "$KV_ID" -o none 2>/dev/null || true

# ─── 2. Azure Cache for Redis ─────────────────────────────────────────────
echo "==> Creating Azure Cache for Redis $REDIS (Basic C0)... (may take 15-20 min on first run)"
if ! az redis show -n "$REDIS" -g "$RG" >/dev/null 2>&1; then
  az redis create -n "$REDIS" -g "$RG" -l "$LOC" --sku Basic --vm-size c0 -o none
fi

REDIS_STATE=$(az redis show -n "$REDIS" -g "$RG" --query provisioningState -o tsv)
if [ "$REDIS_STATE" != "Succeeded" ]; then
  echo "    Redis provisioning state: $REDIS_STATE. Waiting until Succeeded..."
  until [ "$(az redis show -n "$REDIS" -g "$RG" --query provisioningState -o tsv)" = "Succeeded" ]; do
    sleep 30
    echo -n "."
  done
  echo
fi

REDIS_HOST=$(az redis show -n "$REDIS" -g "$RG" --query hostName -o tsv)
REDIS_KEY=$(az redis list-keys -n "$REDIS" -g "$RG" --query primaryKey -o tsv)
REDIS_URL="rediss://:${REDIS_KEY}@${REDIS_HOST}:6380/0"

# ─── 3. AKS info (OIDC issuer + resource id) ──────────────────────────────
AKS_ID=$(az aks show -n "$AKS" -g "$RG" --query id -o tsv)
AKS_OIDC=$(az aks show -n "$AKS" -g "$RG" --query oidcIssuerProfile.issuerUrl -o tsv)

# ─── 4. CI identity (GitHub Actions OIDC → AKS Cluster User) ──────────────
echo "==> Creating CI identity id-aidetect-${GH_ENV}-deploy..."
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

az role assignment create --assignee "$CI_PRINCIPAL" --role "Azure Kubernetes Service Cluster User Role" --scope "$AKS_ID" -o none 2>/dev/null || true

# ─── 5. Backend runtime identity (K8s SA → KV Secrets User) ───────────────
echo "==> Creating backend runtime identity id-aidetect-${GH_ENV}-backend..."
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

# ─── Output ───────────────────────────────────────────────────────────────
cat <<EOF

✅ Bootstrap complete.

──── GitHub environment 'development' variables ────
AZURE_CLIENT_ID         = $CI_CLIENT
AZURE_TENANT_ID         = $TENANT
AZURE_SUBSCRIPTION_ID   = $SUB
AKS_NAME                = $AKS
AKS_RESOURCE_GROUP      = $RG
K8S_NAMESPACE           = $NS
HELM_RELEASE            = $RELEASE
IMAGE_NAMESPACE         = co-actor
BACKEND_UAMI_CLIENT_ID  = $SVC_CLIENT
GHCR_PULL_SECRET_NAME   = ""
API_HOST                = api.aidetect.co.actor
APP_HOST                = aidetect.co.actor

──── CI principal id (used by 02-setup-cluster-rbac.sh) ────
CI_PRINCIPAL_ID         = $CI_PRINCIPAL

──── Redis URL (used by 03-import-secrets.sh) ────
REDIS_URL               = $REDIS_URL

──── Next steps ────
  1) Run:  bash infra/scripts/02-setup-cluster-rbac.sh "$CI_PRINCIPAL"
  2) Run:  bash infra/scripts/03-import-secrets.sh "$REDIS_URL"
  3) Run:  bash infra/scripts/04-setup-github-vars.sh "$CI_CLIENT" "$SVC_CLIENT"
  4) Add DNS A records:
       aidetect.co.actor      A   52.254.109.26
       api.aidetect.co.actor  A   52.254.109.26
  5) Push code on 'development' branch — workflow deploys automatically.
EOF
