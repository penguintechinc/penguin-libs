import { render, screen, fireEvent, waitFor, act, cleanup } from '@testing-library/react';
import * as jestDomMatchers from '@testing-library/jest-dom/matchers';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { PasskeyButton } from '../components/LoginPageBuilder/components/PasskeyButton';
import type { PasskeyConfig, LoginResponse } from '../components/LoginPageBuilder/types';

expect.extend(jestDomMatchers);

// RTL cleanup between tests
afterEach(() => cleanup());

const mockConfig: PasskeyConfig = {
  enabled: true,
  registrationUrl: '/api/v1/auth/passkey/register',
  authenticationUrl: '/api/v1/auth/passkey/authenticate',
  buttonLabel: 'Sign in with passkey',
  allowFallback: true,
};

const mockOnSuccess = vi.fn();
const mockOnFallback = vi.fn();
const mockOnError = vi.fn();

// Mock @simplewebauthn/browser
vi.mock('@simplewebauthn/browser', () => ({
  startAuthentication: vi.fn(),
}));

describe('PasskeyButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('when WebAuthn is supported', () => {
    beforeEach(() => {
      // Mock WebAuthn support
      Object.defineProperty(window, 'PublicKeyCredential', {
        value: {
          isUserVerifyingPlatformAuthenticatorAvailable: vi.fn().mockResolvedValue(true),
        },
        writable: true,
        configurable: true,
      });
    });

    it('renders passkey button when authenticator is available', async () => {
      render(
        <PasskeyButton
          config={mockConfig}
          onSuccess={mockOnSuccess}
          onFallback={mockOnFallback}
        />
      );

      await waitFor(() => {
        expect(screen.getByTestId('passkey-button')).toBeTruthy();
      });
    });

    it('shows custom button label', async () => {
      const config = { ...mockConfig, buttonLabel: 'Use Touch ID' };
      render(
        <PasskeyButton config={config} onSuccess={mockOnSuccess} />
      );

      await waitFor(() => {
        expect(screen.getByText('Use Touch ID')).toBeTruthy();
      });
    });

    it('shows default label when buttonLabel is not set', async () => {
      const config = { ...mockConfig, buttonLabel: undefined };
      render(
        <PasskeyButton config={config} onSuccess={mockOnSuccess} />
      );

      await waitFor(() => {
        expect(screen.getByText('Sign in with passkey')).toBeTruthy();
      });
    });

    it('calls onSuccess after successful authentication', async () => {
      const { startAuthentication } = await import('@simplewebauthn/browser');
      const mockAuthResponse = { id: 'cred-id', type: 'public-key' };
      const mockLoginResponse: LoginResponse = { success: true, token: 'jwt-token' };

      vi.mocked(startAuthentication).mockResolvedValue(mockAuthResponse as Awaited<ReturnType<typeof startAuthentication>>);

      global.fetch = vi.fn()
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ challenge: 'abc', allowCredentials: [] }),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockLoginResponse),
        } as Response);

      render(
        <PasskeyButton
          config={mockConfig}
          onSuccess={mockOnSuccess}
          onFallback={mockOnFallback}
        />
      );

      await waitFor(() => {
        expect(screen.getByTestId('passkey-button')).toBeTruthy();
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId('passkey-button'));
      });

      await waitFor(() => {
        expect(mockOnSuccess).toHaveBeenCalledWith(mockLoginResponse);
      });
    });

    it('calls onFallback when authentication fails and allowFallback is true', async () => {
      const { startAuthentication } = await import('@simplewebauthn/browser');
      vi.mocked(startAuthentication).mockRejectedValue(new Error('User cancelled'));

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ challenge: 'abc' }),
      } as Response);

      render(
        <PasskeyButton
          config={{ ...mockConfig, allowFallback: true }}
          onSuccess={mockOnSuccess}
          onFallback={mockOnFallback}
        />
      );

      await waitFor(() => {
        expect(screen.getByTestId('passkey-button')).toBeTruthy();
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId('passkey-button'));
      });

      await waitFor(() => {
        expect(mockOnFallback).toHaveBeenCalled();
      });
    });

    it('calls onError when allowFallback is false and authentication fails', async () => {
      const { startAuthentication } = await import('@simplewebauthn/browser');
      vi.mocked(startAuthentication).mockRejectedValue(new Error('WebAuthn error'));

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ challenge: 'abc' }),
      } as Response);

      render(
        <PasskeyButton
          config={{ ...mockConfig, allowFallback: false }}
          onSuccess={mockOnSuccess}
          onError={mockOnError}
          onFallback={mockOnFallback}
        />
      );

      await waitFor(() => {
        expect(screen.getByTestId('passkey-button')).toBeTruthy();
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId('passkey-button'));
      });

      await waitFor(() => {
        expect(mockOnError).toHaveBeenCalled();
        expect(mockOnFallback).not.toHaveBeenCalled();
      });
    });

    it('calls onFallback when server returns error fetching options and allowFallback is true', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: () => Promise.resolve({}),
      } as Response);

      render(
        <PasskeyButton
          config={{ ...mockConfig, allowFallback: true }}
          onSuccess={mockOnSuccess}
          onFallback={mockOnFallback}
          onError={mockOnError}
        />
      );

      await waitFor(() => {
        expect(screen.getByTestId('passkey-button')).toBeTruthy();
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId('passkey-button'));
      });

      await waitFor(() => {
        expect(mockOnFallback).toHaveBeenCalled();
      });
    });
  });

  describe('when WebAuthn is NOT supported', () => {
    beforeEach(() => {
      // Remove WebAuthn support
      Object.defineProperty(window, 'PublicKeyCredential', {
        value: undefined,
        writable: true,
        configurable: true,
      });
    });

    it('does not render button when WebAuthn unavailable', async () => {
      render(
        <PasskeyButton
          config={mockConfig}
          onSuccess={mockOnSuccess}
        />
      );

      // Wait for effect to run
      await act(async () => {
        await new Promise(resolve => setTimeout(resolve, 50));
      });

      expect(screen.queryByTestId('passkey-button')).toBeNull();
    });
  });

  describe('when authenticator reports unavailable', () => {
    beforeEach(() => {
      Object.defineProperty(window, 'PublicKeyCredential', {
        value: {
          isUserVerifyingPlatformAuthenticatorAvailable: vi.fn().mockResolvedValue(false),
        },
        writable: true,
        configurable: true,
      });
    });

    it('does not render button when platform authenticator unavailable', async () => {
      render(
        <PasskeyButton
          config={mockConfig}
          onSuccess={mockOnSuccess}
        />
      );

      await act(async () => {
        await new Promise(resolve => setTimeout(resolve, 50));
      });

      expect(screen.queryByTestId('passkey-button')).toBeNull();
    });
  });

  describe('PasskeyConfig type', () => {
    it('has required fields', () => {
      const config: PasskeyConfig = {
        enabled: true,
        registrationUrl: '/register',
        authenticationUrl: '/authenticate',
      };
      expect(config.enabled).toBe(true);
      expect(config.registrationUrl).toBe('/register');
      expect(config.authenticationUrl).toBe('/authenticate');
    });

    it('has optional fields with defaults', () => {
      const config: PasskeyConfig = {
        enabled: true,
        registrationUrl: '/register',
        authenticationUrl: '/authenticate',
        buttonLabel: 'Custom Label',
        allowFallback: false,
      };
      expect(config.buttonLabel).toBe('Custom Label');
      expect(config.allowFallback).toBe(false);
    });
  });
});
