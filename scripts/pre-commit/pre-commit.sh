#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Detect changed packages
CHANGED_FILES=$(git diff --cached --name-only --diff-filter=ACMR)

check_go_aaa=false
check_go_common=false
check_python_aaa=false
check_python_utils=false
check_react_aaa=false
check_react_libs=false

for f in $CHANGED_FILES; do
  case "$f" in
    packages/go-aaa/*) check_go_aaa=true ;;
    packages/go-common/*) check_go_common=true ;;
    packages/python-aaa/*) check_python_aaa=true ;;
    packages/python-utils/*) check_python_utils=true ;;
    packages/react-aaa/*) check_react_aaa=true ;;
    packages/react-libs/*) check_react_libs=true ;;
  esac
done

# If nothing relevant changed, skip
if ! $check_go_aaa && ! $check_go_common && ! $check_python_aaa && ! $check_python_utils && ! $check_react_aaa && ! $check_react_libs; then
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
if $check_python_aaa; then
  echo "Building python-aaa..."
  cd packages/python-aaa && python -m py_compile src/penguin_aaa/__init__.py && cd "$REPO_ROOT"
fi
if $check_python_utils; then
  echo "Building python-utils..."
  cd packages/python-utils && python -m py_compile src/penguintechinc_utils/__init__.py && cd "$REPO_ROOT"
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
if $check_python_aaa; then
  echo "Linting python-aaa..."
  cd packages/python-aaa && ruff check src/ tests/ && ruff format --check src/ tests/ && cd "$REPO_ROOT"
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
if $check_python_aaa; then
  echo "Security scanning python-aaa..."
  cd packages/python-aaa && bandit -r src/ -c pyproject.toml && cd "$REPO_ROOT"
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
if $check_python_aaa; then
  echo "Testing python-aaa..."
  cd packages/python-aaa && pytest tests/ -v --tb=short && cd "$REPO_ROOT"
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

echo "=== All pre-commit checks passed ==="
