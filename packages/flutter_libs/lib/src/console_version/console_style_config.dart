import 'package:flutter/material.dart';
import '../theme/elder_colors.dart';

/// Style configuration for console version logging.
class ConsoleStyleConfig {
  const ConsoleStyleConfig({
    this.primaryColor = ElderColors.amber500,
    this.secondaryColor = ElderColors.slate500,
    this.accentColor = ElderColors.amber400,
    this.backgroundColor = ElderColors.slate900,
    this.fontFamily = 'monospace',
  });

  final Color primaryColor;
  final Color secondaryColor;
  final Color accentColor;
  final Color backgroundColor;
  final String fontFamily;

  /// Default Elder theme style.
  static const ConsoleStyleConfig elder = ConsoleStyleConfig();
}
