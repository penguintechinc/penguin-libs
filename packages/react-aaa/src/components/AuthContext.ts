import { createContext, useContext } from 'react';
import type { Claims } from '../authn/types.js';
import type { AuditEmitter } from '../audit/emitter.js';

export interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: Claims | null;
  accessToken: string | null;
  login: () => Promise<void>;
  logout: () => void;
  emitter: AuditEmitter | null;
}

export const AuthContext = createContext<AuthContextValue>({
  isAuthenticated: false,
  isLoading: false,
  user: null,
  accessToken: null,
  login: async () => {},
  logout: () => {},
  emitter: null,
});

export function useAuthContext(): AuthContextValue {
  return useContext(AuthContext);
}
