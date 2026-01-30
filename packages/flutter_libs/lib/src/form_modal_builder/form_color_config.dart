import 'package:flutter/material.dart';
import '../theme/elder_colors.dart';

/// Color configuration for [FormModalBuilder].
///
/// All colors default to the Elder dark theme palette.
class FormColorConfig {
  const FormColorConfig({
    this.modalBackground = ElderColors.slate800,
    this.headerBackground = ElderColors.slate800,
    this.footerBackground = ElderColors.slate900,
    this.overlayBackground = const Color(0x80000000),
    this.titleText = ElderColors.amber400,
    this.labelText = ElderColors.amber300,
    this.descriptionText = ElderColors.slate400,
    this.errorText = ElderColors.red400,
    this.buttonText = ElderColors.slate900,
    this.fieldBackground = ElderColors.white,
    this.fieldBorder = ElderColors.slate600,
    this.fieldText = ElderColors.slate900,
    this.fieldPlaceholder = ElderColors.slate400,
    this.focusRing = ElderColors.amber500,
    this.focusBorder = ElderColors.amber500,
    this.primaryButton = ElderColors.amber500,
    this.primaryButtonHover = ElderColors.amber600,
    this.secondaryButton = ElderColors.slate700,
    this.secondaryButtonHover = ElderColors.slate600,
    this.secondaryButtonBorder = ElderColors.slate600,
    this.secondaryButtonText = ElderColors.slate300,
    this.activeTab = ElderColors.amber400,
    this.activeTabBorder = ElderColors.amber500,
    this.inactiveTab = ElderColors.slate400,
    this.inactiveTabHover = ElderColors.slate300,
    this.tabBorder = ElderColors.slate700,
    this.errorTabText = ElderColors.red400,
    this.errorTabBorder = ElderColors.red500,
    this.checkboxActive = ElderColors.amber500,
    this.radioActive = ElderColors.amber500,
    this.disabledBackground = ElderColors.slate700,
    this.disabledText = ElderColors.slate500,
  });

  final Color modalBackground;
  final Color headerBackground;
  final Color footerBackground;
  final Color overlayBackground;
  final Color titleText;
  final Color labelText;
  final Color descriptionText;
  final Color errorText;
  final Color buttonText;
  final Color fieldBackground;
  final Color fieldBorder;
  final Color fieldText;
  final Color fieldPlaceholder;
  final Color focusRing;
  final Color focusBorder;
  final Color primaryButton;
  final Color primaryButtonHover;
  final Color secondaryButton;
  final Color secondaryButtonHover;
  final Color secondaryButtonBorder;
  final Color secondaryButtonText;
  final Color activeTab;
  final Color activeTabBorder;
  final Color inactiveTab;
  final Color inactiveTabHover;
  final Color tabBorder;
  final Color errorTabText;
  final Color errorTabBorder;
  final Color checkboxActive;
  final Color radioActive;
  final Color disabledBackground;
  final Color disabledText;

  /// Default Elder dark theme configuration.
  static const FormColorConfig elder = FormColorConfig();
}
