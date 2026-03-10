# react-libs Migration Guide

## Migrating to 1.3.0

### Adding Passkey Support

No breaking changes. To enable passkey authentication, install the peer dependency and add the `passkey` prop.

**Install peer dependency:**
```bash
npm install @simplewebauthn/browser
```

**Add `passkey` prop to `LoginPageBuilder`:**
```tsx
<LoginPageBuilder
  api={{ loginUrl: '/api/v1/auth/login' }}
  branding={{ appName: 'My App' }}
  onSuccess={handleSuccess}
  gdpr={{ enabled: true, privacyPolicyUrl: '/privacy' }}
  passkey={{
    enabled: true,
    authenticationUrl: '/api/v1/auth/passkey/authenticate',
    registrationUrl: '/api/v1/auth/passkey/register',
    buttonLabel: 'Sign in with passkey',  // optional
    allowFallback: true,                  // optional, default: true
  }}
/>
```

**Server requirements** — implement these endpoints using a WebAuthn server library:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `{authenticationUrl}` | POST | Returns WebAuthn authentication options |
| `{authenticationUrl}/verify` | POST | Verifies client assertion, returns `LoginResponse` |
| `{registrationUrl}` | POST | Returns WebAuthn registration options |

Recommended server libraries:
- Node.js: `@simplewebauthn/server`
- Python: `py_webauthn`
- Go: `github.com/go-webauthn/webauthn`

**Browser support** — The `PasskeyButton` auto-hides when the browser does not support WebAuthn platform authenticators. No conditional rendering required in your app code.

## Migrating to 1.2.0

### SidebarMenu new props

If you are passing `defaultOpen` or `autoCollapse`, update your usage:

```tsx
// Now available:
<SidebarMenu
  categories={categories}
  currentPath={location.pathname}
  onNavigate={navigate}
  defaultOpen={false}          // Start collapsed
  autoCollapse={true}          // Collapse on mobile
  onGroupToggle={(name, open) => console.log(name, open)}
/>
```

No breaking changes — all new props are optional with backward-compatible defaults.
