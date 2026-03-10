# flutter-libs

Shared Flutter widgets for Penguin Tech Inc applications. All components use the Elder dark theme (slate backgrounds, amber/gold accents) by default and are fully customizable via color config classes.

## Installation

### Git dependency (recommended)

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

## Components

| Component | Description |
|-----------|-------------|
| `FormModalBuilder` | Modal form dialogs with tabbed layouts, 18 field types, validation, and file upload |
| `FormBuilder` | Inline forms with controller-based state management |
| `LoginPageBuilder` | Full login page with social login, MFA, CAPTCHA, and GDPR consent |
| `SidebarMenu` | Collapsible navigation sidebar with role-based item filtering |
| `ConsoleVersion` | Version logging widget that logs build info to the developer console |

## Quick Start

```dart
import 'package:flutter_libs/flutter_libs.dart';

// Modal form
FormModalBuilder.show(
  context: context,
  title: 'Create User',
  fields: [
    FormFieldConfig(name: 'name', label: 'Name', type: FormFieldType.text, required: true),
    FormFieldConfig(name: 'email', label: 'Email', type: FormFieldType.email, required: true),
  ],
  onSubmit: (values) async => await api.createUser(values),
);

// Login page
LoginPageBuilder(
  apiConfig: LoginApiConfig(loginUrl: 'https://api.example.com/auth/login'),
  branding: BrandingConfig(appName: 'My App', tagline: 'Welcome back'),
  onLoginSuccess: (response) => Navigator.pushReplacementNamed(context, '/home'),
);

// Sidebar navigation
SidebarMenu(
  categories: [
    MenuCategory(header: 'Main', items: [
      MenuItem(name: 'Dashboard', href: '/dashboard', icon: Icons.dashboard),
    ]),
  ],
  activePath: '/dashboard',
  onNavigate: (href) => Navigator.pushNamed(context, href),
);
```

## Elder Theme

All components default to the Elder dark theme. Customize via color config classes:

- `FormColorConfig` — 30+ color properties for form modals
- `LoginColorConfig` — 30+ color properties for the login page
- `SidebarColorConfig` — 13 color properties for the sidebar
- `ElderThemeData` — Global Flutter `ThemeExtension` for app-wide theme

📚 Full documentation: [docs/flutter-libs/](../../docs/flutter-libs/)
