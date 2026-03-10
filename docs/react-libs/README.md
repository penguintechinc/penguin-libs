# react-libs

Shared React component library for Penguin Tech Inc applications. Provides pre-built, production-ready components with consistent Elder-style dark theming (slate backgrounds, amber/gold accents).

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
| `LoginPageBuilder` | Complete login page with GDPR, CAPTCHA, MFA, social login, passkey |
| `SidebarMenu` | Elder-style collapsible navigation sidebar |
| `FormModalBuilder` | Modal dialog with typed form fields and validation |
| `AppConsoleVersion` | Logs app + API versions to browser console on startup |

## Quick Start

### LoginPageBuilder

```tsx
import { LoginPageBuilder } from '@penguintechinc/react-libs';

<LoginPageBuilder
  api={{ loginUrl: '/api/v1/auth/login' }}
  branding={{ appName: 'My App', logo: '/logo.png' }}
  onSuccess={(response) => {
    localStorage.setItem('token', response.token);
    navigate('/dashboard');
  }}
  gdpr={{ enabled: true, privacyPolicyUrl: '/privacy' }}
  passkey={{
    enabled: true,
    authenticationUrl: '/api/v1/auth/passkey/authenticate',
    registrationUrl: '/api/v1/auth/passkey/register',
  }}
/>
```

### SidebarMenu

```tsx
import { SidebarMenu } from '@penguintechinc/react-libs';

<SidebarMenu
  categories={[
    {
      header: 'Main',
      items: [
        { name: 'Dashboard', href: '/dashboard', icon: HomeIcon },
        { name: 'Users', href: '/users', icon: UsersIcon },
      ],
    },
  ]}
  currentPath={location.pathname}
  onNavigate={(href) => navigate(href)}
/>
```

📚 Full documentation: [docs/react-libs/](../../docs/react-libs/)
