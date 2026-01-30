import 'package:flutter/material.dart';
import '../theme/elder_colors.dart';

/// Color configuration for [SidebarMenu].
class SidebarColorConfig {
  const SidebarColorConfig({
    this.sidebarBackground = ElderColors.slate800,
    this.sidebarBorder = ElderColors.slate700,
    this.categoryHeaderText = ElderColors.slate400,
    this.menuItemText = ElderColors.slate300,
    this.menuItemHover = ElderColors.slate700,
    this.menuItemActive = ElderColors.amber500,
    this.menuItemActiveText = ElderColors.white,
    this.scrollbarTrack = ElderColors.slate800,
    this.scrollbarThumb = ElderColors.slate600,
    this.scrollbarThumbHover = ElderColors.slate500,
    this.logoBackground = ElderColors.slate900,
    this.footerBackground = ElderColors.slate900,
    this.footerText = ElderColors.slate400,
  });

  final Color sidebarBackground;
  final Color sidebarBorder;
  final Color categoryHeaderText;
  final Color menuItemText;
  final Color menuItemHover;
  final Color menuItemActive;
  final Color menuItemActiveText;
  final Color scrollbarTrack;
  final Color scrollbarThumb;
  final Color scrollbarThumbHover;
  final Color logoBackground;
  final Color footerBackground;
  final Color footerText;

  /// Default Elder dark theme configuration.
  static const SidebarColorConfig elder = SidebarColorConfig();
}
