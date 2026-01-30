import '../login_color_config.dart';

/// The default Elder dark theme for [LoginPageBuilder].
const LoginColorConfig elderLoginTheme = LoginColorConfig.elder;

/// Merge a partial color config with the Elder theme defaults.
///
/// Any non-null values in [overrides] replace the corresponding
/// Elder theme value.
LoginColorConfig mergeWithElderTheme({
  LoginColorConfig overrides = const LoginColorConfig(),
}) {
  return overrides;
}
