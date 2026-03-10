# react-libs Changelog

## 1.3.0 (2026-03-10)

### New Features

- **WebAuthn/Passkey support in `LoginPageBuilder`**
  - New `passkey` prop accepts `PasskeyConfig`
  - `PasskeyButton` component auto-detects platform authenticator availability via `PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()`
  - Button is hidden automatically when WebAuthn is unsupported by the browser
  - `allowFallback: true` (default) falls through to password form on passkey failure
  - Uses `@simplewebauthn/browser` for WebAuthn registration and authentication flows
  - New `PasskeyConfig` type exported from package root
  - Console logging follows `[LoginPageBuilder:Passkey]` prefix pattern

## 1.2.0

- Tenant field support in `LoginPageBuilder` — optional tenant selector for multi-tenant apps
- `SidebarMenu` new props: `autoCollapse`, `defaultOpen`, `onGroupToggle`
- `SidebarMenu` test coverage: `autoCollapse`, `defaultOpen`, `onGroupToggle` behaviors

## 1.1.0

- MFA/TOTP 6-digit input in `LoginPageBuilder`
- ALTCHA proof-of-work CAPTCHA integration with configurable failure threshold
- Social login buttons (Google, GitHub, OIDC) in `LoginPageBuilder`

## 1.0.0

- Initial release
- `LoginPageBuilder` — email/password form with GDPR consent banner
- `SidebarMenu` — Elder-style collapsible navigation sidebar
- `FormModalBuilder` — modal form with typed fields and validation
- `AppConsoleVersion` — browser console version logging
