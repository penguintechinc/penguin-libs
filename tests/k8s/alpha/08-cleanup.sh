#!/bin/bash

# === Cleanup Step ===
# Remove deployed resources from alpha namespace

set -e

PROJECT_NAME="penguin-libs"
NAMESPACE="penguin-libs-alpha"

echo "Cleaning up resources from namespace: $NAMESPACE"

# Uninstall the Helm release
helm uninstall "$PROJECT_NAME" -n "$NAMESPACE" 2>/dev/null || true

# Optionally delete the namespace (comment out if you want to keep it)
# kubectl delete namespace "$NAMESPACE" --ignore-not-found=true

echo "Cleanup completed"
