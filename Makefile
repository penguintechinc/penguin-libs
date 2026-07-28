# === Development Targets ===

.PHONY: lint test test-security security build pre-commit install-tools install-hooks prpc-proto prpc-generate prpc-generate-check prpc-integration

build: ## Build/compile all packages
	@echo "=== Building Go packages ==="
	cd packages/go-common && go build ./...
	cd packages/go-aaa && go build ./...
	cd packages/go-rpc && go build ./...
	@echo "=== Building Python packages ==="
	cd packages/python-aaa && python3 -m py_compile src/penguin_aaa/__init__.py
	cd packages/python-utils && python3 -m py_compile src/penguintechinc_utils/__init__.py
	cd packages/python-rpc && python3 -m py_compile src/penguin_rpc/__init__.py
	cd packages/python-email && python3 -m py_compile src/penguin_email/__init__.py
	@echo "=== Building React packages ==="
	cd packages/react-aaa && npm run build
	cd packages/react-libs && npm run build
	@echo "=== Building Rust packages ==="
	cd packages/rust-rpc && cargo build --workspace

lint: ## Run linters on all packages
	@echo "=== Go lint ==="
	cd packages/go-aaa && golangci-lint run ./...
	cd packages/go-common && golangci-lint run ./...
	cd packages/go-rpc && golangci-lint run ./...
	@echo "=== Python lint ==="
	cd packages/python-aaa && ruff check src/ tests/ && ruff format --check src/ tests/
	cd packages/python-utils && ruff check src/ tests/ && ruff format --check src/ tests/
	cd packages/python-rpc && ruff check src/ tests/ && ruff format --check src/ tests/
	@echo "=== React lint ==="
	cd packages/react-aaa && npm run lint
	cd packages/react-libs && npm run lint
	@echo "=== Rust lint ==="
	cd packages/rust-rpc && cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check
	@echo "=== Containers/shell lint ==="
	@if command -v hadolint >/dev/null 2>&1; then find . -name "Dockerfile*" -not -path "*/.git/*" -not -path "*/node_modules/*" | xargs -r hadolint; fi
	@if command -v shellcheck >/dev/null 2>&1; then find . -name "*.sh" -not -path "*/.git/*" -not -path "*/node_modules/*" | xargs -r shellcheck; fi

test: ## Run tests on all packages
	@echo "=== Go tests ==="
	cd packages/go-common && go test -race -v ./...
	cd packages/go-aaa && go test -race -v ./...
	cd packages/go-rpc && go test -race -v ./...
	@echo "=== Python tests ==="
	cd packages/python-aaa && pytest tests/ -v --tb=short
	cd packages/python-utils && pytest tests/ -v --tb=short
	cd packages/python-rpc && pytest tests/ -v --tb=short
	cd packages/python-email && pytest tests/ -v --tb=short
	cd packages/python-limiter && pytest tests/ -v --tb=short
	@echo "=== React tests ==="
	cd packages/react-aaa && npm test
	cd packages/react-libs && npm test
	@echo "=== Rust tests ==="
	cd packages/rust-rpc && cargo test --workspace

test-security: ## Run security scans on all packages
	@echo "=== Go security ==="
	cd packages/go-aaa && govulncheck ./... && gosec -quiet ./...
	cd packages/go-common && govulncheck ./... && gosec -quiet ./...
	cd packages/go-rpc && govulncheck ./... && gosec -quiet ./...
	@echo "=== Python security ==="
	cd packages/python-aaa && bandit -r src/ -c pyproject.toml
	cd packages/python-utils && bandit -r src/ -c pyproject.toml
	cd packages/python-rpc && bandit -r src/ -c pyproject.toml
	@echo "=== React security ==="
	cd packages/react-aaa && npm audit --omit=dev
	@echo "=== Rust security ==="
	cd packages/rust-rpc && cargo audit && cargo deny check

prpc-proto: ## Lint, breaking-check, and format-check proto definitions
	cd proto && buf lint && buf breaking --against '../.git#branch=main,subdir=proto' && buf format --diff --exit-code

prpc-generate: ## Regenerate Go stubs for prpc/* protos into packages/go-rpc/gen
	cd proto && buf generate --path prpc
	rm -rf gen/go/prpc packages/python-libs/src/penguin_libs/gen/prpc
	find gen -depth -type d -empty -delete 2>/dev/null || true
	find packages/python-libs/src/penguin_libs/gen -depth -type d -empty -delete 2>/dev/null || true
	cd packages/go-rpc && GOTOOLCHAIN=local go mod tidy

prpc-generate-check: prpc-generate ## CI drift gate: fail if checked-in go-rpc stubs are stale
	git add -N packages/go-rpc/gen/
	git diff --exit-code packages/go-rpc/gen/

prpc-integration: ## Run cross-lane integration tests for go-rpc (real sockets, build tag: integration)
	cd packages/go-rpc && go test -race -tags=integration ./integration/...

security: test-security ## Alias for test-security

pre-commit: build lint security test ## Run full pre-commit gate
	@echo "=== All checks passed ==="

install-tools: ## Install Go development tools
	go install github.com/golangci/golangci-lint/cmd/golangci-lint@v1.61.0
	go install golang.org/x/vuln/cmd/govulncheck@v1.1.3
	go install github.com/securego/gosec/v2/cmd/gosec@v2.21.0

install-hooks: ## Install git pre-commit hook
	@./scripts/install-hooks.sh

# === Kubernetes Deployment (microk8s + Helm v3) ===
PROJECT_NAME := $(shell basename $(CURDIR))
HELM_DIR := k8s/helm/$(PROJECT_NAME)

.PHONY: k8s-alpha-deploy k8s-beta-deploy k8s-prod-deploy k8s-alpha-test k8s-beta-test k8s-cleanup helm-lint helm-template-alpha helm-template-beta

k8s-alpha-deploy:
	@./tests/k8s/alpha/run-all-alpha.sh

k8s-beta-deploy:
	@./tests/k8s/beta/run-all-beta.sh

k8s-prod-deploy:
	@read -p "Deploy to PRODUCTION? (yes/NO): " c && [ "$$c" = "yes" ]
	@helm upgrade --install $(PROJECT_NAME) ./$(HELM_DIR) --namespace $(PROJECT_NAME) --create-namespace --kube-context $(PROJECT_NAME)-prod --values ./$(HELM_DIR)/values.yaml --values ./$(HELM_DIR)/production.yml --wait --timeout 10m

k8s-alpha-test:
	@./tests/k8s/alpha/run-all-alpha.sh

k8s-beta-test:
	@./tests/k8s/beta/run-all-beta.sh

k8s-cleanup:
	@helm uninstall $(PROJECT_NAME) -n $(PROJECT_NAME) 2>/dev/null || true
	@microk8s kubectl delete namespace $(PROJECT_NAME) 2>/dev/null || true

helm-lint:
	@helm lint ./$(HELM_DIR)

helm-template-alpha:
	@helm template $(PROJECT_NAME) ./$(HELM_DIR) --values ./$(HELM_DIR)/values.yaml --values ./$(HELM_DIR)/alpha.yml

helm-template-beta:
	@helm template $(PROJECT_NAME) ./$(HELM_DIR) --values ./$(HELM_DIR)/values.yaml --values ./$(HELM_DIR)/beta.yml
