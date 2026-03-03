import { useEffect, useRef, type ReactNode } from 'react';
import { OIDCClient } from '../authn/oidc-client.js';
import { TokenManager } from '../authn/token-manager.js';
import type { OIDCClientConfig } from '../authn/oidc-client.js';

export interface LoginCallbackProps {
  oidcConfig: OIDCClientConfig;
  onSuccess?: (redirectPath: string) => void;
  onError?: (error: Error) => void;
  redirectPath?: string;
  loadingFallback?: ReactNode;
}

export function LoginCallback({
  oidcConfig,
  onSuccess,
  onError,
  redirectPath = '/',
  loadingFallback = null,
}: LoginCallbackProps): ReactNode {
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) {
      return;
    }
    handled.current = true;

    const params = new URLSearchParams(window.location.search);
    const client = new OIDCClient(oidcConfig);
    const manager = new TokenManager();

    client
      .handleCallback(params)
      .then((tokens) => {
        manager.store(tokens);
        if (onSuccess) {
          onSuccess(redirectPath);
        } else {
          window.location.replace(redirectPath);
        }
      })
      .catch((err: unknown) => {
        const error = err instanceof Error ? err : new Error(String(err));
        if (onError) {
          onError(error);
        }
      });
  }, [oidcConfig, onSuccess, onError, redirectPath]);

  return loadingFallback;
}
