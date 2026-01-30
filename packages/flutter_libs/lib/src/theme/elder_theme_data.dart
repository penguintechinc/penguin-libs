import 'package:flutter/material.dart';
import 'elder_colors.dart';

/// Theme extension providing Elder dark theme colors to the widget tree.
///
/// Usage:
/// ```dart
/// Theme(
///   data: ThemeData.dark().copyWith(
///     extensions: [ElderThemeData.dark],
///   ),
///   child: MyApp(),
/// )
/// ```
///
/// Access in widgets:
/// ```dart
/// final elder = Theme.of(context).extension<ElderThemeData>()!;
/// ```
@immutable
class ElderThemeData extends ThemeExtension<ElderThemeData> {
  const ElderThemeData({
    required this.pageBackground,
    required this.cardBackground,
    required this.cardBorder,
    required this.titleText,
    required this.subtitleText,
    required this.labelText,
    required this.bodyText,
    required this.inputBackground,
    required this.inputBorder,
    required this.inputFocusBorder,
    required this.inputText,
    required this.primaryButton,
    required this.primaryButtonHover,
    required this.primaryButtonText,
    required this.secondaryButton,
    required this.secondaryButtonBorder,
    required this.errorText,
    required this.successText,
    required this.linkText,
    required this.linkHoverText,
    required this.divider,
  });

  final Color pageBackground;
  final Color cardBackground;
  final Color cardBorder;
  final Color titleText;
  final Color subtitleText;
  final Color labelText;
  final Color bodyText;
  final Color inputBackground;
  final Color inputBorder;
  final Color inputFocusBorder;
  final Color inputText;
  final Color primaryButton;
  final Color primaryButtonHover;
  final Color primaryButtonText;
  final Color secondaryButton;
  final Color secondaryButtonBorder;
  final Color errorText;
  final Color successText;
  final Color linkText;
  final Color linkHoverText;
  final Color divider;

  /// The default Elder dark theme.
  static const ElderThemeData dark = ElderThemeData(
    pageBackground: ElderColors.slate950,
    cardBackground: ElderColors.slate800,
    cardBorder: ElderColors.slate700,
    titleText: ElderColors.amber400,
    subtitleText: ElderColors.slate400,
    labelText: ElderColors.amber300,
    bodyText: ElderColors.slate300,
    inputBackground: ElderColors.slate900,
    inputBorder: ElderColors.slate600,
    inputFocusBorder: ElderColors.amber500,
    inputText: ElderColors.white,
    primaryButton: ElderColors.amber500,
    primaryButtonHover: ElderColors.amber600,
    primaryButtonText: ElderColors.slate900,
    secondaryButton: ElderColors.slate700,
    secondaryButtonBorder: ElderColors.slate600,
    errorText: ElderColors.red400,
    successText: ElderColors.green400,
    linkText: ElderColors.amber400,
    linkHoverText: ElderColors.amber300,
    divider: ElderColors.slate700,
  );

  @override
  ElderThemeData copyWith({
    Color? pageBackground,
    Color? cardBackground,
    Color? cardBorder,
    Color? titleText,
    Color? subtitleText,
    Color? labelText,
    Color? bodyText,
    Color? inputBackground,
    Color? inputBorder,
    Color? inputFocusBorder,
    Color? inputText,
    Color? primaryButton,
    Color? primaryButtonHover,
    Color? primaryButtonText,
    Color? secondaryButton,
    Color? secondaryButtonBorder,
    Color? errorText,
    Color? successText,
    Color? linkText,
    Color? linkHoverText,
    Color? divider,
  }) {
    return ElderThemeData(
      pageBackground: pageBackground ?? this.pageBackground,
      cardBackground: cardBackground ?? this.cardBackground,
      cardBorder: cardBorder ?? this.cardBorder,
      titleText: titleText ?? this.titleText,
      subtitleText: subtitleText ?? this.subtitleText,
      labelText: labelText ?? this.labelText,
      bodyText: bodyText ?? this.bodyText,
      inputBackground: inputBackground ?? this.inputBackground,
      inputBorder: inputBorder ?? this.inputBorder,
      inputFocusBorder: inputFocusBorder ?? this.inputFocusBorder,
      inputText: inputText ?? this.inputText,
      primaryButton: primaryButton ?? this.primaryButton,
      primaryButtonHover: primaryButtonHover ?? this.primaryButtonHover,
      primaryButtonText: primaryButtonText ?? this.primaryButtonText,
      secondaryButton: secondaryButton ?? this.secondaryButton,
      secondaryButtonBorder: secondaryButtonBorder ?? this.secondaryButtonBorder,
      errorText: errorText ?? this.errorText,
      successText: successText ?? this.successText,
      linkText: linkText ?? this.linkText,
      linkHoverText: linkHoverText ?? this.linkHoverText,
      divider: divider ?? this.divider,
    );
  }

  @override
  ElderThemeData lerp(ElderThemeData? other, double t) {
    if (other is! ElderThemeData) return this;
    return ElderThemeData(
      pageBackground: Color.lerp(pageBackground, other.pageBackground, t)!,
      cardBackground: Color.lerp(cardBackground, other.cardBackground, t)!,
      cardBorder: Color.lerp(cardBorder, other.cardBorder, t)!,
      titleText: Color.lerp(titleText, other.titleText, t)!,
      subtitleText: Color.lerp(subtitleText, other.subtitleText, t)!,
      labelText: Color.lerp(labelText, other.labelText, t)!,
      bodyText: Color.lerp(bodyText, other.bodyText, t)!,
      inputBackground: Color.lerp(inputBackground, other.inputBackground, t)!,
      inputBorder: Color.lerp(inputBorder, other.inputBorder, t)!,
      inputFocusBorder: Color.lerp(inputFocusBorder, other.inputFocusBorder, t)!,
      inputText: Color.lerp(inputText, other.inputText, t)!,
      primaryButton: Color.lerp(primaryButton, other.primaryButton, t)!,
      primaryButtonHover: Color.lerp(primaryButtonHover, other.primaryButtonHover, t)!,
      primaryButtonText: Color.lerp(primaryButtonText, other.primaryButtonText, t)!,
      secondaryButton: Color.lerp(secondaryButton, other.secondaryButton, t)!,
      secondaryButtonBorder: Color.lerp(secondaryButtonBorder, other.secondaryButtonBorder, t)!,
      errorText: Color.lerp(errorText, other.errorText, t)!,
      successText: Color.lerp(successText, other.successText, t)!,
      linkText: Color.lerp(linkText, other.linkText, t)!,
      linkHoverText: Color.lerp(linkHoverText, other.linkHoverText, t)!,
      divider: Color.lerp(divider, other.divider, t)!,
    );
  }
}
