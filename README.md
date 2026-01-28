# Penguin Libraries

Shared libraries for Penguin Tech applications across all languages.

## Packages

### JavaScript/TypeScript

| Package | Version | Description |
|---------|---------|-------------|
| [@penguintechinc/react-libs](./packages/react-libs) | 1.1.0 | React components (LoginPageBuilder, FormModalBuilder, SidebarMenu) |

### Python (Future)

| Package | Version | Description |
|---------|---------|-------------|
| `penguintechinc-utils` | - | Python utilities (coming soon) |

### Go (Future)

| Package | Version | Description |
|---------|---------|-------------|
| `github.com/penguintechinc/penguin-libs/go-common` | - | Go utilities (coming soon) |

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

Publishing is automated via GitHub Actions on version tags. To publish manually:

```bash
# Bump version
cd packages/react-libs
npm version patch  # or minor, major

# Publish (requires authentication)
npm publish
```

## Repository Structure

```
penguin-libs/
├── packages/
│   ├── react-libs/          # @penguintechinc/react-libs (npm)
│   ├── python-utils/        # penguintechinc-utils (PyPI) - future
│   └── go-common/           # Go module - future
├── .github/
│   └── workflows/
│       └── publish.yml      # Automated publishing
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
