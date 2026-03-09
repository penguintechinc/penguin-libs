# Penguin Libraries

[![CI](https://github.com/penguintechinc/penguin-libs/actions/workflows/ci.yml/badge.svg)](https://github.com/penguintechinc/penguin-libs/actions/workflows/ci.yml)
[![Publish](https://github.com/penguintechinc/penguin-libs/actions/workflows/publish.yml/badge.svg)](https://github.com/penguintechinc/penguin-libs/actions/workflows/publish.yml)

Shared libraries for Penguin Tech applications across all languages.

## Packages

### JavaScript/TypeScript

| Package | Version | Description |
|---------|---------|-------------|
| [@penguintechinc/react-libs](./packages/react-libs) | 1.2.0 | React components (LoginPageBuilder, FormModalBuilder, SidebarMenu) |

### Python

| Package | Version | Coverage | Description |
|---------|---------|----------|-------------|
| [penguin-aaa](./packages/python-aaa) | 0.1.0 | 99% | Authentication, authorization, and audit (OIDC, RBAC, SPIFFE, tenant isolation) |
| [penguin-dal](./packages/python-dal) | 0.1.0 | 98% | Database access layer — PyDAL-style API over SQLAlchemy |
| [penguin-libs](./packages/python-libs) | 0.1.0 | 98% | H3 protocol, HTTP client, validation, Pydantic base models |
| [penguin-licensing](./packages/python-licensing) | 0.1.0 | 100% | PenguinTech License Server integration |
| [penguin-sal](./packages/python-secrets) | 0.1.0 | 100% | Secrets and authentication library |
| [penguin-utils](./packages/python-utils) | 0.1.0 | 99% | Sanitized logging and Flask utilities |

### Go

| Package | Version | Description |
|---------|---------|-------------|
| [go-common](./packages/go-common) | - | Common Go utilities and helpers |
| [go-h3](./packages/go-h3) | - | Go H3 protocol interceptors and middleware |

### Flutter/Dart

| Package | Version | Description |
|---------|---------|-------------|
| [flutter_libs](./packages/flutter_libs) | - | Flutter UI components and utilities |

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
git tag python-aaa-v0.1.0
git tag python-dal-v0.1.0
git tag python-libs-v0.1.0
git tag python-licensing-v0.1.0
git tag python-secrets-v0.1.0
git tag python-utils-v0.1.0
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

## Contributing

1. Create a feature branch
2. Make changes
3. Run tests and linting for affected packages
4. Ensure 90%+ test coverage on all Python packages
5. Submit a pull request

## License

AGPL-3.0 - See [LICENSE](./LICENSE) for details.

---

**Maintained by**: [Penguin Tech Inc](https://www.penguintech.io)
