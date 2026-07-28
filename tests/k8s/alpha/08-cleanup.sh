#!/bin/bash

# === Cleanup Step ===
# Remove deployed resources from alpha namespace

set -e

PROJECT_NAME="penguin-libs"
NAMESPACE="penguin-libs"

echo "Cleaning up resources from namespace: $NAMESPACE"

# Uninstall the Helm release
helm uninstall "$PROJECT_NAME" -n "$NAMESPACE" --kube-context local-alpha 2>/dev/null || true

# Delete the namespace
kubectl delete namespace "$NAMESPACE" --ignore-not-found=true --context local-alpha 2>/dev/null || true

echo "Cleanup completed"
