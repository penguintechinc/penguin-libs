# Penguin Libraries

[![CI](https://github.com/penguintechinc/penguin-libs/actions/workflows/ci.yml/badge.svg)](https://github.com/penguintechinc/penguin-libs/actions/workflows/ci.yml)
[![Publish](https://github.com/penguintechinc/penguin-libs/actions/workflows/publish.yml/badge.svg)](https://github.com/penguintechinc/penguin-libs/actions/workflows/publish.yml)

Shared libraries for Penguin Tech applications across all languages.

## Package Directory

| Package | Language | Registry | Install |
|---------|----------|----------|---------|
| `penguin-libs` | Python | PyPI | `pip install penguin-libs` (transition) |
| `penguin-crypto` | Python | PyPI | `pip install penguin-crypto` |
| `penguin-flask` | Python | PyPI | `pip install penguin-flask` |
| `penguin-grpc` | Python | PyPI | `pip install penguin-grpc` |
| `penguin-h3` | Python | PyPI | `pip install penguin-h3` |
| `penguin-http` | Python | PyPI | `pip install penguin-http` |
| `penguin-pydantic` | Python | PyPI | `pip install penguin-pydantic` |
| `penguin-security` | Python | PyPI | `pip install penguin-security` |
| `penguin-validation` | Python | PyPI | `pip install penguin-validation` |
| `penguin-aaa` | Python | PyPI | `pip install penguin-aaa` |
| `penguin-dal` | Python | PyPI | `pip install penguin-dal` |
| `penguin-email` | Python | PyPI | `pip install penguin-email` (SMTP) |
| `penguin-limiter` | Python | PyPI | `pip install penguin-limiter` (rate limiting) |
| `penguin-licensing` | Python | PyPI | `pip install penguin-licensing` |
| `penguin-sal` | Python | PyPI | `pip install penguin-sal` (secrets) |
| `penguin-utils` | Python | PyPI | `pip install penguin-utils` |
| `penguin-pytest` | Python | PyPI | `pip install penguin-pytest` |
| `@penguintechinc/react-libs` | TypeScript | npm | `npm i @penguintechinc/react-libs` (transition) |
| `@penguintechinc/react-form-builder` | TypeScript | npm | `npm i @penguintechinc/react-form-builder` |
| `@penguintechinc/react-login` | TypeScript | npm | `npm i @penguintechinc/react-login` |
| `@penguintechinc/react-sidebar` | TypeScript | npm | `npm i @penguintechinc/react-sidebar` |
| `@penguintechinc/react-console-version` | TypeScript | npm | `npm i @penguintechinc/react-console-version` |
| `@penguintechinc/react-hooks` | TypeScript | npm | `npm i @penguintechinc/react-hooks` |
| `@penguintechinc/react-aaa` | TypeScript | npm | `npm i @penguintechinc/react-aaa` |
| `@penguintechinc/react-testutils` | TypeScript | npm | `npm i @penguintechinc/react-testutils` |
| `go-logging` | Go | go get | `go get github.com/penguintechinc/penguin-libs/packages/go-logging` |
| `go-common` | Go | go get | `go get ...go-common` (transition) |
| `go-xdp` | Go | go get | `go get ...go-xdp` |
| `go-numa` | Go | go get | `go get ...go-numa` |
| `go-h3` | Go | go get | `go get ...go-h3` |
| `go-aaa` | Go | go get | `go get ...go-aaa` |
| `flutter_libs` | Dart | git | See pubspec.yaml |

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
