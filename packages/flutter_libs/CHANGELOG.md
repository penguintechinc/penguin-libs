# Changelog

## Unreleased

### Breaking / Platform Support

- **Flutter web is no longer supported** by this package. The SAML
  HTTP-Redirect DEFLATE fix (see below) uses `dart:io`'s `ZLibCodec`, which
  does not compile for web; since `saml_utils.dart` is re-exported from the
  `flutter_libs.dart` barrel, this affects the whole package, not just SAML
  users. Supported targets remain mobile (iOS/Android) and desktop
  (macOS/Windows/Linux) — see README "Platform Support".

### Security

- **CaptchaWidget**: replaced the placeholder that returned a hardcoded
  token with a real ALTCHA proof-of-work flow (fetch, solve on a
  background isolate, fail closed on any error)
- **OAuth2/OIDC**: wired PKCE (`code_challenge`/`S256`) into
  `buildOAuth2Url`/`buildCustomOAuth2Url`/`buildOIDCUrl`; these now return
  an `OAuth2AuthorizationRequest` (`url`, `state`, `codeVerifier`) instead
  of a bare `String` (breaking change)
- **SAML**: `initiateSAMLLogin` now returns a `SAMLLoginRequest` (`url`,
  `relayState`) so the CSRF `RelayState` is no longer discarded (breaking
  change); added `isValidCallbackState` helper for validating returned
  `state`/`RelayState`; XML-escaped `idpSsoUrl`/`acsUrl`/`entityId`;
  `SAMLRequest` is now raw-DEFLATE + base64 encoded per the HTTP-Redirect
  binding spec (previously plain base64)
- **LoginApiConfig**: `loginUrl` must be `https://` in release builds
  (localhost/127.0.0.1 exempted) — throws otherwise; no longer a `const`
  constructor
- **TokenStorage**: added secure (Keychain/Keystore-backed) token storage;
  `LoginPageBuilder` now accepts an optional `tokenStorage` parameter
- **sanitizedLog**: normalizes keys (lowercase, strip `_`) before matching
  the redaction denylist, extended the denylist, and now recurses into
  `List`s (previously only `Map`s)
- **Login failure handling**: only a genuine `401` counts toward the
  CAPTCHA failure threshold; 5xx/network errors surface a distinct message
  instead of silently penalizing the user

### Fixed

- 30-second timeout on all HTTP calls (login, OIDC discovery, ALTCHA
  challenge fetch, version fetch), each with a user-facing error
- `MFAInput`: fixed a `FocusNode` leak (one was created inline in `build()`
  on every rebuild); paste of a full code no longer breaks due to
  `maxLength: 1` truncating input before it reaches the paste handler
- `CookieConsentNotifier`: consent is now stored as JSON; a legacy
  comma/colon-encoded value from before this change is still read once on
  migration rather than being silently reset
- `FormModalBuilder`: submit failures show a generic message and route the
  real error through `sanitizedLog` instead of displaying the raw
  exception
- `rememberDevice` from the MFA modal is now threaded through to the login
  payload (previously discarded)
- `pubspec.yaml` dependencies are now exact-pinned (no `^`)

### Scope clarification

- This package provides UI + auth flows + secure token storage. It does
  **not** include a license entitlement client or analytics client (see
  README) — tracked as follow-up work.

## 0.1.0

Initial release of the Flutter shared library.

### Added

- **Theme**: Elder dark theme with `ElderColors` and `ElderThemeData` extension
- **FormModalBuilder**: Modal form dialogs with 18 field types, tabbed layouts, validation, file upload, and password generation
- **FormBuilder**: Inline and modal forms with controller-based state management
- **LoginPageBuilder**: Full login page with email/password, social login (OAuth2, OIDC, SAML), MFA, CAPTCHA, and GDPR consent
- **SidebarMenu**: Collapsible navigation sidebar with role-based filtering and active path highlighting
- **ConsoleVersion**: Version logging widget with ASCII banner output
- **AppConsoleVersion**: API-fetching variant of ConsoleVersion
- Comprehensive color configuration classes for all components
- OAuth2, OIDC, and SAML utility functions
- Form validators ported from Zod schemas
- Password generator with secure random
- Sanitized logger for redacting sensitive data
