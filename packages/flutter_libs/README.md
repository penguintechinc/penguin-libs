# flutter_libs

Shared Flutter widgets for Penguin Tech applications, built with the Elder dark theme.

## Scope

This package provides:

- Shared UI components (forms, login page, sidebar, version logging)
- Auth flows: email/password, OAuth2 (with PKCE), OIDC (with discovery),
  SAML, MFA, CAPTCHA (ALTCHA proof-of-work)
- Secure token storage via `TokenStorage` (Keychain/Keystore-backed,
  wraps `flutter_secure_storage`)

This package does **not** (yet) provide:

- A license entitlement client (`license.penguintech.io` integration)
- An analytics client

Both are tracked as follow-up work — do not assume they exist based on
descriptions elsewhere; only what's documented here and exported from
`flutter_libs.dart` is implemented.

## Platform Support

**Supported: mobile (iOS, Android) and desktop (macOS, Windows, Linux)** —
the PenguinTech Flutter house targets (see `client-flutter.md`).

**Not supported: Flutter web.** `saml_utils.dart` uses `dart:io`'s
`ZLibCodec` to DEFLATE-compress the SAML `AuthnRequest` per the HTTP-Redirect
binding spec, and `dart:io` does not compile for the web target. Because
`saml_utils.dart` is re-exported from the top-level `flutter_libs.dart`
barrel, **importing `package:flutter_libs/flutter_libs.dart` at all breaks
web builds**, not just apps that use the SAML login flow. If web support
becomes a requirement, `saml_utils.dart`'s DEFLATE step needs a
conditional-import split (`dart:io` vs. a pure-Dart implementation, e.g. via
the `archive` package) before this package can be used from a web target.

## Components

### FormModalBuilder

Modal form dialogs with tabbed layouts, 18 field types, validation, and file upload.

```dart
FormModalBuilder.show(
  context: context,
  title: 'Create User',
  fields: [
    FormFieldConfig(name: 'name', label: 'Name', type: FormFieldType.text, required: true),
    FormFieldConfig(name: 'email', label: 'Email', type: FormFieldType.email, required: true),
    FormFieldConfig(name: 'role', label: 'Role', type: FormFieldType.select, options: [
      FormFieldOption(label: 'Admin', value: 'admin'),
      FormFieldOption(label: 'User', value: 'user'),
    ]),
  ],
  onSubmit: (values) async {
    await api.createUser(values);
  },
);
```

### FormBuilder

Inline and modal forms with controller-based state management.

### LoginPageBuilder

Full-featured login page with social login, MFA, CAPTCHA, and GDPR consent.

```dart
LoginPageBuilder(
  apiConfig: LoginApiConfig(loginUrl: 'https://api.example.com/auth/login'),
  branding: BrandingConfig(appName: 'My App', tagline: 'Welcome back'),
  socialProviders: [
    BuiltInOAuth2Provider(
      provider: BuiltInProviderType.google,
      clientId: 'your-client-id',
      redirectUri: 'https://example.com/callback',
    ),
  ],
  onLoginSuccess: (response) => Navigator.pushReplacementNamed(context, '/home'),
);
```

Pass `tokenStorage: TokenStorage()` to persist the access/refresh tokens to
platform-secure storage automatically on a successful login. This widget has
no logout UI — call `tokenStorage.clear()` yourself wherever your app
implements logout.

For social/SSO login, `buildOAuth2Url`/`buildCustomOAuth2Url`/`buildOIDCUrl`
return an `OAuth2AuthorizationRequest` (`url`, `state`, `codeVerifier`), and
`initiateSAMLLogin` returns a `SAMLLoginRequest` (`url`, `relayState`).
Retain `state`/`relayState`/`codeVerifier` (e.g. via
`LoginPageBuilder.onSocialLoginInitiated`) and validate the callback's
returned `state`/`RelayState` with `isValidCallbackState` before exchanging
the authorization code or accepting a SAML response.

### SidebarMenu

Collapsible navigation sidebar with role-based item filtering.

```dart
SidebarMenu(
  categories: [
    MenuCategory(header: 'Main', items: [
      MenuItem(name: 'Dashboard', href: '/dashboard', icon: Icons.dashboard),
      MenuItem(name: 'Settings', href: '/settings', icon: Icons.settings),
    ]),
  ],
  activePath: '/dashboard',
  onNavigate: (href) => Navigator.pushNamed(context, href),
);
```

### ConsoleVersion

Version logging widget that logs build info to the developer console.

```dart
ConsoleVersion(
  version: 'v1.2.3.1234567890',
  appName: 'My App',
);
```

## Installation

### Git dependency

```yaml
dependencies:
  flutter_libs:
    git:
      url: https://github.com/penguintechinc/penguin-libs.git
      path: packages/flutter_libs
```

### Local development

```yaml
dependencies:
  flutter_libs:
    path: ../penguin-libs/packages/flutter_libs
```

## Elder Theme

All components use the Elder dark theme by default, featuring slate and amber colors. Customize via color config classes:

- `FormColorConfig` — Form modal colors (30+ properties)
- `LoginColorConfig` — Login page colors (30+ properties)
- `SidebarColorConfig` — Sidebar colors (13 properties)
- `ElderThemeData` — Global theme extension

## License

MIT — See [LICENSE](LICENSE) for details.
