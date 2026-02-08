# penguin-libs (App-Specific Context)

This file contains project-specific context and patterns for the penguin-libs monorepo.

## Monorepo Structure

This is a multi-language monorepo containing shared libraries for:
- JavaScript/TypeScript (react-libs)
- Python (python-libs, python-licensing, python-secrets, python-utils)
- Go (go-common, go-h3)
- Flutter/Dart (flutter_libs)

## Version Management

### Independent Package Versioning

**IMPORTANT**: Each package in this monorepo has **independent versioning**. Never bump versions for all packages at once.

**Rules:**
1. **Only bump versions for packages with actual changes**
2. **Don't bump versions without functional updates**
3. **Each package follows semantic versioning independently**
4. **Version bumps should correspond to real code changes**

**Example (Correct):**
```bash
# Only react-libs had email validation changes
packages/react-libs: 1.1.0 → 1.1.1  ✅
packages/python-libs: 0.1.0 → 0.1.0  ✅ (no changes, no bump)
packages/go-common: stays same        ✅ (no changes, no bump)
```

**Example (Incorrect):**
```bash
# ❌ DON'T bump all packages when only one changed
packages/react-libs: 1.1.0 → 1.1.1
packages/python-libs: 0.1.0 → 0.1.1  ❌ (no changes, don't bump)
packages/go-common: → new version     ❌ (no changes, don't bump)
```

### When to Bump Versions

- **PATCH** (x.x.1): Bug fixes, security patches, minor improvements
- **MINOR** (x.1.x): New features, API additions (backwards compatible)
- **MAJOR** (1.x.x): Breaking changes, API removals

### Version Bump Process

1. Make changes to specific package(s)
2. Update version in that package's metadata file:
   - `package.json` for JavaScript/TypeScript
   - `pyproject.toml` for Python
   - `pubspec.yaml` for Flutter
   - Go uses git tags directly
3. Commit with descriptive message mentioning which package changed
4. Create tag if needed: `{package}-v{version}` or `v{version}` for multi-package releases

## Publishing Strategy

### Published Registries

| Package | Registry | Package Name | Status |
|---------|----------|--------------|--------|
| react-libs | GitHub Packages (npm) | @penguintechinc/react-libs | Active |
| python-libs | PyPI | penguin-libs | Planned |
| python-licensing | PyPI | penguin-licensing | Planned |
| python-secrets | PyPI | penguin-sal | Planned |
| python-utils | PyPI | penguintechinc-utils | Planned |
| go-common | GitHub (go get) | N/A - direct import | Active |
| go-h3 | GitHub (go get) | N/A - direct import | Active |
| flutter_libs | pub.dev | flutter_libs | Planned |

### Publishing Workflow

- **Automated**: GitHub Actions workflow (`.github/workflows/publish.yml`)
- **Trigger**: Push tags in format `{package}-v{version}` or `v{version}`
- **Authentication**:
  - npm: GitHub token (automatic)
  - PyPI: API token (stored in secrets)
  - Go: No publishing needed (direct import)
  - Flutter: pub.dev credentials (when configured)

## Development Practices

### Email Validation

**Special Requirement**: Email validation must support development TLDs.

Supported TLDs:
- `.local` - For local development (e.g., `user@localhost.local`)
- `.localhost` - RFC 6761 reserved
- `.test` - RFC 6761 reserved for testing
- `.example` - RFC 2606 reserved for documentation
- All standard TLDs

**Security**: Email regex is ReDoS-safe (no nested quantifiers, O(n) performance).

### Testing

All packages should have:
- Unit tests
- Integration tests (where applicable)
- Security tests (especially for validation logic)
- Performance tests for critical paths

## Package-Specific Notes

### react-libs
- Contains shared React components (LoginPageBuilder, FormModalBuilder, etc.)
- Uses TypeScript
- Published to GitHub Packages
- Requires scoped package configuration for consumers

### Python Packages
- All use Python 3.11+
- PyDAL for database abstraction where needed
- Follow PEP 8 style guidelines
- Use ruff and black for linting/formatting

### Go Packages
- Go 1.24+
- Connect RPC for HTTP/3 support
- Follow standard Go project layout
- Consumed directly via `go get`

## Historical Notes

### Version Corrections
- **2026-02-08**: Corrected improper mass version bump. Changed from bumping all packages to only bumping packages with actual changes (react-libs 1.1.0→1.1.1 for .local TLD support).
