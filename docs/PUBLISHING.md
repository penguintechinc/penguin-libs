# Publishing Guide

This document describes the publishing process for all packages in the penguin-libs monorepo.

## Overview

All packages are published automatically via GitHub Actions when version tags are pushed. The workflow supports both individual package publishing and batch publishing.

## Package Publishing Matrix

| Package | Registry | Package Name | Trigger Tag | Status |
|---------|----------|--------------|-------------|--------|
| react-libs | GitHub Packages (npm) | @penguintechinc/react-libs | `react-libs-v*` | ✅ Active |
| python-libs | PyPI | penguin-libs | `python-libs-v*` | ✅ Active |
| python-licensing | PyPI | penguin-licensing | `python-licensing-v*` | ✅ Active |
| python-secrets | PyPI | penguin-sal | `python-secrets-v*` | ✅ Active |
| python-utils | PyPI | penguin-utils | `python-utils-v*` | ✅ Active |
| go-common | GitHub (go get) | github.com/penguintechinc/penguin-libs/packages/go-common | `v*` (validation only) | ✅ Active |
| go-h3 | GitHub (go get) | github.com/penguintechinc/penguin-libs/packages/go-h3 | `v*` (validation only) | ✅ Active |
| flutter_libs | pub.dev | flutter_libs | `flutter-libs-v*` | ⚠️ Dry-run only |

## Publishing Methods

### Automated Publishing (Recommended)

#### 1. Publishing Individual Packages

```bash
# Update version in package metadata
cd packages/python-utils
# Edit pyproject.toml or package.json to bump version

# Commit version change
git add .
git commit -m "chore: Bump python-utils to v0.1.1"

# Create and push tag
git tag python-utils-v0.1.1
git push origin python-utils-v0.1.1
```

#### 2. Publishing All Packages

Use a general `v*` tag to publish all packages at once:

```bash
# Ensure all package versions are updated
git tag v1.2.0
git push origin v1.2.0
```

This will trigger publishing for ALL packages that support it.

#### 3. Manual Trigger via GitHub UI

Navigate to: **Actions → Publish Packages → Run workflow**

Select the package to publish from the dropdown menu.

## Package-Specific Instructions

### JavaScript/TypeScript (react-libs)

**Registry**: GitHub Packages
**Authentication**: Uses `GITHUB_TOKEN` (automatic)

```bash
cd packages/react-libs

# Bump version using npm
npm version patch  # or minor, major

# This updates package.json and creates a git commit + tag
# Push the changes and tag
git push origin main --follow-tags

# Or manually tag
git tag react-libs-v1.1.1
git push origin react-libs-v1.1.1
```

**Workflow steps:**
1. Setup Node.js 20
2. Install dependencies
3. Build package
4. Run type check
5. Publish to GitHub Packages

### Python Packages

**Registry**: PyPI
**Authentication**: OIDC trusted publishing (no tokens needed)

All Python packages follow the same process:

```bash
cd packages/python-libs  # or python-licensing, python-secrets, python-utils

# Update version in pyproject.toml
vim pyproject.toml  # Change version = "X.Y.Z"

# Commit and tag
git add pyproject.toml
git commit -m "chore: Bump python-libs to vX.Y.Z"
git tag python-libs-vX.Y.Z
git push origin python-libs-vX.Y.Z
```

**Workflow steps:**
1. Setup Python 3.13
2. Install build tools (build, twine)
3. Build package with `python -m build`
4. Check package with `twine check`
5. Publish to PyPI using OIDC

**PyPI Package Names:**
- `packages/python-libs` → `penguin-libs`
- `packages/python-licensing` → `penguin-licensing`
- `packages/python-secrets` → `penguin-sal`
- `packages/python-utils` → `penguin-utils`

### Go Packages

**Registry**: GitHub (direct import)
**Authentication**: None required

Go packages don't need separate publishing - they're consumed via `go get` directly from the repository.

```bash
# Update version (optional, uses git tags)
git tag go-common-v1.2.3
git push origin go-common-v1.2.3

# Or use general versioning
git tag v1.2.3
git push origin v1.2.3
```

**Workflow steps:**
1. Setup Go 1.24
2. Download dependencies
3. Verify dependencies
4. Build with `go build ./...`
5. Run tests with `go test ./...`

**Usage by consumers:**
```bash
go get github.com/penguintechinc/penguin-libs/packages/go-common@v1.2.3
go get github.com/penguintechinc/penguin-libs/packages/go-h3@v1.2.3
```

### Flutter Packages

**Registry**: pub.dev (dry-run mode)
**Authentication**: Not configured yet

Currently runs in dry-run mode only. To enable full publishing:

1. Set up pub.dev credentials in GitHub Secrets
2. Add credentials to workflow
3. Remove `--dry-run` flag from publish step

```bash
cd packages/flutter_libs

# Update version in pubspec.yaml
vim pubspec.yaml  # Change version: X.Y.Z

# Commit and tag
git add pubspec.yaml
git commit -m "chore: Bump flutter_libs to vX.Y.Z"
git tag flutter-libs-vX.Y.Z
git push origin flutter-libs-vX.Y.Z
```

**Workflow steps:**
1. Setup Flutter 3.24.x
2. Install dependencies with `flutter pub get`
3. Run analyzer with `flutter analyze`
4. Run tests with `flutter test`
5. Dry-run publish with `dart pub publish --dry-run`

## Troubleshooting

### Failed Python Publishing

**Issue**: PyPI publishing fails with authentication error

**Solution**: Ensure the repository is configured as a trusted publisher on PyPI:

1. Go to PyPI project settings
2. Add GitHub Actions as trusted publisher
3. Specify: `penguintechinc/penguin-libs` repository and workflow file

### Failed npm Publishing

**Issue**: GitHub Packages publishing fails

**Solution**: Verify that:
- Package name is scoped: `@penguintechinc/react-libs`
- `publishConfig` in package.json points to GitHub Packages
- Workflow has `packages: write` permission

### Go Module Not Found

**Issue**: `go get` fails to find module

**Solution**:
- Ensure tags are pushed to GitHub
- Wait a few minutes for Go proxy to update
- Try with `GOPROXY=direct go get ...`

### Version Conflicts

**Issue**: Version tag already exists

**Solution**:
```bash
# Delete local tag
git tag -d python-libs-v1.0.0

# Delete remote tag (use with caution!)
git push origin :refs/tags/python-libs-v1.0.0

# Create new tag with correct version
git tag python-libs-v1.0.1
git push origin python-libs-v1.0.1
```

## Release Checklist

Before publishing a new version:

- [ ] Update version in package metadata (pyproject.toml, package.json, pubspec.yaml)
- [ ] Update CHANGELOG.md in package directory
- [ ] Run tests locally: `npm test`, `pytest`, `go test`, `flutter test`
- [ ] Run linting: `npm run lint`, `ruff check`, `flutter analyze`
- [ ] Verify builds locally: `npm run build`, `python -m build`, `go build`
- [ ] Update README.md if API changes
- [ ] Commit all changes
- [ ] Create and push version tag
- [ ] Monitor GitHub Actions workflow
- [ ] Verify package is published to registry
- [ ] Test installation in a clean environment

## Best Practices

1. **Use semantic versioning**: MAJOR.MINOR.PATCH
   - MAJOR: Breaking changes
   - MINOR: New features (backwards compatible)
   - PATCH: Bug fixes

2. **Always test before publishing**: Run full test suite locally

3. **Use descriptive commit messages**:
   - `feat: Add new authentication middleware`
   - `fix: Resolve race condition in logger`
   - `chore: Bump version to v1.2.3`

4. **Document breaking changes**: Update CHANGELOG.md with migration guide

5. **Tag consistently**: Use `{package}-v{version}` format

6. **Monitor workflows**: Check GitHub Actions after pushing tags

7. **Verify published packages**: Install and test from registry after publishing

## Support

For publishing issues:
- Check GitHub Actions logs: https://github.com/penguintechinc/penguin-libs/actions
- Review workflow file: `.github/workflows/publish.yml`
- Contact: dev@penguintech.io
