import { useAuthContext } from '../components/AuthContext.js';
import { hasScope, hasAnyScope, hasAllScopes, hasRole } from '../authz/permissions.js';

export interface UsePermissionsReturn {
  hasScope: (required: string) => boolean;
  hasAnyScope: (required: string[]) => boolean;
  hasAllScopes: (required: string[]) => boolean;
  hasRole: (required: string) => boolean;
}

export function usePermissions(): UsePermissionsReturn {
  const { user } = useAuthContext();
  const scopes = user?.scope ?? [];
  const roles = user?.roles ?? [];

  return {
    hasScope: (required: string) => hasScope(scopes, required),
    hasAnyScope: (required: string[]) => hasAnyScope(scopes, required),
    hasAllScopes: (required: string[]) => hasAllScopes(scopes, required),
    hasRole: (required: string) => hasRole(roles, required),
  };
}
