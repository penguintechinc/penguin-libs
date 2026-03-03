import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AuthContext } from '../components/AuthContext.js';
import { ProtectedRoute } from '../components/ProtectedRoute.js';
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

describe('ProtectedRoute', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'location', {
      value: { href: '' },
      writable: true,
    });
  });

  it('renders children when authenticated', () => {
    render(
      <AuthContext.Provider value={makeContextValue()}>
        <ProtectedRoute>
          <div>Protected Content</div>
        </ProtectedRoute>
      </AuthContext.Provider>,
    );

    expect(screen.getByText('Protected Content')).toBeTruthy();
  });

  it('redirects to login path when not authenticated', () => {
    render(
      <AuthContext.Provider value={makeContextValue({ isAuthenticated: false, accessToken: null })}>
        <ProtectedRoute loginPath="/login">
          <div>Protected Content</div>
        </ProtectedRoute>
      </AuthContext.Provider>,
    );

    expect(window.location.href).toBe('/login');
    expect(screen.queryByText('Protected Content')).toBeNull();
  });

  it('shows loading fallback when isLoading is true', () => {
    render(
      <AuthContext.Provider value={makeContextValue({ isLoading: true })}>
        <ProtectedRoute loadingFallback={<div>Loading...</div>}>
          <div>Protected Content</div>
        </ProtectedRoute>
      </AuthContext.Provider>,
    );

    expect(screen.getByText('Loading...')).toBeTruthy();
    expect(screen.queryByText('Protected Content')).toBeNull();
  });

  it('shows forbidden fallback when required scope is missing', () => {
    render(
      <AuthContext.Provider value={makeContextValue()}>
        <ProtectedRoute
          requiredScopes={['delete']}
          forbiddenFallback={<div>Access Denied</div>}
        >
          <div>Protected Content</div>
        </ProtectedRoute>
      </AuthContext.Provider>,
    );

    expect(screen.getByText('Access Denied')).toBeTruthy();
    expect(screen.queryByText('Protected Content')).toBeNull();
  });

  it('renders children when required scope is present', () => {
    render(
      <AuthContext.Provider value={makeContextValue()}>
        <ProtectedRoute requiredScopes={['read']}>
          <div>Protected Content</div>
        </ProtectedRoute>
      </AuthContext.Provider>,
    );

    expect(screen.getByText('Protected Content')).toBeTruthy();
  });

  it('shows forbidden fallback when required role is missing', () => {
    render(
      <AuthContext.Provider value={makeContextValue()}>
        <ProtectedRoute
          requiredRole="superadmin"
          forbiddenFallback={<div>Forbidden</div>}
        >
          <div>Protected Content</div>
        </ProtectedRoute>
      </AuthContext.Provider>,
    );

    expect(screen.getByText('Forbidden')).toBeTruthy();
    expect(screen.queryByText('Protected Content')).toBeNull();
  });

  it('renders children when required role is present', () => {
    render(
      <AuthContext.Provider value={makeContextValue()}>
        <ProtectedRoute requiredRole="admin">
          <div>Protected Content</div>
        </ProtectedRoute>
      </AuthContext.Provider>,
    );

    expect(screen.getByText('Protected Content')).toBeTruthy();
  });

  it('renders children with no scope or role requirements', () => {
    render(
      <AuthContext.Provider value={makeContextValue()}>
        <ProtectedRoute>
          <div>Open Protected</div>
        </ProtectedRoute>
      </AuthContext.Provider>,
    );

    expect(screen.getByText('Open Protected')).toBeTruthy();
  });
});
