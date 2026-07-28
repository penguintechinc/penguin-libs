import { useState, useEffect, useCallback, type ReactNode } from 'react';
import { decodeJwt } from 'jose';
import { OIDCClient } from '../authn/oidc-client.js';
import { TokenManager } from '../authn/token-manager.js';
import { AuditEmitter } from '../audit/emitter.js';
import { ClaimsSchema } from '../authn/types.js';
import { AuthContext } from './AuthContext.js';
import type { Claims, TokenSet } from '../authn/types.js';
import type { OIDCClientConfig } from '../authn/oidc-client.js';
import type { AuditEmitterOptions } from '../audit/emitter.js';

export interface AuthProviderProps {
  children: ReactNode;
  oidcConfig: OIDCClientConfig;
  jwksUri?: string;
  expectedIssuer?: string;
  expectedAudience?: string;
  auditEndpoint?: string;
  auditOptions?: AuditEmitterOptions;
}

function parseClaims(accessToken: string): Claims | null {
  try {
    const payload = decodeJwt(accessToken);
    const result = ClaimsSchema.safeParse({
      ...payload,
      iat: payload.iat ? new Date(payload.iat * 1000) : undefined,
      exp: payload.exp ? new Date(payload.exp * 1000) : undefined,
      aud: Array.isArray(payload.aud) ? payload.aud : [payload.aud],
    });
    return result.success ? result.data : null;
  } catch {
    return null;
  }
}

export function AuthProvider({
  children,
  oidcConfig,
  jwksUri,
  expectedIssuer,
  expectedAudience,
  auditEndpoint,
  auditOptions,
}: AuthProviderProps): ReactNode {
  const [isLoading, setIsLoading] = useState(true);
  const [user, setUser] = useState<Claims | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [tokenSet, setTokenSet] = useState<TokenSet | null>(null);

  const [client] = useState(() => new OIDCClient(oidcConfig));

  const [tokenManager] = useState(
    () =>
      new TokenManager({
        jwksUri,
        expectedIssuer,
        expectedAudience,
        onTokenRefreshed: (tokens: TokenSet) => {
          setAccessToken(tokens.access_token);
          setTokenSet(tokens);
          setUser(parseClaims(tokens.access_token));
        },
        onTokenExpired: () => {
          setAccessToken(null);
          setTokenSet(null);
          setUser(null);
        },
        onRefresh: (refreshToken: string) => client.refresh(refreshToken),
      }),
  );

  const [emitter] = useState(() => {
    if (!auditEndpoint) {
      return null;
    }
    return new AuditEmitter(
      auditEndpoint,
      () => tokenManager.getAccessToken(),
      auditOptions,
    );
  });

  useEffect(() => {
    const stored = tokenManager.getAccessToken();
    if (stored && !tokenManager.isExpired()) {
      setAccessToken(stored);
      setUser(parseClaims(stored));
    }
    setIsLoading(false);

    return () => {
      emitter?.destroy();
    };
  }, [tokenManager, emitter]);

  const login = useCallback(async () => {
    const url = await client.buildAuthUrl();
    window.location.href = url;
  }, [client]);

  const logout = useCallback(async () => {
    const currentTokenSet = tokenSet;
    const currentAccessToken = accessToken;

    // Clear local state immediately
    tokenManager.clear();
    setAccessToken(null);
    setTokenSet(null);
    setUser(null);

    // Revoke access token if available (fire-and-forget)
    if (currentAccessToken) {
      void client.revoke(currentAccessToken, 'access_token');
    }

    // Revoke refresh token if available (fire-and-forget)
    if (currentTokenSet?.refresh_token) {
      void client.revoke(currentTokenSet.refresh_token, 'refresh_token');
    }

    // Redirect to end-session endpoint if available
    const endSessionUrl = client.buildEndSessionUrl(
      currentTokenSet?.id_token,
      `${window.location.origin}/`,
    );
    if (endSessionUrl) {
      window.location.href = endSessionUrl;
    }
  }, [tokenManager, client, tokenSet, accessToken]);

  const isAuthenticated = accessToken !== null && !tokenManager.isExpired();

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated,
        isLoading,
        user,
        accessToken,
        login,
        logout,
        emitter,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
