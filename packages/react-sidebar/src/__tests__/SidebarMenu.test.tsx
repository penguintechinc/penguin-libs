import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SidebarMenu, SidebarMenuTrigger, MenuItem, MenuCategory } from '../SidebarMenu';

describe('SidebarMenu', () => {
  const mockMenuItems: MenuItem[] = [
    { name: 'Dashboard', href: '/dashboard' },
    { name: 'Profile', href: '/profile' },
    { name: 'Settings', href: '/settings' },
  ];

  const mockCategories: MenuCategory[] = [
    {
      header: 'Main',
      items: mockMenuItems,
      key: 'main',
    },
  ];

  const defaultProps = {
    categories: mockCategories,
    currentPath: '/dashboard',
  };

  describe('Rendering', () => {
    it('renders without crashing', () => {
      render(<SidebarMenu {...defaultProps} />);
      const navs = screen.getAllByRole('navigation');
      expect(navs.length).toBeGreaterThan(0);
    });

    it('renders all navigation items from categories', () => {
      render(<SidebarMenu {...defaultProps} />);
      expect(screen.getAllByText('Dashboard').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Profile').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Settings').length).toBeGreaterThan(0);
    });

    it('renders category headers', () => {
      render(<SidebarMenu {...defaultProps} />);
      expect(screen.getAllByText('Main').length).toBeGreaterThan(0);
    });

    it('renders footer items when provided', () => {
      const footerItems: MenuItem[] = [
        { name: 'Help', href: '/help' },
        { name: 'Logout', href: '/logout' },
      ];
      render(
        <SidebarMenu {...defaultProps} footerItems={footerItems} />
      );
      expect(screen.getByText('Help')).toBeInTheDocument();
      expect(screen.getByText('Logout')).toBeInTheDocument();
    });

    it('renders logo when provided', () => {
      const logo = <div data-testid="logo">Logo</div>;
      render(<SidebarMenu {...defaultProps} logo={logo} />);
      expect(screen.getByTestId('logo')).toBeInTheDocument();
    });
  });

  describe('Active Item Styling', () => {
    it('marks current path item as active with correct class', () => {
      render(<SidebarMenu {...defaultProps} currentPath="/dashboard" />);
      const dashboardButtons = screen.getAllByText('Dashboard');
      expect(dashboardButtons[0].closest('button')?.className).toContain('bg-primary-600');
    });

    it('applies active text color to active item', () => {
      render(<SidebarMenu {...defaultProps} currentPath="/dashboard" />);
      const dashboardButtons = screen.getAllByText('Dashboard');
      expect(dashboardButtons[0].closest('button')?.className).toContain('text-white');
    });

    it('does not mark non-current path items as active', () => {
      render(<SidebarMenu {...defaultProps} currentPath="/dashboard" />);
      const profileButtons = screen.getAllByText('Profile');
      expect(profileButtons[0].closest('button')?.className).not.toContain('bg-primary-600');
    });

    it('handles path prefix matching for subpaths', () => {
      render(<SidebarMenu {...defaultProps} currentPath="/dashboard/analytics" />);
      const dashboardButtons = screen.getAllByText('Dashboard');
      expect(dashboardButtons[0].closest('button')?.className).toContain('bg-primary-600');
    });
  });

  describe('Collapsible Categories', () => {
    it('renders collapsible category with toggle button', () => {
      const categories: MenuCategory[] = [
        {
          header: 'Main',
          items: mockMenuItems,
          collapsible: true,
          key: 'main',
        },
      ];
      render(<SidebarMenu {...defaultProps} categories={categories} />);
      const headers = screen.getAllByText('Main');
      expect(headers[0].closest('button')).toBeInTheDocument();
    });

    it('collapses category when defaultOpen is false', () => {
      const categories: MenuCategory[] = [
        {
          header: 'Collapsed',
          items: [{ name: 'CollapsedItem', href: '/collapsed' }],
          collapsible: true,
          defaultOpen: false,
          key: 'collapsed',
        },
      ];
      render(<SidebarMenu {...defaultProps} categories={categories} />);
      expect(screen.queryAllByText('CollapsedItem').length).toBe(0);
    });

    it('expands category when defaultOpen is true', () => {
      const categories: MenuCategory[] = [
        {
          header: 'Main',
          items: mockMenuItems,
          collapsible: true,
          defaultOpen: true,
          key: 'main',
        },
      ];
      render(<SidebarMenu {...defaultProps} categories={categories} />);
      expect(screen.getAllByText('Dashboard').length).toBeGreaterThan(0);
    });

    it('toggles category expansion on header click', () => {
      const categories: MenuCategory[] = [
        {
          header: 'ToggleTest',
          items: [{ name: 'ToggleItem', href: '/toggle' }],
          collapsible: true,
          defaultOpen: true,
          key: 'toggle-test',
        },
      ];
      render(<SidebarMenu {...defaultProps} categories={categories} />);
      const headers = screen.getAllByText('ToggleTest');
      const header = headers[0].closest('button');
      expect(screen.getAllByText('ToggleItem').length).toBeGreaterThan(0);
      fireEvent.click(header!);
      expect(screen.queryAllByText('ToggleItem').length).toBe(0);
      fireEvent.click(header!);
      expect(screen.getAllByText('ToggleItem').length).toBeGreaterThan(0);
    });

    it('calls onGroupToggle when category is toggled', () => {
      const onGroupToggle = vi.fn();
      const categories: MenuCategory[] = [
        {
          header: 'MainToggle',
          items: mockMenuItems,
          collapsible: true,
          defaultOpen: true,
          key: 'main',
        },
      ];
      render(
        <SidebarMenu
          {...defaultProps}
          categories={categories}
          onGroupToggle={onGroupToggle}
        />
      );
      const headers = screen.getAllByText('MainToggle');
      const header = headers[0].closest('button');
      fireEvent.click(header!);
      expect(onGroupToggle).toHaveBeenCalledWith('main', false);
    });
  });

  describe('Navigation Callback', () => {
    it('calls onNavigate when menu item is clicked', async () => {
      const onNavigate = vi.fn();
      const user = userEvent.setup();
      const categories: MenuCategory[] = [
        {
          header: 'NavTest',
          items: [{ name: 'NavItem', href: '/nav-test' }],
          key: 'nav-test',
        },
      ];
      render(
        <SidebarMenu {...defaultProps} categories={categories} onNavigate={onNavigate} />
      );
      const navItems = screen.getAllByText('NavItem');
      await user.click(navItems[0].closest('button')!);
      expect(onNavigate).toHaveBeenCalledWith('/nav-test');
    });

    it('calls onNavigate with correct href for footer items', async () => {
      const onNavigate = vi.fn();
      const user = userEvent.setup();
      const footerItems: MenuItem[] = [{ name: 'LogoutFooterItem', href: '/logout' }];
      render(
        <SidebarMenu
          {...defaultProps}
          footerItems={footerItems}
          onNavigate={onNavigate}
        />
      );
      const logoutButtons = screen.getAllByText('LogoutFooterItem');
      await user.click(logoutButtons[0].closest('button')!);
      expect(onNavigate).toHaveBeenCalledWith('/logout');
    });

    it('closes mobile sidebar when closeOnNavigate is true', async () => {
      const onMobileClose = vi.fn();
      const user = userEvent.setup();
      const categories: MenuCategory[] = [
        {
          header: 'MobileNav',
          items: [{ name: 'MobileNavItem', href: '/mobile-nav' }],
          key: 'mobile-nav',
        },
      ];
      render(
        <SidebarMenu
          {...defaultProps}
          categories={categories}
          mobileOpen={true}
          onMobileClose={onMobileClose}
          closeOnNavigate={true}
        />
      );
      const navItems = screen.getAllByText('MobileNavItem');
      await user.click(navItems[navItems.length - 1].closest('button')!);
      expect(onMobileClose).toHaveBeenCalled();
    });
  });

  describe('Role-Based Visibility', () => {
    it('renders items without role restrictions', () => {
      render(<SidebarMenu {...defaultProps} />);
      expect(screen.getAllByText('Dashboard').length).toBeGreaterThan(0);
    });

    it('shows items with matching user role', () => {
      const categories: MenuCategory[] = [
        {
          header: 'Main',
          items: [
            { name: 'Admin Panel', href: '/admin', roles: ['admin'] },
          ],
          key: 'main',
        },
      ];
      render(
        <SidebarMenu {...defaultProps} categories={categories} userRole="admin" />
      );
      expect(screen.getAllByText('Admin Panel').length).toBeGreaterThan(0);
    });

    it('hides items without matching user role', () => {
      const categories: MenuCategory[] = [
        {
          header: 'Admin Only',
          items: [
            { name: 'Admin Panel Only', href: '/admin', roles: ['admin'] },
          ],
          key: 'admin-only',
        },
      ];
      render(
        <SidebarMenu {...defaultProps} categories={categories} userRole="viewer" />
      );
      expect(screen.queryAllByText('Admin Panel Only').length).toBe(0);
    });

    it('hides all role-restricted items when no userRole provided', () => {
      const categories: MenuCategory[] = [
        {
          header: 'Restricted',
          items: [
            { name: 'Restricted Admin', href: '/admin', roles: ['admin'] },
          ],
          key: 'restricted',
        },
      ];
      render(<SidebarMenu {...defaultProps} categories={categories} />);
      expect(screen.queryAllByText('Restricted Admin').length).toBe(0);
    });

    it('shows items with multiple matching roles', () => {
      const categories: MenuCategory[] = [
        {
          header: 'Main',
          items: [
            { name: 'Reports', href: '/reports', roles: ['admin', 'maintainer'] },
          ],
          key: 'main',
        },
      ];
      render(
        <SidebarMenu {...defaultProps} categories={categories} userRole="maintainer" />
      );
      expect(screen.getAllByText('Reports').length).toBeGreaterThan(0);
    });

    it('hides empty categories when all items are filtered by role', () => {
      const categories: MenuCategory[] = [
        {
          header: 'Admin',
          items: [
            { name: 'User Management', href: '/users', roles: ['admin'] },
          ],
          key: 'admin',
        },
      ];
      render(
        <SidebarMenu {...defaultProps} categories={categories} userRole="viewer" />
      );
      expect(screen.queryAllByText('Admin').length).toBe(0);
      expect(screen.queryAllByText('User Management').length).toBe(0);
    });
  });

  describe('Accessibility (ARIA)', () => {
    it('renders nav with role="navigation"', () => {
      render(<SidebarMenu {...defaultProps} />);
      const navs = screen.getAllByRole('navigation');
      expect(navs.length).toBeGreaterThan(0);
    });

    it('menu items have accessible names', () => {
      render(<SidebarMenu {...defaultProps} />);
      const dashboardButtons = screen.getAllByText('Dashboard');
      expect(dashboardButtons[0].closest('button')).toHaveAccessibleName('Dashboard');
    });

    it('category headers have accessible names', () => {
      const categories: MenuCategory[] = [
        {
          header: 'Main Navigation',
          items: mockMenuItems,
          key: 'main',
        },
      ];
      render(<SidebarMenu {...defaultProps} categories={categories} />);
      const headers = screen.getAllByText('Main Navigation');
      expect(headers[0].closest('button')).toHaveAccessibleName('Main Navigation');
    });
  });

  describe('Theme Configuration', () => {
    it('renders with dark theme by default', () => {
      const { container } = render(
        <SidebarMenu {...defaultProps} themeMode="dark" />
      );
      const sidebar = container.querySelector('[class*="bg-slate"]');
      expect(sidebar).toBeInTheDocument();
    });

    it('renders with light theme when specified', () => {
      const { container } = render(
        <SidebarMenu {...defaultProps} themeMode="light" />
      );
      const sidebar = container.querySelector('[class*="bg-white"]');
      expect(sidebar).toBeInTheDocument();
    });
  });

  describe('Auto Collapse Feature', () => {
    it('collapses all groups except active when autoCollapse is enabled', () => {
      const categories: MenuCategory[] = [
        {
          header: 'Main',
          items: [{ name: 'Dashboard Item', href: '/dashboard' }],
          collapsible: true,
          key: 'main',
        },
        {
          header: 'Settings',
          items: [{ name: 'Profile Item', href: '/profile' }],
          collapsible: true,
          key: 'settings',
        },
      ];
      render(
        <SidebarMenu
          {...defaultProps}
          categories={categories}
          autoCollapse={true}
          activeGroupKey="main"
        />
      );
      expect(screen.getByText('Dashboard Item')).toBeInTheDocument();
      expect(screen.queryByText('Profile Item')).not.toBeInTheDocument();
    });
  });

  describe('Mobile Sidebar', () => {
    it('does not render mobile overlay when mobileOpen is undefined', () => {
      const { container } = render(
        <SidebarMenu {...defaultProps} />
      );
      const overlay = container.querySelector('[aria-hidden]');
      expect(overlay).not.toBeInTheDocument();
    });

    it('renders mobile overlay when mobileOpen is true', () => {
      const { container } = render(
        <SidebarMenu
          {...defaultProps}
          mobileOpen={true}
          onMobileClose={() => {}}
        />
      );
      const overlay = container.querySelector('[aria-hidden="false"]');
      expect(overlay).toBeInTheDocument();
    });

    it('closes overlay when backdrop is clicked', () => {
      const onMobileClose = vi.fn();
      const { container } = render(
        <SidebarMenu
          {...defaultProps}
          mobileOpen={true}
          onMobileClose={onMobileClose}
        />
      );
      const backdrop = container.querySelector('.bg-black\\/50');
      fireEvent.click(backdrop!);
      expect(onMobileClose).toHaveBeenCalled();
    });

    it('closes overlay on Escape key', () => {
      const onMobileClose = vi.fn();
      render(
        <SidebarMenu
          {...defaultProps}
          mobileOpen={true}
          onMobileClose={onMobileClose}
        />
      );
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(onMobileClose).toHaveBeenCalled();
    });
  });
});

describe('SidebarMenuTrigger', () => {
  it('renders without crashing', () => {
    const onClick = vi.fn();
    const { container } = render(
      <SidebarMenuTrigger onClick={onClick} />
    );
    const button = container.querySelector('button');
    expect(button).toBeInTheDocument();
  });

  it('calls onClick when clicked', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { container } = render(
      <SidebarMenuTrigger onClick={onClick} />
    );
    const button = container.querySelector('button');
    await user.click(button!);
    expect(onClick).toHaveBeenCalled();
  });

  it('shows hamburger icon when closed', () => {
    const onClick = vi.fn();
    const { container } = render(
      <SidebarMenuTrigger onClick={onClick} isOpen={false} />
    );
    const svg = container.querySelectorAll('svg');
    expect(svg.length).toBeGreaterThan(0);
  });

  it('shows X icon when open', () => {
    const onClick = vi.fn();
    const { container } = render(
      <SidebarMenuTrigger onClick={onClick} isOpen={true} />
    );
    const svg = container.querySelectorAll('svg');
    expect(svg.length).toBeGreaterThan(0);
  });

  it('has correct aria-label when closed', () => {
    const onClick = vi.fn();
    const { container } = render(
      <SidebarMenuTrigger onClick={onClick} isOpen={false} />
    );
    const button = container.querySelector('button');
    expect(button).toHaveAttribute('aria-label', 'Open sidebar');
  });

  it('has correct aria-label when open', () => {
    const onClick = vi.fn();
    const { container } = render(
      <SidebarMenuTrigger onClick={onClick} isOpen={true} />
    );
    const button = container.querySelector('button');
    expect(button).toHaveAttribute('aria-label', 'Close sidebar');
  });

  it('applies custom className', () => {
    const onClick = vi.fn();
    const { container } = render(
      <SidebarMenuTrigger
        onClick={onClick}
        className="custom-class"
      />
    );
    const button = container.querySelector('button');
    expect(button).toHaveClass('custom-class');
  });

  it('respects theme configuration', () => {
    const onClick = vi.fn();
    const { container } = render(
      <SidebarMenuTrigger
        onClick={onClick}
        themeMode="light"
      />
    );
    const button = container.querySelector('button');
    expect(button).toBeInTheDocument();
  });

  it('applies custom colors', () => {
    const onClick = vi.fn();
    const { container } = render(
      <SidebarMenuTrigger
        onClick={onClick}
        themeMode="dark"
        colors={{ menuItemText: 'text-custom' }}
      />
    );
    const button = container.querySelector('button');
    expect(button).toBeInTheDocument();
  });
});
