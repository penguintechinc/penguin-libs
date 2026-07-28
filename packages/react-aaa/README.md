# @penguintechinc/react-aaa

Authentication, Authorization, and Audit library for React applications — OIDC, RBAC, and audit logging.

## Installation

```bash
npm install @penguintechinc/react-aaa
```

## Features

- **OIDC/OAuth2 authentication** — OpenID Connect and OAuth2 flow support
- **Role-based access control (RBAC)** — Scope-based authorization with role bundling
- **Audit logging** — Track authentication events for compliance
- **JWT token management** — Automatic token refresh and expiration handling
- **Multi-tenant support** — Tenant-scoped identity and access control
- **Secure token storage** — XSS-resistant in-memory default, opt-in session storage

## Token Storage

### ⚠️ BREAKING CHANGE: Default Token Storage

**As of v0.1.5+, tokens are stored in-memory by default instead of sessionStorage.**

#### Impact

- **Page refresh requires re-authentication** — tokens are cleared when the page reloads
- **XSS-safe by default** — tokens cannot be exfiltrated via JavaScript/XSS attacks
- **No persistent session** — users must re-auth after closing the browser tab

#### Migration

**Option 1: Accept default memory storage (recommended)**

No code changes needed. Users will need to re-authenticate after a page refresh.

```typescript
// Token stored in memory (XSS-safe, cleared on refresh)
const manager = new TokenManager();
```

**Option 2: Opt into sessionStorage (backward-compatible, XSS-exfiltrable)**

If you need tokens to persist across page refreshes and can ensure your app has strong XSS protections:

```typescript
// Token stored in sessionStorage (backward-compatible)
// ⚠️ WARNING: Vulnerable to XSS token exfiltration
const manager = new TokenManager({ storage: 'session' });
```

**Option 3: Custom storage implementation**

For advanced use cases, provide your own TokenStorage implementation:

```typescript
interface TokenStorage {
  set(key: string, tokens: TokenSet): void;
  get(key: string): TokenSet | null;
  remove(key: string): void;
}

const customStorage: TokenStorage = { /* your impl */ };
const manager = new TokenManager({ storage: customStorage });
```

## Usage

### Basic Setup

```typescript
import { useAuth } from '@penguintechinc/react-aaa';

function App() {
  const { user, isAuthenticated, login, logout } = useAuth();

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <div>
      <p>Hello, {user?.email}</p>
      <button onClick={logout}>Logout</button>
    </div>
  );
}
```

### Protected Routes

```typescript
import { ProtectedRoute } from '@penguintechinc/react-aaa';

<Routes>
  <Route path="/login" element={<LoginPage />} />
  <Route
    path="/dashboard"
    element={
      <ProtectedRoute>
        <DashboardPage />
      </ProtectedRoute>
    }
  />
</Routes>
```

### OIDC Configuration

```typescript
import { OIDCAuthProvider } from '@penguintechinc/react-aaa';

const oidcConfig = {
  clientId: 'your-client-id',
  issuer: 'https://your-oidc-provider.com',
  redirectUri: window.location.origin + '/callback',
  scopes: ['openid', 'profile', 'email'],
};

<OIDCAuthProvider config={oidcConfig}>
  <App />
</OIDCAuthProvider>
```

## Security

### XSS Protection

Tokens are stored in-memory by default, preventing exfiltration via XSS. Use sessionStorage only if you have strong XSS mitigations in place (CSP, input sanitization, etc.).

### CSRF Protection

All OIDC flows include CSRF state validation. Never disable this protection.

### OIDC Compliance

- Automatic token refresh before expiration
- Secure redirect path sanitization (prevents open redirect attacks)
- Proper token validation and expiration checks

## API Reference

### `useAuth()`

Hook to access authentication state and methods.

```typescript
const {
  user,              // Authenticated user object
  isAuthenticated,   // Boolean
  isLoading,         // Loading state
  error,             // Authentication error
  login,             // Trigger login flow
  logout,            // Trigger logout
  refreshToken,      // Force token refresh
} = useAuth();
```

### `TokenManager`

Manages JWT token storage and refresh.

```typescript
const manager = new TokenManager({
  storage: 'memory' | 'session' | TokenStorage,  // Default: 'memory'
  onTokenRefreshed: (tokens) => { },
  onTokenExpired: () => { },
  onRefresh: async (refreshToken) => { /* ... */ },
});

manager.store(tokens);
manager.getAccessToken();
manager.getTokenSet();
manager.isExpired();
manager.clear();
```

## License

MIT — See [LICENSE](../../LICENSE) for details.

## Support

- Issues: https://github.com/penguintechinc/penguin-libs/issues
- Email: dev@penguintech.io
