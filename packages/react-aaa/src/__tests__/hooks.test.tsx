import { describe, it, expect, vi } from 'vitest';
import { render, screen, renderHook } from '@testing-library/react';
import { type ReactNode } from 'react';
import { AuthContext } from '../components/AuthContext.js';
import { useAuth } from '../hooks/useAuth.js';
import { usePermissions } from '../hooks/usePermissions.js';
import { useAuditLog } from '../hooks/useAuditLog.js';
import type { AuthContextValue } from '../components/AuthContext.js';
import type { Claims } from '../authn/types.js';

const mockClaims: Claims = {
  sub: 'user-123',
  iss: 'https://auth.example.com',
  aud: ['my-app'],
  iat: new Date(),
  exp: new Date(Date.now() + 3600 * 1000),
  scope: ['read', 'write'],
  roles: ['admin'],
};

function makeContextValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    isAuthenticated: true,
    isLoading: false,
    user: mockClaims,
    accessToken: 'test-token',
    login: vi.fn(),
    logout: vi.fn(),
    emitter: null,
    ...overrides,
  };
}

function TestWrapper({ children, value }: { children: ReactNode; value: AuthContextValue }): JSX.Element {
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

describe('useAuth', () => {
  it('returns authentication state from context', () => {
    const value = makeContextValue();
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.user).toEqual(mockClaims);
    expect(result.current.accessToken).toBe('test-token');
  });

  it('returns not-authenticated state', () => {
    const value = makeContextValue({
      isAuthenticated: false,
      user: null,
      accessToken: null,
    });
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
  });

  it('exposes login and logout functions', () => {
    const login = vi.fn();
    const logout = vi.fn();
    const value = makeContextValue({ login, logout });

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    expect(result.current.login).toBe(login);
    expect(result.current.logout).toBe(logout);
  });
});

describe('usePermissions', () => {
  it('hasScope returns true for granted scope', () => {
    const value = makeContextValue();
    const { result } = renderHook(() => usePermissions(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    expect(result.current.hasScope('read')).toBe(true);
  });

  it('hasScope returns false for missing scope', () => {
    const value = makeContextValue();
    const { result } = renderHook(() => usePermissions(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    expect(result.current.hasScope('delete')).toBe(false);
  });

  it('hasAnyScope returns true when one scope matches', () => {
    const value = makeContextValue();
    const { result } = renderHook(() => usePermissions(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    expect(result.current.hasAnyScope(['delete', 'write'])).toBe(true);
  });

  it('hasAllScopes returns false when one scope is missing', () => {
    const value = makeContextValue();
    const { result } = renderHook(() => usePermissions(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    expect(result.current.hasAllScopes(['read', 'delete'])).toBe(false);
  });

  it('hasRole returns true for granted role', () => {
    const value = makeContextValue();
    const { result } = renderHook(() => usePermissions(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    expect(result.current.hasRole('admin')).toBe(true);
  });

  it('hasRole returns false for missing role', () => {
    const value = makeContextValue();
    const { result } = renderHook(() => usePermissions(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    expect(result.current.hasRole('superadmin')).toBe(false);
  });

  it('returns false for all checks when user is null', () => {
    const value = makeContextValue({ user: null, isAuthenticated: false });
    const { result } = renderHook(() => usePermissions(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    expect(result.current.hasScope('read')).toBe(false);
    expect(result.current.hasAnyScope(['read'])).toBe(false);
    expect(result.current.hasAllScopes(['read'])).toBe(false);
    expect(result.current.hasRole('admin')).toBe(false);
  });
});

describe('useAuditLog', () => {
  it('emit calls emitter.emit when emitter is present', () => {
    const mockEmit = vi.fn();
    const value = makeContextValue({
      emitter: { emit: mockEmit, flush: vi.fn(), destroy: vi.fn() } as unknown as ReturnType<typeof makeContextValue>['emitter'],
    });

    const { result } = renderHook(() => useAuditLog(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    const event = {
      type: 'auth.login' as const,
      outcome: 'success' as const,
      actor: { sub: 'user-123' },
    };

    result.current.emit(event);
    expect(mockEmit).toHaveBeenCalledWith(event);
  });

  it('emit is a no-op when emitter is null', () => {
    const value = makeContextValue({ emitter: null });
    const { result } = renderHook(() => useAuditLog(), {
      wrapper: ({ children }) => <TestWrapper value={value}>{children}</TestWrapper>,
    });

    expect(() =>
      result.current.emit({
        type: 'auth.login',
        outcome: 'success',
        actor: { sub: 'user-123' },
      }),
    ).not.toThrow();
  });
});

describe('AuthContext default values', () => {
  it('renders with default context values', () => {
    function TestComponent(): JSX.Element {
      const { isAuthenticated } = useAuth();
      return <div>{isAuthenticated ? 'authenticated' : 'not-authenticated'}</div>;
    }

    render(<TestComponent />);
    expect(screen.getByText('not-authenticated')).toBeTruthy();
  });
});
