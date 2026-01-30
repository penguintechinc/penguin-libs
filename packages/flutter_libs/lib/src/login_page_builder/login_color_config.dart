import 'package:flutter/material.dart';
import '../theme/elder_colors.dart';

/// Color configuration for [LoginPageBuilder].
///
/// All colors default to the Elder dark theme palette.
class LoginColorConfig {
  const LoginColorConfig({
    this.pageBackground = ElderColors.slate950,
    this.cardBackground = ElderColors.slate800,
    this.cardBorder = ElderColors.slate700,
    this.titleText = ElderColors.amber400,
    this.subtitleText = ElderColors.slate400,
    this.labelText = ElderColors.amber300,
    this.inputBackground = ElderColors.slate900,
    this.inputBorder = ElderColors.slate600,
    this.inputFocusBorder = ElderColors.amber500,
    this.inputText = ElderColors.white,
    this.inputPlaceholder = ElderColors.slate500,
    this.primaryButton = ElderColors.amber500,
    this.primaryButtonHover = ElderColors.amber600,
    this.primaryButtonText = ElderColors.slate900,
    this.socialButtonBackground = ElderColors.slate700,
    this.socialButtonBorder = ElderColors.slate600,
    this.socialButtonText = ElderColors.white,
    this.socialButtonHover = ElderColors.slate600,
    this.errorText = ElderColors.red400,
    this.errorBackground = const Color(0x1AF87171),
    this.successText = ElderColors.green400,
    this.linkText = ElderColors.amber400,
    this.linkHoverText = ElderColors.amber300,
    this.dividerColor = ElderColors.slate700,
    this.checkboxActive = ElderColors.amber500,
    this.footerText = ElderColors.slate500,
    this.mfaBackground = ElderColors.slate800,
    this.mfaInputBackground = ElderColors.slate900,
    this.mfaInputBorder = ElderColors.slate600,
    this.captchaBackground = ElderColors.slate900,
  });

  final Color pageBackground;
  final Color cardBackground;
  final Color cardBorder;
  final Color titleText;
  final Color subtitleText;
  final Color labelText;
  final Color inputBackground;
  final Color inputBorder;
  final Color inputFocusBorder;
  final Color inputText;
  final Color inputPlaceholder;
  final Color primaryButton;
  final Color primaryButtonHover;
  final Color primaryButtonText;
  final Color socialButtonBackground;
  final Color socialButtonBorder;
  final Color socialButtonText;
  final Color socialButtonHover;
  final Color errorText;
  final Color errorBackground;
  final Color successText;
  final Color linkText;
  final Color linkHoverText;
  final Color dividerColor;
  final Color checkboxActive;
  final Color footerText;
  final Color mfaBackground;
  final Color mfaInputBackground;
  final Color mfaInputBorder;
  final Color captchaBackground;

  /// Default Elder dark theme configuration.
  static const LoginColorConfig elder = LoginColorConfig();
}
