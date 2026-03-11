# @penguintechinc/react-libs

Shared React component library for Penguin Tech Inc applications. Elder dark theme (slate + amber/gold) out of the box.

## Installation

```bash
npm install @penguintechinc/react-libs
```

**GitHub Packages auth required** — add to `.npmrc`:
```
@penguintechinc:registry=https://npm.pkg.github.com
```

## Components

| Component | Description |
|-----------|-------------|
| `LoginPageBuilder` | Complete login page — GDPR, CAPTCHA, MFA, social login, WebAuthn passkey |
| `SidebarMenu` | Elder-style collapsible navigation sidebar |
| `FormModalBuilder` | Modal dialog with typed form fields, tabs, and validation |
| `AppConsoleVersion` | Logs app + API versions to browser console on startup |

## Quick Start

```tsx
import { LoginPageBuilder, SidebarMenu, FormModalBuilder } from '@penguintechinc/react-libs';

// Login page with passkey support
<LoginPageBuilder
  api={{ loginUrl: '/api/v1/auth/login' }}
  branding={{ appName: 'My App', logo: '/logo.png' }}
  onSuccess={(r) => { localStorage.setItem('token', r.token); navigate('/dashboard'); }}
  gdpr={{ enabled: true, privacyPolicyUrl: '/privacy' }}
  passkey={{
    enabled: true,
    authenticationUrl: '/api/v1/auth/passkey/authenticate',
    registrationUrl: '/api/v1/auth/passkey/register',
  }}
/>

// Sidebar navigation
<SidebarMenu
  categories={[{ header: 'Main', items: [{ name: 'Dashboard', href: '/dashboard', icon: HomeIcon }] }]}
  currentPath={location.pathname}
  onNavigate={(href) => navigate(href)}
/>
```

📚 **Full documentation**: [docs/react-libs/](../../docs/react-libs/)
- [README](../../docs/react-libs/README.md) — complete component overview
- [API Reference](../../docs/react-libs/API.md) — all props and types
- [Changelog](../../docs/react-libs/CHANGELOG.md)
- [Migration Guide](../../docs/react-libs/MIGRATION.md) — adding passkey support (1.3.x)

## License

AGPL-3.0 — Penguin Tech Inc
