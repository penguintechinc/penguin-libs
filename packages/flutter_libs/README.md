# flutter_libs

Shared Flutter widgets for Penguin Tech applications, built with the Elder dark theme.

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

AGPL-3.0 — See [LICENSE](LICENSE) for details.
