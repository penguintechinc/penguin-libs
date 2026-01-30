import 'package:flutter/material.dart';
import '../theme/elder_colors.dart';
import 'sidebar_types.dart';
import 'sidebar_color_config.dart';

/// A sidebar navigation menu with collapsible categories and role-based filtering.
///
/// Supports an optional logo at the top and a sticky footer section.
class SidebarMenu extends StatefulWidget {
  const SidebarMenu({
    super.key,
    required this.categories,
    this.activePath,
    this.userRole,
    this.logo,
    this.footerWidget,
    this.onItemTap,
    this.colorConfig = SidebarColorConfig.elder,
    this.width = 256,
  });

  final List<MenuCategory> categories;
  final String? activePath;
  final String? userRole;
  final Widget? logo;
  final Widget? footerWidget;
  final void Function(MenuItem item)? onItemTap;
  final SidebarColorConfig colorConfig;
  final double width;

  @override
  State<SidebarMenu> createState() => _SidebarMenuState();
}

class _SidebarMenuState extends State<SidebarMenu> {
  final Map<String, bool> _expandedState = {};

  bool _hasPermission(MenuItem item) {
    if (item.roles == null || item.roles!.isEmpty) return true;
    if (widget.userRole == null) return false;
    return item.roles!.contains(widget.userRole);
  }

  bool _isActive(MenuItem item) {
    if (widget.activePath == null) return false;
    return widget.activePath == item.href ||
        widget.activePath!.startsWith(item.href);
  }

  @override
  Widget build(BuildContext context) {
    final colors = widget.colorConfig;

    return Container(
      width: widget.width,
      decoration: BoxDecoration(
        color: colors.sidebarBackground,
        border: Border(
          right: BorderSide(color: colors.sidebarBorder),
        ),
      ),
      child: Column(
        children: [
          // Logo section
          if (widget.logo != null)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: colors.logoBackground,
                border: Border(
                  bottom: BorderSide(color: colors.sidebarBorder),
                ),
              ),
              child: widget.logo,
            ),

          // Menu items
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(vertical: 8),
              children: widget.categories.map((category) {
                final visibleItems = category.items
                    .where(_hasPermission)
                    .toList();

                if (visibleItems.isEmpty) {
                  return const SizedBox.shrink();
                }

                if (category.header == null) {
                  return Column(
                    children: visibleItems
                        .map((item) => _buildMenuItem(item, colors))
                        .toList(),
                  );
                }

                final key = category.header!;
                final isExpanded = _expandedState[key] ?? true;

                if (!category.collapsible) {
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _buildCategoryHeader(key, colors),
                      ...visibleItems
                          .map((item) => _buildMenuItem(item, colors)),
                    ],
                  );
                }

                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    InkWell(
                      onTap: () {
                        setState(() {
                          _expandedState[key] = !isExpanded;
                        });
                      },
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 8,
                        ),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(
                                key.toUpperCase(),
                                style: TextStyle(
                                  color: colors.categoryHeaderText,
                                  fontSize: 11,
                                  fontWeight: FontWeight.w600,
                                  letterSpacing: 0.5,
                                ),
                              ),
                            ),
                            Icon(
                              isExpanded
                                  ? Icons.expand_less
                                  : Icons.expand_more,
                              color: colors.categoryHeaderText,
                              size: 16,
                            ),
                          ],
                        ),
                      ),
                    ),
                    if (isExpanded)
                      ...visibleItems
                          .map((item) => _buildMenuItem(item, colors)),
                  ],
                );
              }).toList(),
            ),
          ),

          // Footer
          if (widget.footerWidget != null)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: colors.footerBackground,
                border: Border(
                  top: BorderSide(color: colors.sidebarBorder),
                ),
              ),
              child: widget.footerWidget,
            ),
        ],
      ),
    );
  }

  Widget _buildCategoryHeader(String header, SidebarColorConfig colors) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
      child: Text(
        header.toUpperCase(),
        style: TextStyle(
          color: colors.categoryHeaderText,
          fontSize: 11,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.5,
        ),
      ),
    );
  }

  Widget _buildMenuItem(MenuItem item, SidebarColorConfig colors) {
    final active = _isActive(item);

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: () => widget.onItemTap?.call(item),
        hoverColor: colors.menuItemHover,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          decoration: active
              ? BoxDecoration(
                  color: colors.menuItemActive.withAlpha(25),
                  border: Border(
                    left: BorderSide(
                      color: colors.menuItemActive,
                      width: 3,
                    ),
                  ),
                )
              : null,
          child: Row(
            children: [
              if (item.icon != null) ...[
                Icon(
                  item.icon,
                  color: active
                      ? colors.menuItemActive
                      : colors.menuItemText,
                  size: 18,
                ),
                const SizedBox(width: 12),
              ],
              Expanded(
                child: Text(
                  item.name,
                  style: TextStyle(
                    color: active
                        ? colors.menuItemActiveText
                        : colors.menuItemText,
                    fontSize: 14,
                    fontWeight:
                        active ? FontWeight.w600 : FontWeight.normal,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
