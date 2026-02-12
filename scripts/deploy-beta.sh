#!/bin/bash
set -euo pipefail

################################################################################
# Penguin-libs Kubernetes Deployment Script (Beta Environment)
#
# This script handles building, pushing, and deploying penguin-libs to a
# Kubernetes cluster with comprehensive logging, error handling, and rollback.
#
# Usage: ./deploy-beta.sh [OPTIONS]
################################################################################

# Configuration
RELEASE_NAME="penguin-libs"
NAMESPACE="penguin-libs"
CHART_PATH="k8s/helm/penguin-libs"
IMAGE_REGISTRY="registry-dal2.penguintech.io"
KUBE_CONTEXT="dal2-beta"
APP_HOST="penguin-libs.penguintech.io"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP=$(date +%s)
BUILD_TAG="${TIMESTAMP}"
SERVICE_NAME=""
SKIP_BUILD=false
DRY_RUN=false
ROLLBACK_REVISION=""
VERBOSE=false

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

################################################################################
# Helper Functions
################################################################################

log_info() {
  echo -e "${BLUE}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

log_success() {
  echo -e "${GREEN}[SUCCESS]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

log_warn() {
  echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

log_debug() {
  if [ "$VERBOSE" = true ]; then
    echo -e "${CYAN}[DEBUG]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $*"
  fi
}

print_header() {
  echo ""
  echo -e "${BLUE}========================================${NC}"
  echo -e "${BLUE}$*${NC}"
  echo -e "${BLUE}========================================${NC}"
  echo ""
}

print_section() {
  echo ""
  echo -e "${CYAN}>>> $*${NC}"
  echo ""
}

print_divider() {
  echo -e "${BLUE}----------------------------------------${NC}"
}

################################################################################
# Validation & Prerequisites
################################################################################

check_prerequisites() {
  print_section "Checking Prerequisites"

  local missing_tools=()

  # Check required tools
  for tool in docker kubectl kustomize helm git; do
    if ! command -v "$tool" &> /dev/null; then
      missing_tools+=("$tool")
    else
      log_debug "$tool found: $(command -v "$tool")"
    fi
  done

  if [ ${#missing_tools[@]} -ne 0 ]; then
    log_error "Missing required tools: ${missing_tools[*]}"
    log_error "Please install: docker, kubectl, kustomize, helm, git"
    exit 1
  fi

  log_success "All required tools found"

  # Check kubeconfig
  if [ ! -f "$HOME/.kube/config" ]; then
    log_error "kubeconfig not found at $HOME/.kube/config"
    exit 1
  fi

  log_debug "kubeconfig found: $HOME/.kube/config"

  # Check docker daemon
  if ! docker info &> /dev/null; then
    log_error "Docker daemon is not running"
    exit 1
  fi

  log_success "Docker daemon is running"

  # Validate kubectl connection
  if ! kubectl cluster-info &> /dev/null; then
    log_error "Cannot connect to Kubernetes cluster"
    log_error "Current context: $(kubectl config current-context)"
    exit 1
  fi

  log_success "Connected to Kubernetes cluster"
  log_debug "Current context: $(kubectl config current-context)"
}

validate_kube_context() {
  print_section "Validating Kubernetes Context"

  local current_context=$(kubectl config current-context)

  if [ "$current_context" != "$KUBE_CONTEXT" ]; then
    log_warn "Current context is '$current_context', expected '$KUBE_CONTEXT'"
    log_info "Switching to context: $KUBE_CONTEXT"

    if kubectl config use-context "$KUBE_CONTEXT" &> /dev/null; then
      log_success "Switched to context: $KUBE_CONTEXT"
    else
      log_error "Failed to switch to context: $KUBE_CONTEXT"
      log_error "Available contexts:"
      kubectl config get-contexts
      exit 1
    fi
  else
    log_success "Already in context: $KUBE_CONTEXT"
  fi
}

validate_paths() {
  print_section "Validating Paths"

  if [ ! -d "$SCRIPT_DIR" ]; then
    log_error "Script directory not found: $SCRIPT_DIR"
    exit 1
  fi
  log_debug "Script directory: $SCRIPT_DIR"

  if [ ! -d "$SCRIPT_DIR/$CHART_PATH" ]; then
    log_error "Helm chart path not found: $SCRIPT_DIR/$CHART_PATH"
    exit 1
  fi
  log_success "Helm chart found: $SCRIPT_DIR/$CHART_PATH"

  if [ ! -f "$SCRIPT_DIR/$CHART_PATH/Chart.yaml" ]; then
    log_error "Chart.yaml not found in: $SCRIPT_DIR/$CHART_PATH"
    exit 1
  fi
  log_success "Chart.yaml found"

  if [ ! -d "$SCRIPT_DIR/k8s/kustomize" ]; then
    log_error "Kustomize directory not found: $SCRIPT_DIR/k8s/kustomize"
    exit 1
  fi
  log_success "Kustomize directory found"
}

################################################################################
# Build & Push Functions
################################################################################

build_and_push() {
  print_section "Building and Pushing Docker Images"

  if [ "$SKIP_BUILD" = true ]; then
    log_warn "Skipping build (--skip-build flag set)"
    return 0
  fi

  local buildValidator_image="${IMAGE_REGISTRY}/build-validator:${BUILD_TAG}"

  if [ -n "$SERVICE_NAME" ] && [ "$SERVICE_NAME" != "buildValidator" ]; then
    log_info "Skipping build - only building $SERVICE_NAME (not applicable)"
    return 0
  fi

  # Build buildValidator
  log_info "Building buildValidator image..."

  if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN: Would execute: docker build -t $buildValidator_image ."
    return 0
  fi

  if docker build -t "$buildValidator_image" "$SCRIPT_DIR"; then
    log_success "Successfully built: $buildValidator_image"
  else
    log_error "Failed to build buildValidator image"
    return 1
  fi

  # Push image
  log_info "Pushing buildValidator image to registry..."

  if docker push "$buildValidator_image"; then
    log_success "Successfully pushed: $buildValidator_image"
  else
    log_error "Failed to push buildValidator image"
    return 1
  fi
}

################################################################################
# Deployment Functions
################################################################################

create_namespace() {
  print_section "Creating/Updating Namespace"

  if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN: Would create namespace $NAMESPACE"
    return 0
  fi

  if kubectl get namespace "$NAMESPACE" &> /dev/null; then
    log_info "Namespace $NAMESPACE already exists"
  else
    log_info "Creating namespace: $NAMESPACE"
    if kubectl create namespace "$NAMESPACE"; then
      log_success "Created namespace: $NAMESPACE"
    else
      log_error "Failed to create namespace: $NAMESPACE"
      return 1
    fi
  fi
}

deploy_with_helm() {
  print_section "Deploying with Helm"

  local values_file="$SCRIPT_DIR/$CHART_PATH/values-beta.yaml"

  if [ ! -f "$values_file" ]; then
    log_warn "Values file not found: $values_file"
    values_file="$SCRIPT_DIR/$CHART_PATH/values.yaml"
  fi

  log_info "Using values file: $values_file"

  local helm_cmd=(
    "helm" "upgrade" "--install"
    "$RELEASE_NAME"
    "$SCRIPT_DIR/$CHART_PATH"
    "--namespace" "$NAMESPACE"
    "--values" "$values_file"
    "--create-namespace"
    "--timeout" "5m"
  )

  if [ "$DRY_RUN" = true ]; then
    helm_cmd+=("--dry-run" "--debug")
    log_warn "DRY RUN: Executing helm with --dry-run"
  fi

  log_debug "Executing: ${helm_cmd[*]}"

  if "${helm_cmd[@]}"; then
    log_success "Helm deployment successful"
  else
    log_error "Helm deployment failed"
    return 1
  fi
}

deploy_with_kustomize() {
  print_section "Deploying with Kustomize (Beta Overlay)"

  local overlay_path="$SCRIPT_DIR/k8s/kustomize/overlays/beta"

  if [ ! -d "$overlay_path" ]; then
    log_error "Beta overlay not found: $overlay_path"
    return 1
  fi

  log_info "Building manifests from: $overlay_path"

  local kustomize_cmd=(
    "kustomize" "build" "$overlay_path"
  )

  if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN: Would apply kustomize manifests"
  fi

  log_debug "Executing: ${kustomize_cmd[*]}"

  if "${kustomize_cmd[@]}" | kubectl apply $([ "$DRY_RUN" = true ] && echo "--dry-run=client" || echo ""); then
    log_success "Kustomize deployment successful"
  else
    log_error "Kustomize deployment failed"
    return 1
  fi
}

################################################################################
# Verification Functions
################################################################################

verify_deployment() {
  print_section "Verifying Deployment"

  if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN: Skipping deployment verification"
    return 0
  fi

  log_info "Waiting for rollout..."

  local timeout=300 # 5 minutes
  local start_time=$(date +%s)

  while true; do
    local current_time=$(date +%s)
    local elapsed=$((current_time - start_time))

    if [ $elapsed -gt $timeout ]; then
      log_error "Deployment verification timeout after ${timeout}s"
      return 1
    fi

    if kubectl rollout status deployment -n "$NAMESPACE" --timeout=30s 2>/dev/null; then
      log_success "Deployment rollout successful"
      break
    fi

    log_info "Waiting for deployment to be ready... (${elapsed}s/${timeout}s)"
    sleep 5
  done

  print_divider

  log_info "Deployment Status:"
  kubectl get deployments -n "$NAMESPACE" -o wide

  print_divider

  log_info "Pod Status:"
  kubectl get pods -n "$NAMESPACE" -o wide

  print_divider

  log_info "Services:"
  kubectl get svc -n "$NAMESPACE" -o wide

  # Check pod logs
  log_info "Checking pod logs for errors..."
  local pods=$(kubectl get pods -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}')

  for pod in $pods; do
    log_debug "Checking logs for pod: $pod"
    if ! kubectl logs -n "$NAMESPACE" "$pod" 2>&1 | grep -i error | head -5; then
      log_debug "No errors found in pod: $pod"
    fi
  done

  log_success "Deployment verified"
}

check_app_health() {
  print_section "Checking Application Health"

  if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN: Skipping health check"
    return 0
  fi

  log_info "Application host: $APP_HOST"
  log_info "Namespace: $NAMESPACE"
  log_info "Release: $RELEASE_NAME"

  # Try to get service endpoint
  local service_ip=$(kubectl get svc -n "$NAMESPACE" -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")

  if [ -z "$service_ip" ] || [ "$service_ip" = "pending" ]; then
    log_warn "Load balancer IP not yet assigned (this is normal for some environments)"
    service_ip=$(kubectl get svc -n "$NAMESPACE" -o jsonpath='{.items[0].spec.clusterIP}' 2>/dev/null || echo "unknown")
  fi

  log_info "Service IP: $service_ip"

  log_success "Application deployment complete"
}

################################################################################
# Rollback Functions
################################################################################

rollback_deployment() {
  print_section "Rolling Back Deployment"

  if [ -z "$ROLLBACK_REVISION" ]; then
    log_info "No specific revision specified, rolling back to previous release"
    ROLLBACK_REVISION="0"
  fi

  log_warn "Rolling back to revision: $ROLLBACK_REVISION"

  if helm rollback "$RELEASE_NAME" "$ROLLBACK_REVISION" -n "$NAMESPACE"; then
    log_success "Rollback successful"

    log_info "Waiting for rollback to complete..."
    if kubectl rollout status deployment -n "$NAMESPACE" --timeout=5m; then
      log_success "Rollback verification complete"
    else
      log_error "Rollback verification failed"
      return 1
    fi
  else
    log_error "Rollback failed"
    return 1
  fi
}

################################################################################
# Usage & Help
################################################################################

print_help() {
  cat << 'EOF'
Penguin-libs Kubernetes Deployment Script (Beta Environment)

Usage: ./scripts/deploy-beta.sh [OPTIONS]

OPTIONS:
  --tag TAG                 Docker image tag (default: unix timestamp)
  --service SERVICE         Deploy only specific service (buildValidator)
  --skip-build              Skip docker build and push
  --dry-run                 Perform a dry-run without applying changes
  --rollback [REVISION]     Rollback to previous or specified revision
  --verbose                 Enable verbose/debug output
  --help                    Show this help message

EXAMPLES:
  # Standard deployment
  ./scripts/deploy-beta.sh

  # Deploy with custom tag
  ./scripts/deploy-beta.sh --tag v1.2.3

  # Dry-run to see what would be deployed
  ./scripts/deploy-beta.sh --dry-run

  # Skip build and push (use existing image)
  ./scripts/deploy-beta.sh --skip-build

  # Rollback to previous release
  ./scripts/deploy-beta.sh --rollback

  # Rollback to specific revision
  ./scripts/deploy-beta.sh --rollback 2

  # Verbose output
  ./scripts/deploy-beta.sh --verbose

CONFIGURATION:
  Release Name:     penguin-libs
  Namespace:        penguin-libs
  Kube Context:     dal2-beta
  Image Registry:   registry-dal2.penguintech.io
  App Host:         penguin-libs.penguintech.io
  Helm Chart:       k8s/helm/penguin-libs
  Kustomize Base:   k8s/kustomize/base
  Kustomize Overlay: k8s/kustomize/overlays/beta

REQUIREMENTS:
  - Docker (running daemon)
  - kubectl (configured)
  - Helm 3.x
  - Kustomize 4.x+
  - Kubernetes cluster access (dal2-beta context)
  - Docker registry credentials configured

NOTES:
  - The script uses Helm for deployment by default
  - Kustomize overlay is available for alternative deployments
  - All deployments include health checks and verification
  - Failed deployments can be rolled back using --rollback
  - Verbose mode provides detailed debugging information

EOF
}

################################################################################
# Main Execution
################################################################################

main() {
  # Parse command-line arguments
  while [[ $# -gt 0 ]]; do
    case $1 in
      --tag)
        BUILD_TAG="$2"
        shift 2
        ;;
      --service)
        SERVICE_NAME="$2"
        shift 2
        ;;
      --skip-build)
        SKIP_BUILD=true
        shift
        ;;
      --dry-run)
        DRY_RUN=true
        shift
        ;;
      --rollback)
        if [[ -n "$2" && "$2" != --* ]]; then
          ROLLBACK_REVISION="$2"
          shift 2
        else
          ROLLBACK_REVISION="0"
          shift
        fi
        ;;
      --verbose)
        VERBOSE=true
        shift
        ;;
      --help)
        print_help
        exit 0
        ;;
      *)
        log_error "Unknown option: $1"
        echo "Use --help for usage information"
        exit 1
        ;;
    esac
  done

  print_header "Penguin-libs Kubernetes Deployment"

  log_info "Configuration:"
  log_info "  Release Name: $RELEASE_NAME"
  log_info "  Namespace: $NAMESPACE"
  log_info "  Kube Context: $KUBE_CONTEXT"
  log_info "  Image Registry: $IMAGE_REGISTRY"
  log_info "  Build Tag: $BUILD_TAG"
  log_info "  Dry Run: $DRY_RUN"
  log_info "  Skip Build: $SKIP_BUILD"

  if [ -n "$ROLLBACK_REVISION" ]; then
    log_info "  Rollback Revision: $ROLLBACK_REVISION"
  fi

  # Handle rollback
  if [ -n "$ROLLBACK_REVISION" ]; then
    check_prerequisites
    validate_kube_context
    rollback_deployment
    check_app_health
    print_header "Rollback Complete"
    exit 0
  fi

  # Standard deployment flow
  check_prerequisites
  validate_kube_context
  validate_paths
  build_and_push
  create_namespace
  deploy_with_helm
  verify_deployment
  check_app_health

  print_header "Deployment Complete"

  log_success "Penguin-libs successfully deployed to $NAMESPACE"
  log_info "App URL: http://$APP_HOST"
  log_info "Release: $RELEASE_NAME"
  log_info "Namespace: $NAMESPACE"

  exit 0
}

# Execute main function
main "$@"
