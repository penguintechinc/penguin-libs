# Package Publishing Status

**Date**: 2026-02-07
**Status**: ✅ All packages configured for publishing

## Summary

All 8 packages in the penguin-libs monorepo are now properly configured for automated publishing via GitHub Actions.

## Package Publishing Configuration

| # | Package | Registry | Package Name | Tag Trigger | Workflow Job | Status |
|---|---------|----------|--------------|-------------|--------------|--------|
| 1 | react-libs | GitHub Packages (npm) | @penguintechinc/react-libs | `react-libs-v*` | `publish-react-libs` | ✅ Configured |
| 2 | python-libs | PyPI | penguin-libs | `python-libs-v*` | `publish-python-libs` | ✅ Configured |
| 3 | python-licensing | PyPI | penguin-licensing | `python-licensing-v*` | `publish-python-licensing` | ✅ Configured |
| 4 | python-secrets | PyPI | penguin-sal | `python-secrets-v*` | `publish-python-secrets` | ✅ Configured |
| 5 | python-utils | PyPI | penguintechinc-utils | `python-utils-v*` | `publish-python-utils` | ✅ **NEWLY ADDED** |
| 6 | go-common | GitHub (go get) | github.com/.../go-common | `v*` | `validate-go-common` | ✅ Configured |
| 7 | go-h3 | GitHub (go get) | github.com/.../go-h3 | `v*` | `validate-go-common` | ✅ Configured |
| 8 | flutter_libs | pub.dev | flutter_libs | `flutter-libs-v*` | `publish-flutter-libs` | ✅ Configured (dry-run) |

## Changes Made

### 1. Updated `.github/workflows/publish.yml`

**Added python-utils tag trigger:**
```yaml
on:
  push:
    tags:
      - 'python-utils-v*'  # NEW
```

**Added python-utils to workflow dispatch options:**
```yaml
workflow_dispatch:
  inputs:
    package:
      options:
        - python-utils  # NEW
```

**Added publish-python-utils job:**
- Job name: `publish-python-utils`
- Trigger: `python-utils-v*` tags or workflow dispatch
- Working directory: `packages/python-utils`
- Python version: 3.13
- Registry: PyPI
- Package name: `penguintechinc-utils`
- Publishing method: OIDC trusted publishing

### 2. Updated `README.md`

**Updated package table** to show all 8 packages with accurate status:
- Removed "(Future)" and "coming soon" labels
- Added all Python packages with proper names
- Added Go and Flutter packages

**Added installation instructions** for all package types:
- Python packages from PyPI
- Go packages via `go get`
- Flutter packages via git dependency

**Updated publishing section** with comprehensive instructions:
- Tag format for all packages
- Manual publishing commands for each package type
- Batch publishing using `v*` tags

**Updated repository structure** to show all packages

### 3. Created `docs/PUBLISHING.md`

Comprehensive publishing guide covering:
- Package publishing matrix
- Automated and manual publishing methods
- Package-specific instructions for each language
- Troubleshooting common issues
- Release checklist
- Best practices

## Publishing Methods

### Individual Package Publishing

```bash
# Example: Publishing python-utils
cd packages/python-utils
# Update version in pyproject.toml
git add pyproject.toml
git commit -m "chore: Bump python-utils to v0.1.1"
git tag python-utils-v0.1.1
git push origin python-utils-v0.1.1
```

### Batch Publishing All Packages

```bash
# Update all package versions
git tag v1.2.0
git push origin v1.2.0
```

### Manual Workflow Trigger

GitHub UI: **Actions → Publish Packages → Run workflow → Select package**

## Registry Configuration

### PyPI (Python Packages)

- **Authentication**: OIDC trusted publishing
- **Permissions**: `id-token: write`
- **No secrets required**: GitHub Actions authenticates directly with PyPI
- **Publishing action**: `pypa/gh-action-pypi-publish@release/v1`

**Packages:**
- `penguin-libs` (python-libs)
- `penguin-licensing` (python-licensing)
- `penguin-sal` (python-secrets)
- `penguintechinc-utils` (python-utils) ← **NEWLY ADDED**

### GitHub Packages (npm)

- **Authentication**: `GITHUB_TOKEN` (automatic)
- **Scope**: `@penguintechinc`
- **Registry**: `https://npm.pkg.github.com`
- **Permissions**: `packages: write`

**Packages:**
- `@penguintechinc/react-libs`

### GitHub (Go Modules)

- **No publishing required**: Consumed via `go get` directly from repository
- **Workflow validates**: Tests and builds to ensure quality
- **Version tags**: Use semantic versioning (v1.2.3)

**Packages:**
- `github.com/penguintechinc/penguin-libs/packages/go-common`
- `github.com/penguintechinc/penguin-libs/packages/go-h3`

### pub.dev (Flutter)

- **Status**: Dry-run only (not yet published)
- **Requires**: pub.dev credentials configuration
- **Workflow ready**: Remove `--dry-run` flag when credentials are added

**Packages:**
- `flutter_libs`

## Verification

To verify the changes:

```bash
# Check workflow configuration
cat .github/workflows/publish.yml | grep python-utils

# Test workflow syntax
gh workflow view publish.yml

# List all tags
git tag -l '*-v*'

# Trigger workflow manually
gh workflow run publish.yml -f package=python-utils
```

## Next Steps

### For python-utils

1. **First publish**:
   ```bash
   cd packages/python-utils
   git tag python-utils-v0.1.0
   git push origin python-utils-v0.1.0
   ```

2. **Verify on PyPI**: https://pypi.org/project/penguintechinc-utils/

3. **Test installation**:
   ```bash
   pip install penguintechinc-utils
   ```

### For flutter_libs (Future)

1. Configure pub.dev credentials in GitHub Secrets
2. Update workflow to use credentials
3. Remove `--dry-run` flag
4. Publish first version

## Monitoring

- **GitHub Actions**: https://github.com/penguintechinc/penguin-libs/actions
- **Workflow file**: `.github/workflows/publish.yml`
- **PyPI packages**: https://pypi.org/user/penguintechinc/
- **GitHub Packages**: https://github.com/orgs/penguintechinc/packages

## Documentation

- **Publishing Guide**: [docs/PUBLISHING.md](./docs/PUBLISHING.md)
- **README**: [README.md](./README.md)
- **Workflow**: [.github/workflows/publish.yml](./.github/workflows/publish.yml)

---

**Status**: ✅ All packages ready for publishing
**Last Updated**: 2026-02-07
**Updated By**: Claude Code
