# Penguin Libraries

[![CI](https://github.com/penguintechinc/penguin-libs/actions/workflows/ci.yml/badge.svg)](https://github.com/penguintechinc/penguin-libs/actions/workflows/ci.yml)
[![Publish](https://github.com/penguintechinc/penguin-libs/actions/workflows/publish.yml/badge.svg)](https://github.com/penguintechinc/penguin-libs/actions/workflows/publish.yml)

Shared libraries for Penguin Tech applications across all languages.

## Package Directory

### Python

| Package | Version | Coverage | Description |
|---------|---------|----------|-------------|
| [penguin-aaa](./packages/python-aaa) | 0.2.0 | 99% | Authentication, authorization, and audit (OIDC, RBAC, SPIFFE, tenant isolation) |
| [penguin-crypto](./packages/python-crypto) | 0.1.0 | — | Cryptographic primitives and key handling |
| [penguin-dal](./packages/python-dal) | 0.3.0 | 98% | Database access layer — PyDAL-style API over SQLAlchemy, plus storage/cache/stream/document backends |
| [penguin-email](./packages/python-email) | 0.1.0 | — | SMTP delivery helpers |
| [penguin-libs](./packages/python-libs) | 0.3.0 | 98% | Transition meta-package — re-exports the split packages |
| [penguin-licensing](./packages/python-licensing) | 0.1.0 | 100% | PenguinTech License Server integration |
| [penguin-limiter](./packages/python-limiter) | 0.1.0 | — | Rate limiting middleware (HTTP + gRPC) |
| [penguin-pytest](./packages/python-pytest) | 0.1.0 | — | Shared pytest fixtures and helpers |
| [penguin-sal](./packages/python-secrets) | 0.2.1 | 100% | Secrets and authentication library |
| [penguin-security](./packages/python-security) | 0.1.0 | — | Security primitives and hardening helpers |
| [penguin-utils](./packages/python-utils) | 0.2.0 | 99% | Sanitized logging and Flask utilities |
| [penguin-rpc](./packages/python-rpc) | 0.1.0 | 100% | pRPC — Connect RPC over HTTP/3/QUIC, Python implementation (Apache-2.0) |

### TypeScript / React

All published to **public npm** (npmjs.com) under the `@penguintechinc` scope.

| Package | Version | Description |
|---------|---------|-------------|
| [@penguintechinc/react-libs](./packages/react-libs) | 1.3.5 | Shared React components — transition package re-exporting the split packages |
| [@penguintechinc/react-aaa](./packages/react-aaa) | 0.1.5 | Auth context, OIDC client, token manager, protected routes |
| [@penguintechinc/react-testutils](./packages/react-testutils) | 0.1.3 | Test helpers and render utilities |
| [@penguintechinc/react-console-version](./packages/react-console-version) | 0.1.0 | Sanitized console version banner |
| [@penguintechinc/react-form-builder](./packages/react-form-builder) | 0.1.0 | Declarative form/modal builder |
| [@penguintechinc/react-hooks](./packages/react-hooks) | 0.1.0 | Shared React hooks |
| [@penguintechinc/react-login](./packages/react-login) | 0.1.0 | Login page builder (SSO buttons, MFA, WebAuthn) |
| [@penguintechinc/react-sidebar](./packages/react-sidebar) | 0.1.0 | Collapsible sidebar navigation |

### Go

| Package | Version | Description |
|---------|---------|-------------|
| [go-aaa](./packages/go-aaa) | - | Authentication, authorization, audit (OIDC RP, PKCE, SPIFFE) |
| [go-common](./packages/go-common) | - | Common Go utilities and helpers (transition) |
| [go-dal](./packages/go-dal) | - | Database/storage/cache/stream/document access layer |
| [go-h3](./packages/go-h3) | - | Go H3 protocol interceptors and middleware |
| [go-logging](./packages/go-logging) | - | Sanitized structured logging and sinks |
| [go-numa](./packages/go-numa) | - | NUMA-aware buffer pools and aligned allocation |
| [go-xdp](./packages/go-xdp) | - | XDP / AF_XDP networking helpers |
| [go-rpc](./packages/go-rpc) | 0.1.0 | pRPC — Connect RPC over HTTP/3/QUIC, Go implementation (Apache-2.0) |

### Rust

| Package | Version | Description |
|---------|---------|-------------|
| [penguin-rpc](./packages/rust-rpc/crates/penguin-rpc) | 0.1.0 | pRPC — Connect RPC over HTTP/3/QUIC, Rust implementation (Apache-2.0) |
| [penguin-h3-tower](./packages/rust-rpc/crates/penguin-h3-tower) | 0.1.0 | HTTP/3 bridge for Tower services, used by penguin-rpc (Apache-2.0) |
| [penguin-licensing](./packages/rust-licensing) | 0.1.0 | License entitlement + PostHog feature-flag client |

### Flutter/Dart

| Package | Version | Install |
|---------|---------|---------|
| `flutter_libs` | [![pub](https://img.shields.io/pub/v/flutter_libs)](https://pub.dev/packages/flutter_libs) | Add to `pubspec.yaml` (see Installation) |

**Note**: `penguin-email` and `penguin-limiter` are standalone packages for SMTP and API rate limiting respectively. They are not bundled in the transition `penguin-libs` package — install them directly.

## Installation

### JavaScript/TypeScript Packages

Configure npm to use GitHub Packages for the `@penguintechinc` scope:

```bash
# Create or edit ~/.npmrc
echo "@penguintechinc:registry=https://npm.pkg.github.com" >> ~/.npmrc
```

For CI/CD, set `NODE_AUTH_TOKEN` environment variable with a GitHub token that has `read:packages` permission.

```bash
# Install React components
npm install @penguintechinc/react-libs

# Or with yarn
yarn add @penguintechinc/react-libs
```

### Python Packages

All Python packages are published to PyPI:

```bash
# Install all Python libraries
pip install penguin-aaa penguin-dal penguin-libs penguin-licensing penguin-sal penguin-utils

# Or install specific packages
pip install penguin-aaa               # Authentication, authorization, audit
pip install penguin-dal               # Database access layer (SQLAlchemy wrapper)
pip install penguin-libs              # H3 client, validation, Pydantic models
pip install penguin-licensing         # License server integration
pip install penguin-sal               # Secrets management
pip install penguin-utils             # Logging and Flask utilities
```

### Go Packages

Go packages are consumed directly from the repository:

```bash
# Install Go packages
go get github.com/penguintechinc/penguin-libs/packages/go-common
go get github.com/penguintechinc/penguin-libs/packages/go-h3
```

### Flutter/Dart Packages

Add to your `pubspec.yaml`:

```yaml
dependencies:
  flutter_libs:
    git:
      url: https://github.com/penguintechinc/penguin-libs.git
      path: packages/flutter_libs
```

## Usage

### React Libraries

```tsx
import {
  LoginPageBuilder,
  FormModalBuilder,
  SidebarMenu,
  AppConsoleVersion
} from '@penguintechinc/react-libs';

// Login page with MFA, CAPTCHA, and social login
<LoginPageBuilder
  api={{ loginUrl: '/api/v1/auth/login' }}
  branding={{ appName: 'My App', githubRepo: 'penguintechinc/my-app' }}
  onSuccess={(response) => { /* handle success */ }}
  gdpr={{ enabled: true, privacyPolicyUrl: '/privacy' }}
  mfa={{ enabled: true }}
  captcha={{ enabled: true, provider: 'altcha', challengeUrl: '/api/v1/captcha/challenge' }}
/>

// Form modal with validation
<FormModalBuilder
  title="Create User"
  isOpen={isOpen}
  onClose={() => setIsOpen(false)}
  onSubmit={handleSubmit}
  fields={[
    { name: 'email', type: 'email', label: 'Email', required: true },
    { name: 'role', type: 'select', label: 'Role', options: [...] },
  ]}
/>
```

See [packages/react-libs/README.md](./packages/react-libs/README.md) for full documentation.

## Development

### Setup

```bash
git clone https://github.com/penguintechinc/penguin-libs.git
cd penguin-libs

# JavaScript/TypeScript
npm install

# Python (create venv and install all packages in dev mode)
python3 -m venv .venv && source .venv/bin/activate
pip install -e packages/python-aaa[dev] \
            -e packages/python-dal[dev] \
            -e packages/python-libs[dev] \
            -e packages/python-licensing[dev] \
            -e packages/python-secrets[dev] \
            -e packages/python-utils[dev]
```

### Build

```bash
# JavaScript/TypeScript
npm run build

# Python packages are pure Python — no build step needed for development
```

### Running Tests

```bash
# All Python packages (from repo root, with venv active)
for pkg in packages/python-*/; do
  (cd "$pkg" && python3 -m pytest tests/ -q)
done

# Single package
cd packages/python-dal && python3 -m pytest tests/ --cov -q

# JavaScript/TypeScript
npm test
```

### Publishing

Publishing is automated via GitHub Actions on version tags:

```bash
# Tag format: {package}-v{version}
git tag react-libs-v1.2.0
git tag penguin-aaa-v0.1.0
git tag penguin-dal-v0.1.0
git tag penguin-libs-v0.1.0
git tag penguin-licensing-v0.1.0
git tag penguin-secrets-v0.1.0
git tag penguin-utils-v0.1.0
git tag flutter-libs-v0.1.0

# Push tags to trigger publishing
git push origin --tags
```

Publishing uses OIDC trusted publishing on PyPI — no API tokens needed. Each Python package has its own PyPI environment configured in the `publish.yml` workflow.

## Repository Structure

```
penguin-libs/
├── packages/
│   ├── react-libs/          # @penguintechinc/react-libs (GitHub Packages)
│   ├── python-aaa/          # penguin-aaa (PyPI) — authn, authz, audit
│   ├── python-dal/          # penguin-dal (PyPI) — database access layer
│   ├── python-libs/         # penguin-libs (PyPI) — H3, validation, Pydantic
│   ├── python-licensing/    # penguin-licensing (PyPI)
│   ├── python-secrets/      # penguin-sal (PyPI)
│   ├── python-utils/        # penguin-utils (PyPI)
│   ├── go-common/           # Go module (via go get)
│   ├── go-h3/               # Go module (via go get)
│   └── flutter_libs/        # Flutter package (pub.dev)
├── .github/
│   └── workflows/
│       ├── ci.yml           # Continuous integration (tests, lint)
│       └── publish.yml      # Automated publishing on tags
├── proto/                   # Protocol buffer definitions
├── scripts/                 # Build and utility scripts
├── docs/                    # Documentation
├── package.json             # Workspace root
└── README.md
```

## Sunset Packages

**penguin-http** (removed Aug 2026): Never published to PyPI; replaced by domain-specific HTTP packages. Compatibility shim in `penguin-libs._compat` removed.

## Contributing

1. Create a feature branch
2. Make changes
3. Run tests and linting for affected packages
4. Ensure 90%+ test coverage on all Python packages
5. Submit a pull request

## License

MIT - See [LICENSE](./LICENSE) for details.

---

**Maintained by**: [Penguin Tech Inc](https://www.penguintech.io)
