import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import * as jestDomMatchers from '@testing-library/jest-dom/matchers';
import { describe, it, expect, vi, afterEach } from 'vitest';

expect.extend(jestDomMatchers);

// RTL can't auto-register cleanup when vitest globals are off
afterEach(() => cleanup());
import { SidebarMenu } from '../components/SidebarMenu';

const makeCategories = () => [
  {
    key: 'group-a',
    header: 'Group A',
    collapsible: true,
    defaultOpen: true,
    items: [{ name: 'Item A', href: '/a' }],
  },
  {
    key: 'group-b',
    header: 'Group B',
    collapsible: true,
    defaultOpen: true,
    items: [{ name: 'Item B', href: '/b' }],
  },
];

describe('SidebarMenu — autoCollapse', () => {
  it('collapses non-active groups when autoCollapse=true', () => {
    render(
      <SidebarMenu
        categories={makeCategories()}
        currentPath="/a"
        autoCollapse={true}
        activeGroupKey="group-a"
      />
    );
    expect(screen.getByText('Item A')).toBeInTheDocument();
    expect(screen.queryByText('Item B')).toBeNull();
  });

  it('opens the active group when autoCollapse=true', () => {
    render(
      <SidebarMenu
        categories={makeCategories()}
        currentPath="/b"
        autoCollapse={true}
        activeGroupKey="group-b"
      />
    );
    expect(screen.getByText('Item B')).toBeInTheDocument();
    expect(screen.queryByText('Item A')).toBeNull();
  });

  it('does not auto-collapse when autoCollapse is false (default)', () => {
    render(
      <SidebarMenu
        categories={makeCategories()}
        currentPath="/a"
        activeGroupKey="group-a"
      />
    );
    // Both groups should be visible when autoCollapse is off
    expect(screen.getByText('Item A')).toBeInTheDocument();
    expect(screen.getByText('Item B')).toBeInTheDocument();
  });
});

describe('SidebarMenu — defaultOpen=false', () => {
  it('starts collapsed when defaultOpen=false', () => {
    const cats = [
      {
        key: 'g',
        header: 'Hidden Group',
        collapsible: true,
        defaultOpen: false,
        items: [{ name: 'Hidden Item', href: '/h' }],
      },
    ];
    render(<SidebarMenu categories={cats} currentPath="/" />);
    expect(screen.queryByText('Hidden Item')).toBeNull();
  });
});

describe('SidebarMenu — onGroupToggle callback', () => {
  it('fires onGroupToggle when a collapsible header is clicked', () => {
    const onToggle = vi.fn();
    render(
      <SidebarMenu
        categories={makeCategories()}
        currentPath="/"
        onGroupToggle={onToggle}
      />
    );
    act(() => {
      fireEvent.click(screen.getByText('Group A'));
    });
    expect(onToggle).toHaveBeenCalledWith('group-a', expect.any(Boolean));
  });

  it('toggles group open/closed state on repeated header clicks', () => {
    const onToggle = vi.fn();
    render(
      <SidebarMenu
        categories={makeCategories()}
        currentPath="/"
        onGroupToggle={onToggle}
      />
    );
    // Initial state: open (Item A visible)
    expect(screen.getByText('Item A')).toBeInTheDocument();

    // First click: collapse
    act(() => {
      fireEvent.click(screen.getByText('Group A'));
    });
    expect(screen.queryByText('Item A')).toBeNull();

    // Second click: re-open
    act(() => {
      fireEvent.click(screen.getByText('Group A'));
    });
    expect(screen.getByText('Item A')).toBeInTheDocument();
  });
});
