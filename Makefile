# === Development Targets ===

.PHONY: lint test test-security security build pre-commit install-tools install-hooks

build: ## Build/compile all packages
	@echo "=== Building Go packages ==="
	cd packages/go-common && go build ./...
	cd packages/go-aaa && go build ./...
	@echo "=== Building Python packages ==="
	cd packages/python-aaa && python -m py_compile src/penguin_aaa/__init__.py
	cd packages/python-utils && python -m py_compile src/penguintechinc_utils/__init__.py
	@echo "=== Building React packages ==="
	cd packages/react-aaa && npm run build
	cd packages/react-libs && npm run build

lint: ## Run linters on all packages
	@echo "=== Go lint ==="
	cd packages/go-aaa && golangci-lint run ./...
	cd packages/go-common && golangci-lint run ./...
	@echo "=== Python lint ==="
	cd packages/python-aaa && ruff check src/ tests/ && ruff format --check src/ tests/
	cd packages/python-utils && ruff check src/ tests/ && ruff format --check src/ tests/
	@echo "=== React lint ==="
	cd packages/react-aaa && npm run lint
	cd packages/react-libs && npm run lint

test: ## Run tests on all packages
	@echo "=== Go tests ==="
	cd packages/go-common && go test -race -v ./...
	cd packages/go-aaa && go test -race -v ./...
	@echo "=== Python tests ==="
	cd packages/python-aaa && pytest tests/ -v --tb=short
	cd packages/python-utils && pytest tests/ -v --tb=short
	@echo "=== React tests ==="
	cd packages/react-aaa && npm test
	cd packages/react-libs && npm test

test-security: ## Run security scans on all packages
	@echo "=== Go security ==="
	cd packages/go-aaa && govulncheck ./... && gosec -quiet ./...
	cd packages/go-common && govulncheck ./... && gosec -quiet ./...
	@echo "=== Python security ==="
	cd packages/python-aaa && bandit -r src/ -c pyproject.toml
	cd packages/python-utils && bandit -r src/ -c pyproject.toml
	@echo "=== React security ==="
	cd packages/react-aaa && npm audit --omit=dev

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
