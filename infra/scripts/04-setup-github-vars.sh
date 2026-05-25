#!/usr/bin/env bash
#
# Create GitHub environment `development` on Co-Actor/AIDetect and set all
# variables the deploy-dev.yml workflow needs.
#
# Requires:  gh CLI authenticated (with admin:repo scope) against the repo.
#
# Usage:  bash infra/scripts/04-setup-github-vars.sh <azure-client-id> <backend-uami-client-id>
#         (both values are printed by 01-bootstrap-azure.sh)

set -euo pipefail

AZURE_CLIENT_ID="${1:-${AZURE_CLIENT_ID:-}}"
BACKEND_UAMI_CLIENT_ID="${2:-${BACKEND_UAMI_CLIENT_ID:-}}"

if [ -z "$AZURE_CLIENT_ID" ] || [ -z "$BACKEND_UAMI_CLIENT_ID" ]; then
  echo "ERROR: pass AZURE_CLIENT_ID and BACKEND_UAMI_CLIENT_ID (from 01-bootstrap-azure.sh)" >&2
  exit 1
fi

REPO="${REPO:-Co-Actor/AIDetect}"
ENV="${ENV:-development}"

# Defaults — override via env if needed
AZURE_TENANT_ID="${AZURE_TENANT_ID:-126403ee-2465-4019-8431-5a17899b6774}"
AZURE_SUBSCRIPTION_ID="${AZURE_SUBSCRIPTION_ID:-71ddbd6b-dfbd-4293-bfbd-155afd7b518d}"
AKS_NAME="${AKS_NAME:-aks-memory-actor}"
AKS_RESOURCE_GROUP="${AKS_RESOURCE_GROUP:-DefaultResourceGroup-EUS}"
K8S_NAMESPACE="${K8S_NAMESPACE:-dev}"
HELM_RELEASE="${HELM_RELEASE:-aidetect-dev}"
IMAGE_NAMESPACE="${IMAGE_NAMESPACE:-co-actor}"
GHCR_PULL_SECRET_NAME="${GHCR_PULL_SECRET_NAME:-}"
API_HOST="${API_HOST:-apiaidetect.co.actor}"
APP_HOST="${APP_HOST:-aidetect.co.actor}"

echo "==> Creating GitHub environment '$ENV' on $REPO (idempotent)"
gh api --method PUT "repos/$REPO/environments/$ENV" -H "Accept: application/vnd.github+json" >/dev/null

set_var() {
  local name="$1"
  local value="$2"
  echo "    $name = $value"
  gh variable set "$name" --env "$ENV" --repo "$REPO" --body "$value" >/dev/null
}

echo "==> Setting environment variables"
set_var AZURE_CLIENT_ID "$AZURE_CLIENT_ID"
set_var AZURE_TENANT_ID "$AZURE_TENANT_ID"
set_var AZURE_SUBSCRIPTION_ID "$AZURE_SUBSCRIPTION_ID"
set_var AKS_NAME "$AKS_NAME"
set_var AKS_RESOURCE_GROUP "$AKS_RESOURCE_GROUP"
set_var K8S_NAMESPACE "$K8S_NAMESPACE"
set_var HELM_RELEASE "$HELM_RELEASE"
set_var IMAGE_NAMESPACE "$IMAGE_NAMESPACE"
set_var BACKEND_UAMI_CLIENT_ID "$BACKEND_UAMI_CLIENT_ID"
set_var GHCR_PULL_SECRET_NAME "$GHCR_PULL_SECRET_NAME"
set_var API_HOST "$API_HOST"
set_var APP_HOST "$APP_HOST"

echo
echo "✅ GitHub environment '$ENV' is configured."
echo "    See: https://github.com/$REPO/settings/environments/$ENV"
