# flutter-libs API Reference

## FormModalBuilder

Modal dialog containing a typed form. Supports tabbed layouts, 18 field types, validation, and file upload.

### Static Method

```dart
static Future<Map<String, dynamic>?> show({
  required BuildContext context,
  required String title,
  required List<FormFieldConfig> fields,
  required Future<void> Function(Map<String, dynamic>) onSubmit,
  List<String>? tabs,
  String submitLabel = 'Save',
  FormColorConfig? colors,
})
```

Returns `null` if the user dismisses the modal without submitting.

### FormFieldConfig

```dart
class FormFieldConfig {
  final String name;
  final String label;
  final FormFieldType type;
  final bool required;
  final String? tab;
  final String? placeholder;
  final dynamic defaultValue;
  final List<FormFieldOption>? options;  // For select/multiselect fields
}
```

### FormFieldType

```dart
enum FormFieldType {
  text, email, password, number, phone, url,
  textarea, select, multiselect, checkbox,
  date, datetime, time,
  file, image,
  color, slider, rating,
}
```

### FormFieldOption

```dart
class FormFieldOption {
  final String label;
  final String value;
}
```

---

## FormBuilder

Inline form with controller-based state management. Use when a full modal is not needed.

```dart
FormBuilder(
  fields: [...],
  onSubmit: (values) async { ... },
  controller: formController,
)
```

### FormBuilderController

```dart
class FormBuilderController extends ChangeNotifier {
  Map<String, dynamic> get values;
  void reset();
  Future<bool> validate();
  Future<void> submit();
}
```

---

## LoginPageBuilder

Full-featured login page widget.

### Constructor Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `apiConfig` | `LoginApiConfig` | ✅ | API endpoint configuration |
| `branding` | `BrandingConfig` | ✅ | App name, logo, tagline |
| `onLoginSuccess` | `void Function(LoginResponse)` | ✅ | Called on successful login |
| `socialProviders` | `List<OAuth2Provider>` | — | OAuth2/OIDC provider buttons |
| `gdprConfig` | `GdprConfig` | — | GDPR consent banner |
| `mfaConfig` | `MfaConfig` | — | MFA/TOTP 6-digit input |
| `captchaConfig` | `CaptchaConfig` | — | CAPTCHA configuration |
| `colors` | `LoginColorConfig` | — | Theme color overrides |

### LoginApiConfig

```dart
class LoginApiConfig {
  final String loginUrl;
  final String? mfaVerifyUrl;
  final Map<String, String>? headers;
}
```

### BrandingConfig

```dart
class BrandingConfig {
  final String appName;
  final String? tagline;
  final String? logoAsset;    // Asset path
  final String? logoUrl;      // Network image URL
}
```

### OAuth2Provider

```dart
// Built-in providers
BuiltInOAuth2Provider(
  provider: BuiltInProviderType.google,  // .google, .github, .microsoft
  clientId: 'your-client-id',
  redirectUri: 'https://example.com/callback',
)

// Custom OIDC provider
CustomOAuth2Provider(
  label: 'Company SSO',
  issuerUrl: 'https://sso.company.com',
  clientId: 'app-id',
  redirectUri: 'https://example.com/callback',
  iconUrl: 'https://company.com/icon.png',
)
```

### LoginResponse

```dart
class LoginResponse {
  final String? token;
  final String? refreshToken;
  final Map<String, dynamic>? user;
  final bool mfaRequired;
}
```

---

## SidebarMenu

Collapsible navigation sidebar with Elder dark theme styling and optional role-based item filtering.

### Constructor Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `categories` | `List<MenuCategory>` | ✅ | Navigation groups |
| `activePath` | `String` | ✅ | Currently active route |
| `onNavigate` | `void Function(String)` | ✅ | Navigation callback |
| `header` | `Widget?` | — | Widget above category list (logo, app name) |
| `footer` | `Widget?` | — | Widget below category list (user profile) |
| `userRole` | `String?` | — | Filters items by `requiredRole` |
| `colors` | `SidebarColorConfig?` | — | Theme color overrides |
| `initiallyExpanded` | `bool` | — | Start expanded (default: `true`) |

### MenuCategory

```dart
class MenuCategory {
  final String header;
  final List<MenuItem> items;
}
```

### MenuItem

```dart
class MenuItem {
  final String name;
  final String href;
  final IconData? icon;
  final String? badge;
  final String? requiredRole;  // Hide if userRole does not match
}
```

---

## ConsoleVersion

Logs build version and app name to the developer console (`debugPrint`) on widget mount.

```dart
ConsoleVersion(
  version: 'v1.2.3.1234567890',
  appName: 'My App',
  metadata: {'Environment': 'production'},  // Optional extra fields
)
```

---

## Theme

### ElderThemeData

```dart
ThemeData theme = ThemeData.dark().copyWith(
  extensions: [ElderThemeData.defaults()],
);
```

### Color Config Classes

All color configs expose named color properties that accept `Color` values.

```dart
FormColorConfig(
  backgroundPrimary: const Color(0xFF0F172A),   // slate-900
  backgroundSecondary: const Color(0xFF1E293B), // slate-800
  textPrimary: const Color(0xFFFBBF24),         // amber-400
  // ... 27 more properties
)
```

Equivalent configs: `LoginColorConfig` (30+ properties), `SidebarColorConfig` (13 properties).
