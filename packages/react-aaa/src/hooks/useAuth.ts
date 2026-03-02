import { useAuthContext } from '../components/AuthContext.js';
import type { Claims } from '../authn/types.js';

export interface UseAuthReturn {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: Claims | null;
  accessToken: string | null;
  login: () => Promise<void>;
  logout: () => void;
}

export function useAuth(): UseAuthReturn {
  const { isAuthenticated, isLoading, user, accessToken, login, logout } = useAuthContext();
  return { isAuthenticated, isLoading, user, accessToken, login, logout };
}
