#!/usr/bin/env bash
#
# Import AIDetect backend secrets into Azure Key Vault kv-aidetect-dev.
#
# REDIS_URL can be passed as $1 (e.g. from 01-bootstrap-azure.sh output);
# the other two are prompted for. Empty input keeps the existing value in KV.
#
# Usage:
#   bash infra/scripts/03-import-secrets.sh "<redis-url-from-bootstrap>"
#   bash infra/scripts/03-import-secrets.sh                          # all interactive

set -euo pipefail

KV="${KV:-kv-aidetect-dev}"
REDIS_URL="${1:-${REDIS_URL:-}}"

set_secret_if_provided() {
  local name="$1"
  local value="$2"
  if [ -z "$value" ]; then
    echo "  - $name: skipped (empty input)"
    return
  fi
  az keyvault secret set --vault-name "$KV" -n "$name" --value "$value" -o none
  echo "  - $name: set"
}

read_secret() {
  local prompt="$1"
  local value
  read -r -s -p "$prompt: " value
  echo
  echo "$value"
}

echo "==> Importing secrets to Key Vault $KV"

if [ -z "$REDIS_URL" ]; then
  REDIS_URL=$(read_secret "REDIS_URL (rediss://:<key>@<host>:6380/0)")
fi
OPENROUTER_KEY=$(read_secret "OPENROUTER_API_KEY")
INTERNAL_TOKEN=$(read_secret "AIDETECT_INTERNAL_TOKEN (≥8 chars; press Enter to auto-generate)")

if [ -z "$INTERNAL_TOKEN" ]; then
  INTERNAL_TOKEN=$(openssl rand -hex 24)
  echo "    (auto-generated AIDETECT_INTERNAL_TOKEN: $INTERNAL_TOKEN — keep a copy)"
fi

set_secret_if_provided "aidetect-dev-backend-REDIS-URL" "$REDIS_URL"
set_secret_if_provided "aidetect-dev-backend-OPENROUTER-API-KEY" "$OPENROUTER_KEY"
set_secret_if_provided "aidetect-dev-backend-AIDETECT-INTERNAL-TOKEN" "$INTERNAL_TOKEN"

echo
echo "==> Current secrets in $KV:"
az keyvault secret list --vault-name "$KV" --query "[?starts_with(name, 'aidetect-dev-backend-')].name" -o tsv

echo "✅ Done."
echo
echo "When you deploy Langfuse separately and want to enable tracing:"
echo "  az keyvault secret set --vault-name $KV -n aidetect-dev-backend-LANGFUSE-PUBLIC-KEY --value '<...>'"
echo "  az keyvault secret set --vault-name $KV -n aidetect-dev-backend-LANGFUSE-SECRET-KEY --value '<...>'"
echo "  ...then add LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY to values.yaml secretEnvKeys and flip LANGFUSE_ENABLED=1."
