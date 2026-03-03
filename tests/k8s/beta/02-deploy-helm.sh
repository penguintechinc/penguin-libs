#!/bin/bash

# === Helm Deployment Step ===
# Deploy penguin-libs validation chart to beta namespace

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../" && pwd)"
HELM_DIR="$PROJECT_ROOT/k8s/helm/penguin-libs"
PROJECT_NAME="penguin-libs"
NAMESPACE="penguin-libs-beta"

echo "Deploying Helm chart to namespace: $NAMESPACE"
echo "Chart location: $HELM_DIR"

# Deploy the chart (--create-namespace handles namespace creation)
helm upgrade --install "$PROJECT_NAME" "$HELM_DIR" \
    --namespace "$NAMESPACE" \
    --create-namespace \
    --values "$HELM_DIR/values-beta.yaml" \
    --wait \
    --timeout 5m

echo "Helm deployment completed successfully"
