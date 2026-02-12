#!/bin/bash

# === Penguin-libs K8s Beta Smoke Test Orchestrator ===
# Runs comprehensive validation suite for NPM package library in K8s

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../" && pwd)"
NAMESPACE="penguin-libs-beta"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_section() {
    echo ""
    echo -e "${GREEN}=== $1 ===${NC}"
}

# Change to project root
cd "$PROJECT_ROOT"

log_section "Starting Beta Smoke Test Suite"

# Execute test steps
log_section "Step 1: Building container images"
"$SCRIPT_DIR/01-build-images.sh"

log_section "Step 2: Deploying Helm chart"
"$SCRIPT_DIR/02-deploy-helm.sh"

log_section "Step 3: Waiting for deployment readiness"
"$SCRIPT_DIR/03-wait-ready.sh"

log_section "Step 4: Running health checks"
"$SCRIPT_DIR/04-health-check.sh"

log_section "Step 5: Running unit tests"
"$SCRIPT_DIR/05-unit-tests.sh"

log_section "Step 6: API/Integration tests"
"$SCRIPT_DIR/06-api-integration.sh"

log_section "Step 7: Page load tests"
"$SCRIPT_DIR/07-page-load.sh"

log_section "Step 8: Cleanup"
"$SCRIPT_DIR/08-cleanup.sh"

log_info "Beta smoke test suite completed successfully"
echo ""
