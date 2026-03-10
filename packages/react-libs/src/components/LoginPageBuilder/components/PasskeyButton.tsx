import React, { useEffect, useState, useCallback } from 'react';
import type { PasskeyConfig, LoginResponse } from '../types';

interface PasskeyButtonProps {
  config: PasskeyConfig;
  onSuccess: (response: LoginResponse) => void;
  onError?: (error: Error) => void;
  onFallback?: () => void;
  disabled?: boolean;
}

/**
 * PasskeyButton — WebAuthn passkey sign-in button.
 *
 * Detects platform authenticator availability and hides itself when
 * WebAuthn is not supported. Uses @simplewebauthn/browser for the
 * actual WebAuthn flows.
 *
 * Console logging follows the [LoginPageBuilder:Passkey] prefix pattern.
 */
export const PasskeyButton: React.FC<PasskeyButtonProps> = ({
  config,
  onSuccess,
  onError,
  onFallback,
  disabled = false,
}) => {
  const [isSupported, setIsSupported] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  useEffect(() => {
    // Detect platform authenticator availability
    if (
      typeof window !== 'undefined' &&
      window.PublicKeyCredential &&
      typeof PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable === 'function'
    ) {
      PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()
        .then((available) => {
          console.log('[LoginPageBuilder:Passkey] Platform authenticator available:', available);
          setIsSupported(available);
        })
        .catch((err: unknown) => {
          const message = err instanceof Error ? err.message : String(err);
          console.log('[LoginPageBuilder:Passkey] Authenticator detection failed:', message);
          setIsSupported(false);
        });
    } else {
      console.log('[LoginPageBuilder:Passkey] WebAuthn not supported in this browser');
      setIsSupported(false);
    }
  }, []);

  const handlePasskeyAuth = useCallback(async () => {
    console.log('[LoginPageBuilder:Passkey] Authentication flow started');
    setIsLoading(true);

    try {
      // Dynamically import @simplewebauthn/browser to avoid SSR issues
      const { startAuthentication } = await import('@simplewebauthn/browser');

      // 1. Fetch authentication options from server
      const optionsResponse = await fetch(config.authenticationUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!optionsResponse.ok) {
        throw new Error(`Failed to fetch authentication options: ${optionsResponse.status}`);
      }

      const options = await optionsResponse.json();
      console.log('[LoginPageBuilder:Passkey] Received authentication options from server');

      // 2. Prompt user for passkey
      const authResponse = await startAuthentication({ optionsJSON: options });
      console.log('[LoginPageBuilder:Passkey] User completed passkey gesture');

      // 3. Verify with server
      const verifyResponse = await fetch(config.authenticationUrl + '/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(authResponse),
      });

      if (!verifyResponse.ok) {
        throw new Error(`Passkey verification failed: ${verifyResponse.status}`);
      }

      const result: LoginResponse = await verifyResponse.json();
      console.log('[LoginPageBuilder:Passkey] Authentication successful');
      onSuccess(result);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      console.log('[LoginPageBuilder:Passkey] Authentication failed:', error.message);

      if (config.allowFallback !== false && onFallback) {
        console.log('[LoginPageBuilder:Passkey] Falling back to password form');
        onFallback();
      } else if (onError) {
        onError(error);
      }
    } finally {
      setIsLoading(false);
    }
  }, [config, onSuccess, onError, onFallback]);

  if (!isSupported) {
    return null;
  }

  const label = config.buttonLabel ?? 'Sign in with passkey';

  return (
    <button
      type="button"
      onClick={handlePasskeyAuth}
      disabled={disabled || isLoading}
      data-testid="passkey-button"
      className="w-full flex items-center justify-center gap-2 px-4 py-2 border border-amber-400/30 rounded-md text-amber-400 hover:bg-amber-400/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      aria-label={label}
    >
      {isLoading ? (
        <span className="animate-spin h-4 w-4 border-2 border-amber-400 border-t-transparent rounded-full" />
      ) : (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-4 w-4"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"
          />
        </svg>
      )}
      <span>{isLoading ? 'Authenticating...' : label}</span>
    </button>
  );
};

export default PasskeyButton;
