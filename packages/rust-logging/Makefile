# All targets run inside the pinned Dockerfile.ci image — never host cargo.
IMAGE := penguin-logging-ci:1.97.1
DOCKER_RUN := docker run --rm -v "$(CURDIR):/workspace" -w /workspace $(IMAGE)

.PHONY: ci-image fmt lint deny audit test coverage build pre-commit clean

ci-image:
	docker build -f Dockerfile.ci -t $(IMAGE) .

fmt: ci-image
	$(DOCKER_RUN) cargo fmt --all --check

lint: ci-image
	$(DOCKER_RUN) cargo clippy --all-targets --all-features -- -D warnings

deny: ci-image
	$(DOCKER_RUN) cargo deny check

audit: ci-image
	$(DOCKER_RUN) cargo audit

test: ci-image
	$(DOCKER_RUN) cargo test --all-features

coverage: ci-image
	$(DOCKER_RUN) cargo llvm-cov --all-features --fail-under-lines 90

build: ci-image
	$(DOCKER_RUN) cargo build --all-features

pre-commit: fmt lint deny audit test coverage
	@echo "penguin-logging pre-commit: all gates passed"

clean: ci-image
	$(DOCKER_RUN) cargo clean
	-docker rmi $(IMAGE)
