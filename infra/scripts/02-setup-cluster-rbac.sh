#!/usr/bin/env bash
#
# Grant in-cluster RBAC to the CI principal so Helm can manage AIDetect resources
# inside the shared `dev` namespace.
#
# Usage:  bash infra/scripts/02-setup-cluster-rbac.sh <ci-principal-id>
#         (the CI principal id is printed by 01-bootstrap-azure.sh)

set -euo pipefail

CI_PRINCIPAL="${1:-${CI_PRINCIPAL:-}}"
NS="${NS:-dev}"

if [ -z "$CI_PRINCIPAL" ]; then
  # Try to recover from azure if not provided
  CI_PRINCIPAL=$(az identity show -n id-aidetect-development-deploy -g "${RG:-DefaultResourceGroup-EUS}" --query principalId -o tsv 2>/dev/null || true)
fi

if [ -z "$CI_PRINCIPAL" ]; then
  echo "ERROR: pass CI principal id as argument or set CI_PRINCIPAL env var." >&2
  echo "       Hint: run 01-bootstrap-azure.sh first; it prints CI_PRINCIPAL_ID." >&2
  exit 1
fi

echo "==> Applying Role + RoleBinding for CI principal in namespace $NS"
echo "    CI_PRINCIPAL = $CI_PRINCIPAL"

kubectl apply -n "$NS" -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: aidetect-dev-deployer
  namespace: $NS
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
  namespace: $NS
subjects:
  - kind: User
    name: $CI_PRINCIPAL
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: aidetect-dev-deployer
  apiGroup: rbac.authorization.k8s.io
EOF

echo "✅ Cluster RBAC applied."
