#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Detect changed packages
CHANGED_FILES=$(git diff --cached --name-only --diff-filter=ACMR)

check_go_aaa=false
check_go_common=false
check_go_crypto=false
check_go_http=false
check_go_logging=false
check_go_numa=false
check_go_xdp=false
check_python_aaa=false
check_python_crypto=false
check_python_http=false
check_python_security=false
check_python_utils=false
check_react_aaa=false
check_react_libs=false

for f in $CHANGED_FILES; do
  case "$f" in
    packages/go-aaa/*) check_go_aaa=true ;;
    packages/go-common/*) check_go_common=true ;;
    packages/go-crypto/*) check_go_crypto=true ;;
    packages/go-h3/*) check_go_http=true ;;
    packages/go-logging/*) check_go_logging=true ;;
    packages/go-numa/*) check_go_numa=true ;;
    packages/go-xdp/*) check_go_xdp=true ;;
    packages/python-aaa/*) check_python_aaa=true ;;
    packages/python-crypto/*) check_python_crypto=true ;;
    packages/python-http/*) check_python_http=true ;;
    packages/python-security/*) check_python_security=true ;;
    packages/python-utils/*) check_python_utils=true ;;
    packages/react-aaa/*) check_react_aaa=true ;;
    packages/react-libs/*) check_react_libs=true ;;
  esac
done

# If nothing relevant changed, skip
if ! $check_go_aaa && ! $check_go_common && ! $check_go_crypto && ! $check_go_http && \
   ! $check_go_logging && ! $check_go_numa && ! $check_go_xdp && \
   ! $check_python_aaa && ! $check_python_crypto && ! $check_python_http && \
   ! $check_python_security && ! $check_python_utils && \
   ! $check_react_aaa && ! $check_react_libs; then
  echo "No relevant package changes detected, skipping pre-commit checks."
  exit 0
fi

echo "=== Step 1: Build ==="
if $check_go_common; then
  echo "Building go-common..."
  cd packages/go-common && go build ./... && cd "$REPO_ROOT"
fi
if $check_go_aaa; then
  echo "Building go-aaa..."
  cd packages/go-aaa && go build ./... && cd "$REPO_ROOT"
fi
if $check_go_logging; then
  echo "Building go-logging..."
  cd packages/go-logging && go build ./... && cd "$REPO_ROOT"
fi
if $check_go_numa; then
  echo "Building go-numa..."
  cd packages/go-numa && go build ./... && cd "$REPO_ROOT"
fi
if $check_go_xdp; then
  echo "Building go-xdp..."
  cd packages/go-xdp && go build ./... && cd "$REPO_ROOT"
fi
if $check_go_http; then
  echo "Building go-h3..."
  cd packages/go-h3 && go build ./... && cd "$REPO_ROOT"
fi
if $check_python_aaa; then
  echo "Building python-aaa..."
  cd packages/python-aaa && python3 -m py_compile src/penguin_aaa/__init__.py && cd "$REPO_ROOT"
fi
if $check_python_crypto; then
  echo "Building python-crypto..."
  cd packages/python-crypto && python3 -m py_compile src/penguin_crypto/__init__.py && cd "$REPO_ROOT"
fi
if $check_python_security; then
  echo "Building python-security..."
  cd packages/python-security && python3 -m py_compile src/penguin_security/__init__.py && cd "$REPO_ROOT"
fi
if $check_python_http; then
  echo "Building python-http..."
  cd packages/python-http && python3 -m py_compile src/penguin_http/__init__.py && cd "$REPO_ROOT"
fi
if $check_python_utils; then
  echo "Building python-utils..."
  cd packages/python-utils && python3 -m py_compile src/penguintechinc_utils/__init__.py && cd "$REPO_ROOT"
fi
if $check_react_aaa; then
  echo "Building react-aaa..."
  cd packages/react-aaa && npm run build && cd "$REPO_ROOT"
fi
if $check_react_libs; then
  echo "Building react-libs..."
  cd packages/react-libs && npm run build && cd "$REPO_ROOT"
fi

echo "=== Step 2: Lint ==="
if $check_go_common; then
  echo "Linting go-common..."
  cd packages/go-common && golangci-lint run ./... && cd "$REPO_ROOT"
fi
if $check_go_aaa; then
  echo "Linting go-aaa..."
  cd packages/go-aaa && golangci-lint run ./... && cd "$REPO_ROOT"
fi
if $check_go_logging; then
  echo "Linting go-logging..."
  cd packages/go-logging && golangci-lint run ./... && cd "$REPO_ROOT"
fi
if $check_go_numa; then
  echo "Linting go-numa..."
  cd packages/go-numa && golangci-lint run ./... && cd "$REPO_ROOT"
fi
if $check_go_xdp; then
  echo "Linting go-xdp..."
  cd packages/go-xdp && golangci-lint run ./... && cd "$REPO_ROOT"
fi
if $check_go_http; then
  echo "Linting go-h3..."
  cd packages/go-h3 && golangci-lint run ./... && cd "$REPO_ROOT"
fi
if $check_python_aaa; then
  echo "Linting python-aaa..."
  cd packages/python-aaa && ruff check src/ tests/ && ruff format --check src/ tests/ && cd "$REPO_ROOT"
fi
if $check_python_crypto; then
  echo "Linting python-crypto..."
  cd packages/python-crypto && ruff check src/ && cd "$REPO_ROOT"
fi
if $check_python_security; then
  echo "Linting python-security..."
  cd packages/python-security && ruff check src/ && cd "$REPO_ROOT"
fi
if $check_python_http; then
  echo "Linting python-http..."
  cd packages/python-http && ruff check src/ && cd "$REPO_ROOT"
fi
if $check_python_utils; then
  echo "Linting python-utils..."
  cd packages/python-utils && ruff check src/ tests/ && ruff format --check src/ tests/ && cd "$REPO_ROOT"
fi
if $check_react_aaa; then
  echo "Linting react-aaa..."
  cd packages/react-aaa && npm run lint && cd "$REPO_ROOT"
fi
if $check_react_libs; then
  echo "Linting react-libs..."
  cd packages/react-libs && npm run lint && cd "$REPO_ROOT"
fi

echo "=== Step 3: Security ==="
if $check_go_common; then
  echo "Security scanning go-common..."
  cd packages/go-common && govulncheck ./... && gosec -quiet ./... && cd "$REPO_ROOT"
fi
if $check_go_aaa; then
  echo "Security scanning go-aaa..."
  cd packages/go-aaa && govulncheck ./... && gosec -quiet ./... && cd "$REPO_ROOT"
fi
if $check_go_logging; then
  echo "Security scanning go-logging..."
  cd packages/go-logging && govulncheck ./... && gosec -quiet ./... && cd "$REPO_ROOT"
fi
if $check_python_aaa; then
  echo "Security scanning python-aaa..."
  cd packages/python-aaa && bandit -r src/ -c pyproject.toml && cd "$REPO_ROOT"
fi
if $check_python_crypto; then
  echo "Security scanning python-crypto..."
  cd packages/python-crypto && bandit -r src/ -ll && cd "$REPO_ROOT"
fi
if $check_python_security; then
  echo "Security scanning python-security..."
  cd packages/python-security && bandit -r src/ -ll && cd "$REPO_ROOT"
fi
if $check_python_http; then
  echo "Security scanning python-http..."
  cd packages/python-http && bandit -r src/ -ll && cd "$REPO_ROOT"
fi
if $check_python_utils; then
  echo "Security scanning python-utils..."
  cd packages/python-utils && bandit -r src/ -c pyproject.toml && cd "$REPO_ROOT"
fi
if $check_react_aaa; then
  echo "Security scanning react-aaa..."
  cd packages/react-aaa && npm audit --omit=dev && cd "$REPO_ROOT"
fi

echo "=== Step 4: Test ==="
if $check_go_common; then
  echo "Testing go-common..."
  cd packages/go-common && go test -race -v ./... && cd "$REPO_ROOT"
fi
if $check_go_aaa; then
  echo "Testing go-aaa..."
  cd packages/go-aaa && go test -race -v ./... && cd "$REPO_ROOT"
fi
if $check_go_logging; then
  echo "Testing go-logging..."
  cd packages/go-logging && go test -race -v ./... && cd "$REPO_ROOT"
fi
if $check_go_http; then
  echo "Testing go-h3..."
  cd packages/go-h3 && go test -race -v ./... && cd "$REPO_ROOT"
fi
if $check_python_aaa; then
  echo "Testing python-aaa..."
  cd packages/python-aaa && pytest tests/ -v --tb=short && cd "$REPO_ROOT"
fi
if $check_python_crypto; then
  echo "Testing python-crypto..."
  cd packages/python-crypto && pytest tests/ -v --tb=short && cd "$REPO_ROOT"
fi
if $check_python_security; then
  echo "Testing python-security..."
  cd packages/python-security && pytest tests/ -v --tb=short && cd "$REPO_ROOT"
fi
if $check_python_http; then
  echo "Testing python-http..."
  cd packages/python-http && pytest tests/ -v --tb=short && cd "$REPO_ROOT"
fi
if $check_python_utils; then
  echo "Testing python-utils..."
  cd packages/python-utils && pytest tests/ -v --tb=short && cd "$REPO_ROOT"
fi
if $check_react_aaa; then
  echo "Testing react-aaa..."
  cd packages/react-aaa && npm test && cd "$REPO_ROOT"
fi
if $check_react_libs; then
  echo "Testing react-libs..."
  cd packages/react-libs && npm test && cd "$REPO_ROOT"
fi

echo "=== Step 5: K8s Smoke Tests ==="
if command -v kubectl &>/dev/null || command -v microk8s &>/dev/null; then
  echo "K8s detected — running alpha smoke tests..."
  make k8s-alpha-deploy
  make k8s-cleanup
else
  echo "kubectl/microk8s not found — skipping K8s smoke tests (run locally before pushing to main)."
fi

echo "=== All pre-commit checks passed ==="
