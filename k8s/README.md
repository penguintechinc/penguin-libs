# Kubernetes

Helm is the only supported deployment method for this repository.

- **`k8s/helm/`** — the Helm charts that are actually deployed. Per-environment
  values live alongside each chart as `alpha.yml`, `beta.yml`, `gamma.yml`, and
  `production.yml`, layered on top of the chart's own `values.yaml` defaults.
- **`k8s/manifests/`** — reference material only. Nothing in this directory is
  deployed; do not apply it to a cluster.
- **Kustomize has been removed** per policy. Do not reintroduce `kustomization.yaml`
  files or a `k8s/kustomize/` directory.

Render a chart locally with `make helm-template-alpha` or `make helm-template-beta`.
