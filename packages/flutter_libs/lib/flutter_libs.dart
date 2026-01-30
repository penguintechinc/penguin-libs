/// Shared Flutter widgets for Penguin Tech applications.
///
/// Provides reusable widgets with the Elder dark theme:
/// - [FormModalBuilder] — Modal form dialogs with tabbed layouts
/// - [FormBuilder] — Inline and modal forms
/// - [LoginPageBuilder] — Full login pages with OAuth, MFA, CAPTCHA
/// - [SidebarMenu] — Navigation sidebar with role-based filtering
/// - [ConsoleVersion] — Version logging utilities
library flutter_libs;

// Theme
export 'src/theme/elder_colors.dart';
export 'src/theme/elder_theme_data.dart';

// FormModalBuilder
export 'src/form_modal_builder/form_field_config.dart';
export 'src/form_modal_builder/form_tab.dart';
export 'src/form_modal_builder/form_color_config.dart';
export 'src/form_modal_builder/form_validators.dart';
export 'src/form_modal_builder/password_generator.dart';
export 'src/form_modal_builder/sanitized_logger.dart';
export 'src/form_modal_builder/form_field_builder.dart';
export 'src/form_modal_builder/form_modal_builder.dart';

// FormBuilder
export 'src/form_builder/form_builder_types.dart';
export 'src/form_builder/form_builder_controller.dart';
export 'src/form_builder/form_builder_field.dart';
export 'src/form_builder/form_builder_modal.dart';
export 'src/form_builder/form_builder.dart';

// SidebarMenu
export 'src/sidebar_menu/sidebar_types.dart';
export 'src/sidebar_menu/sidebar_color_config.dart';
export 'src/sidebar_menu/sidebar_menu.dart';

// LoginPageBuilder
export 'src/login_page_builder/login_types.dart';
export 'src/login_page_builder/login_color_config.dart';
export 'src/login_page_builder/login_page_builder.dart';
export 'src/login_page_builder/theme/elder_login_theme.dart';
export 'src/login_page_builder/utils/oauth_utils.dart';
export 'src/login_page_builder/utils/saml_utils.dart';
export 'src/login_page_builder/state/captcha_state.dart';
export 'src/login_page_builder/state/cookie_consent_state.dart';
export 'src/login_page_builder/widgets/social_icons.dart';
export 'src/login_page_builder/widgets/mfa_input.dart';
export 'src/login_page_builder/widgets/mfa_modal.dart';
export 'src/login_page_builder/widgets/captcha_widget.dart';
export 'src/login_page_builder/widgets/social_login_buttons.dart';
export 'src/login_page_builder/widgets/cookie_consent_banner.dart';
export 'src/login_page_builder/widgets/login_footer.dart';

// ConsoleVersion
export 'src/console_version/console_style_config.dart';
export 'src/console_version/version_info.dart';
export 'src/console_version/version_logger.dart';
export 'src/console_version/console_version.dart';
export 'src/console_version/app_console_version.dart';
