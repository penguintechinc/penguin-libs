import { type ReactNode } from 'react';
import { useAuth } from '../hooks/useAuth.js';
import { usePermissions } from '../hooks/usePermissions.js';

export interface ProtectedRouteProps {
  children: ReactNode;
  requiredScopes?: string[];
  requiredRole?: string;
  loginPath?: string;
  forbiddenFallback?: ReactNode;
  loadingFallback?: ReactNode;
}

export function ProtectedRoute({
  children,
  requiredScopes,
  requiredRole,
  loginPath = '/login',
  forbiddenFallback = null,
  loadingFallback = null,
}: ProtectedRouteProps): ReactNode {
  const { isAuthenticated, isLoading } = useAuth();
  const permissions = usePermissions();

  if (isLoading) {
    return loadingFallback;
  }

  if (!isAuthenticated) {
    window.location.href = loginPath;
    return null;
  }

  const scopesDenied = requiredScopes && requiredScopes.length > 0 && !permissions.hasAllScopes(requiredScopes);
  const roleDenied = requiredRole && !permissions.hasRole(requiredRole);

  if (scopesDenied || roleDenied) {
    return forbiddenFallback;
  }

  return children;
}
