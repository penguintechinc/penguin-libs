import 'package:flutter/material.dart';

/// A single menu item in the sidebar.
class MenuItem {
  const MenuItem({
    required this.name,
    required this.href,
    this.icon,
    this.roles,
  });

  final String name;
  final String href;
  final IconData? icon;
  final List<String>? roles;
}

/// A category of menu items, optionally collapsible.
class MenuCategory {
  const MenuCategory({
    this.header,
    this.collapsible = true,
    required this.items,
  });

  final String? header;
  final bool collapsible;
  final List<MenuItem> items;
}
