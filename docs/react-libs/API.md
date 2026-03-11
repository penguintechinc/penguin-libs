# react-libs API Reference

## LoginPageBuilder

Complete login page component with Elder dark theme. Includes email/password form, GDPR consent banner, ALTCHA CAPTCHA, MFA/TOTP, social login (OAuth2/OIDC), and WebAuthn passkey support.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `api.loginUrl` | `string` | ✅ | Login endpoint URL (`POST`) |
| `branding.appName` | `string` | ✅ | Application name displayed above form |
| `branding.logo` | `string` | — | Logo image URL (300px height) |
| `branding.tagline` | `string` | — | Subtitle text below app name |
| `branding.githubRepo` | `string` | — | `owner/repo` for GitHub link |
| `onSuccess` | `(response: LoginResponse) => void` | ✅ | Called on successful login |
| `gdpr.enabled` | `boolean` | — | Show GDPR cookie consent banner |
| `gdpr.privacyPolicyUrl` | `string` | — | Privacy policy URL |
| `captcha` | `CaptchaConfig` | — | ALTCHA proof-of-work CAPTCHA |
| `mfa` | `MFAConfig` | — | MFA/TOTP 6-digit input |
| `socialLogins` | `SocialLoginConfig[]` | — | OAuth2/OIDC provider buttons |
| `passkey` | `PasskeyConfig` | — | WebAuthn passkey authentication |

### PasskeyConfig

```typescript
interface PasskeyConfig {
  enabled: boolean;
  registrationUrl: string;       // POST — returns WebAuthn registration options
  authenticationUrl: string;     // POST — returns WebAuthn authentication options
  buttonLabel?: string;          // Default: "Sign in with passkey"
  allowFallback?: boolean;       // Default: true — show password form on passkey failure
}
```

The passkey button is hidden automatically when the browser does not support WebAuthn platform authenticators. When `allowFallback` is `true` (default), a failed passkey attempt gracefully falls through to the password form.

**Required backend endpoints:**
- `POST {authenticationUrl}` — returns WebAuthn authentication options JSON
- `POST {authenticationUrl}/verify` — verifies the client assertion and returns `LoginResponse`
- `POST {registrationUrl}` — returns WebAuthn registration options JSON (for future registration flow)

### CaptchaConfig

```typescript
interface CaptchaConfig {
  enabled: boolean;
  provider: 'altcha';
  challengeUrl: string;
  failedAttemptsThreshold?: number;  // Default: 3
}
```

### MFAConfig

```typescript
interface MFAConfig {
  enabled: boolean;
  codeLength?: number;            // Default: 6
  allowRememberDevice?: boolean;
}
```

### SocialLoginConfig

```typescript
interface SocialLoginConfig {
  provider: 'google' | 'github' | 'oidc';
  clientId: string;
  issuerUrl?: string;   // Required for 'oidc'
  label?: string;       // Default: provider name
}
```

### LoginResponse

```typescript
interface LoginResponse {
  token?: string;
  user?: { id: string; email: string; role: string };
  redirect?: string;
  mfa_required?: boolean;
}
```

---

## SidebarMenu

Elder-style collapsible navigation sidebar with category headers and item icons.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `categories` | `Category[]` | ✅ | Navigation groups |
| `currentPath` | `string` | ✅ | Active route path for highlight |
| `onNavigate` | `(href: string) => void` | ✅ | Navigation callback |
| `logo` | `ReactNode` | — | Logo element rendered at top |
| `defaultOpen` | `boolean` | — | Sidebar starts open (default: `true`) |
| `autoCollapse` | `boolean` | — | Auto-collapse on mobile breakpoint |
| `onGroupToggle` | `(name: string, isOpen: boolean) => void` | — | Called when a category is toggled |

### Category / MenuItem

```typescript
interface Category {
  header: string;
  items: MenuItem[];
}

interface MenuItem {
  name: string;
  href: string;
  icon?: ComponentType;
  badge?: string | number;
  adminOnly?: boolean;
}
```

---

## FormModalBuilder

Modal dialog with typed form fields, tabs, and validation.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `title` | `string` | ✅ | Modal title |
| `isOpen` | `boolean` | ✅ | Visibility state |
| `onClose` | `() => void` | ✅ | Close handler |
| `onSubmit` | `(data: Record<string, unknown>) => void \| Promise<void>` | ✅ | Submit handler |
| `fields` | `FormField[]` | ✅ | Form field definitions |
| `tabs` | `string[]` | — | Tab labels (groups fields by `tab` key) |
| `submitLabel` | `string` | — | Submit button label (default: "Save") |

### FormField

```typescript
interface FormField {
  name: string;
  label: string;
  type: 'text' | 'email' | 'password' | 'number' | 'select' | 'textarea' | 'checkbox' | 'date';
  required?: boolean;
  options?: { value: string; label: string }[];  // For 'select' type
  tab?: string;
  placeholder?: string;
  defaultValue?: unknown;
}
```

---

## AppConsoleVersion

Logs WebUI and API version information to the browser console on mount. Useful for debugging deployed versions.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `appName` | `string` | ✅ | Application name |
| `webuiVersion` | `string` | ✅ | WebUI version string |
| `webuiBuildEpoch` | `number` | ✅ | Build timestamp (Unix epoch) |
| `environment` | `string` | — | Current environment (`development`, `production`) |
| `apiStatusUrl` | `string` | — | URL to fetch API version (`GET`, returns `{version, build_epoch}`) |
| `metadata` | `Record<string, string>` | — | Extra key/value pairs to log |

### Expected Console Output

```
🖥️ MyApp - WebUI
Version: 1.3.0
Build Epoch: 1741564800
Build Date: 2026-03-10 00:00:00 UTC
Environment: production
⚙️ MyApp - API
Version: 1.3.0
Build Epoch: 1741564800
Build Date: 2026-03-10 00:00:00 UTC
```

---

## Exported Types

```typescript
import type {
  LoginResponse,
  CaptchaConfig,
  MFAConfig,
  SocialLoginConfig,
  PasskeyConfig,
  Category,
  MenuItem,
  FormField,
} from '@penguintechinc/react-libs';
```
