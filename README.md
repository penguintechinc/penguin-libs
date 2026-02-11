# Penguin Libraries

Shared libraries for Penguin Tech applications across all languages.

## Packages

### JavaScript/TypeScript

| Package | Version | Description |
|---------|---------|-------------|
| [@penguintechinc/react-libs](./packages/react-libs) | 1.1.0 | React components (LoginPageBuilder, FormModalBuilder, SidebarMenu) |

### Python

| Package | Version | Description |
|---------|---------|-------------|
| [penguin-libs](./packages/python-libs) | - | Python H3 client libraries (middleware, auth, logging) |
| [penguin-licensing](./packages/python-licensing) | - | PenguinTech License Server integration |
| [penguin-sal](./packages/python-secrets) | - | Secrets and authentication library |
| [penguin-utils](./packages/python-utils) | 0.1.0 | Sanitized logging and Flask utilities |

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
# Install Python libraries
pip install penguin-libs penguin-licensing penguin-sal penguin-utils

# Or install specific packages
pip install penguin-libs              # H3 client libraries
pip install penguin-licensing         # License server integration
pip install penguin-sal               # Secrets management
pip install penguin-utils      # Logging and Flask utilities
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
npm install
```

### Build All Packages

```bash
npm run build
```

### Build Specific Package

```bash
npm run build:react-libs
```

### Publishing

Publishing is automated via GitHub Actions on version tags:

```bash
# Tag format: {package}-v{version}
git tag react-libs-v1.1.0
git tag python-libs-v0.2.0
git tag python-licensing-v0.1.5
git tag python-secrets-v0.1.0
git tag python-utils-v0.1.1
git tag flutter-libs-v0.1.0

# Or use v* tag to publish all packages
git tag v1.0.0

# Push tags to trigger publishing
git push origin --tags
```

**Manual publishing (not recommended):**

```bash
# JavaScript/TypeScript
cd packages/react-libs
npm version patch && npm publish

# Python
cd packages/python-libs  # or python-licensing, python-secrets, python-utils
python -m build && twine upload dist/*

# Go (no publishing needed - use via go get)
# Flutter (requires pub.dev credentials)
cd packages/flutter_libs
dart pub publish
```

## Repository Structure

```
penguin-libs/
├── packages/
│   ├── react-libs/          # @penguintechinc/react-libs (GitHub Packages)
│   ├── python-libs/         # penguin-libs (PyPI)
│   ├── python-licensing/    # penguin-licensing (PyPI)
│   ├── python-secrets/      # penguin-sal (PyPI)
│   ├── python-utils/        # penguin-utils (PyPI)
│   ├── go-common/           # Go module (via go get)
│   ├── go-h3/               # Go module (via go get)
│   └── flutter_libs/        # Flutter package (pub.dev)
├── .github/
│   └── workflows/
│       └── publish.yml      # Automated publishing
├── proto/                   # Protocol buffer definitions
├── scripts/                 # Build and utility scripts
├── docs/                    # Documentation
├── package.json             # Workspace root
└── README.md
```

## Contributing

1. Create a feature branch
2. Make changes
3. Run `npm run build && npm run lint`
4. Submit a pull request

## License

AGPL-3.0 - See [LICENSE](./LICENSE) for details.

---

**Maintained by**: [Penguin Tech Inc](https://www.penguintech.io)
