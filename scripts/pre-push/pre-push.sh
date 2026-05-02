#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "=== Pre-push: K8s Alpha E2E Tests ==="

if ! command -v kubectl &>/dev/null && ! command -v microk8s &>/dev/null; then
  echo "ERROR: kubectl/microk8s not found."
  echo "Alpha E2E tests are required before pushing. Install MicroK8s or Docker Desktop K8s."
  exit 1
fi

echo "Running alpha deploy..."
make k8s-alpha-deploy

echo "Running alpha E2E tests..."
make k8s-alpha-test

echo "Cleaning up..."
make k8s-cleanup

echo "=== Pre-push checks passed ==="
