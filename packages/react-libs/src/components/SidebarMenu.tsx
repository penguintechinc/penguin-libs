import React, { useState, useEffect, useCallback, ReactNode } from 'react';

export interface MenuItem {
  name: string;
  href: string;
  icon?: React.ComponentType<{ className?: string }>;
  roles?: string[];
}

export interface MenuCategory {
  header?: string;
  collapsible?: boolean;
  items: MenuItem[];
}

export interface SidebarColorConfig {
  // Sidebar colors
  sidebarBackground: string;
  sidebarBorder: string;

  // Header/Logo section
  logoSectionBorder: string;

  // Navigation colors
  categoryHeaderText: string;
  menuItemText: string;
  menuItemHover: string;
  menuItemActive: string;
  menuItemActiveText: string;

  // Collapse indicator
  collapseIndicator: string;

  // Footer section
  footerBorder: string;
  footerButtonText: string;
  footerButtonHover: string;

  // Scrollbar
  scrollbarTrack: string;
  scrollbarThumb: string;
  scrollbarThumbHover: string;
}

export interface SidebarMenuProps {
  logo?: ReactNode;
  categories: MenuCategory[];
  currentPath: string;
  onNavigate?: (href: string) => void;
  footerItems?: MenuItem[];
  userRole?: string;
  width?: string;
  colors?: SidebarColorConfig;
  collapseIcon?: React.ComponentType<{ className?: string }>;
  expandIcon?: React.ComponentType<{ className?: string }>;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
  closeOnNavigate?: boolean;
}

export interface SidebarMenuTriggerProps {
  onClick: () => void;
  className?: string;
  colors?: SidebarColorConfig;
  isOpen?: boolean;
}

// Default Elder-inspired color scheme (slate dark with blue accent)
const DEFAULT_COLORS: SidebarColorConfig = {
  sidebarBackground: 'bg-slate-800',
  sidebarBorder: 'border-slate-700',
  logoSectionBorder: 'border-slate-700',
  categoryHeaderText: 'text-slate-400',
  menuItemText: 'text-slate-300',
  menuItemHover: 'hover:bg-slate-700 hover:text-white',
  menuItemActive: 'bg-primary-600',
  menuItemActiveText: 'text-white',
  collapseIndicator: 'text-slate-400',
  footerBorder: 'border-slate-700',
  footerButtonText: 'text-slate-300',
  footerButtonHover: 'hover:bg-slate-700 hover:text-white',
  scrollbarTrack: 'bg-slate-800',
  scrollbarThumb: 'bg-slate-600',
  scrollbarThumbHover: 'hover:bg-slate-500',
};

// Default collapse/expand icons (simple chevron)
const DefaultChevronDown: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
  </svg>
);

const DefaultChevronRight: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
  </svg>
);

/**
 * Hamburger / X trigger button for mobile sidebar.
 * Uses `lg:hidden` so it automatically hides on desktop.
 */
export const SidebarMenuTrigger: React.FC<SidebarMenuTriggerProps> = ({
  onClick,
  className = '',
  colors,
  isOpen = false,
}) => {
  const theme = colors || DEFAULT_COLORS;

  return (
    <button
      type="button"
      onClick={onClick}
      className={`lg:hidden inline-flex items-center justify-center p-2 rounded-md ${theme.menuItemText} ${theme.menuItemHover} focus:outline-none focus:ring-2 focus:ring-inset focus:ring-white ${className}`}
      aria-label={isOpen ? 'Close sidebar' : 'Open sidebar'}
    >
      {isOpen ? (
        <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      ) : (
        <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      )}
    </button>
  );
};

export const SidebarMenu: React.FC<SidebarMenuProps> = ({
  logo,
  categories,
  currentPath,
  onNavigate,
  footerItems = [],
  userRole,
  width = 'w-64',
  colors,
  collapseIcon: CollapseIcon = DefaultChevronDown,
  expandIcon: ExpandIcon = DefaultChevronRight,
  mobileOpen,
  onMobileClose,
  closeOnNavigate = true,
}) => {
  const [collapsedCategories, setCollapsedCategories] = useState<Record<string, boolean>>({});
  const theme = colors || DEFAULT_COLORS;

  const toggleCategory = (header: string) => {
    setCollapsedCategories((prev) => ({
      ...prev,
      [header]: !prev[header],
    }));
  };

  const isActive = (itemHref: string) => {
    return currentPath === itemHref || (itemHref !== '/' && currentPath.startsWith(itemHref));
  };

  const handleItemClick = (href: string) => {
    if (onNavigate) {
      onNavigate(href);
    }
    if (closeOnNavigate && onMobileClose) {
      onMobileClose();
    }
  };

  const hasPermission = (item: MenuItem): boolean => {
    if (!item.roles || item.roles.length === 0) return true;
    if (!userRole) return false;
    return item.roles.includes(userRole);
  };

  // Body scroll lock for mobile overlay
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [mobileOpen]);

  // Escape key handler for mobile overlay
  const handleEscape = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape' && mobileOpen && onMobileClose) {
        onMobileClose();
      }
    },
    [mobileOpen, onMobileClose]
  );

  useEffect(() => {
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [handleEscape]);

  const scrollbarStyles = (id: string) => `
    #${id}::-webkit-scrollbar {
      width: 10px;
    }
    #${id}::-webkit-scrollbar-track {
      background: transparent;
    }
    #${id}::-webkit-scrollbar-thumb {
      background: ${theme.scrollbarThumb.replace('bg-', '#')};
      border-radius: 5px;
    }
    #${id}::-webkit-scrollbar-thumb:hover {
      background: ${theme.scrollbarThumbHover.replace('hover:bg-', '#')};
    }
  `;

  const renderSidebarContent = (navId: string) => (
    <>
      {/* Logo Section */}
      {logo && (
        <div className={`flex items-center justify-center h-16 px-6 border-b ${theme.logoSectionBorder}`}>
          {logo}
        </div>
      )}

      {/* Navigation - Scrollable */}
      <nav id={navId} className="flex-1 px-4 py-6 overflow-y-auto">
        <style>{scrollbarStyles(navId)}</style>

        <div className="space-y-6">
          {categories.map((category, categoryIndex) => {
            const isCollapsed = category.header ? collapsedCategories[category.header] : false;
            const visibleItems = category.items.filter((item) => hasPermission(item));

            if (visibleItems.length === 0) return null;

            return (
              <div key={category.header || `category-${categoryIndex}`}>
                {/* Category Header */}
                {category.header && (
                  <button
                    onClick={() => category.collapsible && toggleCategory(category.header!)}
                    className={`flex items-center justify-between w-full px-4 py-2 text-xs font-semibold uppercase tracking-wider ${theme.categoryHeaderText} ${
                      category.collapsible ? 'cursor-pointer hover:text-slate-300' : ''
                    }`}
                  >
                    <span>{category.header}</span>
                    {category.collapsible && (
                      <span className={theme.collapseIndicator}>
                        {isCollapsed ? <ExpandIcon className="w-3 h-3" /> : <CollapseIcon className="w-3 h-3" />}
                      </span>
                    )}
                  </button>
                )}

                {/* Menu Items */}
                {!isCollapsed && (
                  <div className="space-y-1 mt-2">
                    {visibleItems.map((item) => {
                      const Icon = item.icon;
                      const active = isActive(item.href);

                      return (
                        <button
                          key={item.name}
                          onClick={() => handleItemClick(item.href)}
                          className={`flex items-center w-full px-4 py-3 text-sm font-medium rounded-lg transition-colors ${
                            active
                              ? `${theme.menuItemActive} ${theme.menuItemActiveText}`
                              : `${theme.menuItemText} ${theme.menuItemHover}`
                          }`}
                        >
                          {Icon && <Icon className="w-5 h-5 mr-3 flex-shrink-0" />}
                          <span className="truncate">{item.name}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </nav>

      {/* Footer Section - Sticky Bottom */}
      {footerItems.length > 0 && (
        <div className={`p-4 border-t ${theme.footerBorder} space-y-1`}>
          {footerItems.filter(hasPermission).map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);

            return (
              <button
                key={item.name}
                onClick={() => handleItemClick(item.href)}
                className={`flex items-center w-full px-4 py-3 text-sm font-medium rounded-lg transition-colors ${
                  active
                    ? `${theme.menuItemActive} ${theme.menuItemActiveText}`
                    : `${theme.footerButtonText} ${theme.footerButtonHover}`
                }`}
              >
                {Icon && <Icon className="w-5 h-5 mr-3 flex-shrink-0" />}
                <span className="truncate">{item.name}</span>
              </button>
            );
          })}
        </div>
      )}
    </>
  );

  const hasMobileSupport = mobileOpen !== undefined && onMobileClose !== undefined;

  return (
    <>
      {/* Desktop sidebar - always rendered, hidden below lg */}
      <div className={`hidden lg:flex fixed inset-y-0 left-0 ${width} ${theme.sidebarBackground} border-r ${theme.sidebarBorder} flex-col`}>
        {renderSidebarContent('sidebar-nav-desktop')}
      </div>

      {/* Mobile overlay - only when mobileOpen/onMobileClose are provided */}
      {hasMobileSupport && (
        <div
          className={`lg:hidden fixed inset-0 z-40 ${mobileOpen ? '' : 'pointer-events-none'}`}
          aria-hidden={!mobileOpen}
        >
          {/* Backdrop */}
          <div
            className={`fixed inset-0 bg-black/50 transition-opacity duration-300 ${
              mobileOpen ? 'opacity-100' : 'opacity-0'
            }`}
            onClick={onMobileClose}
          />

          {/* Sidebar panel */}
          <div
            className={`fixed inset-y-0 left-0 ${width} ${theme.sidebarBackground} border-r ${theme.sidebarBorder} flex flex-col z-50 transform transition-transform duration-300 ease-in-out ${
              mobileOpen ? 'translate-x-0' : '-translate-x-full'
            }`}
          >
            {renderSidebarContent('sidebar-nav-mobile')}
          </div>
        </div>
      )}
    </>
  );
};
