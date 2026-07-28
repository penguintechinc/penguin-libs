import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  generateState,
  generateCodeVerifier,
  generateCodeChallenge,
  buildOAuth2Url,
  buildCustomOAuth2Url,
  buildOIDCUrl,
  validateState,
  getProviderLabel,
  getProviderColors,
} from '../utils/oauth';

describe('OAuth Utils', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  describe('generateState', () => {
    it('generates a random 64-character hex string', () => {
      const state = generateState();

      expect(state).toMatch(/^[0-9a-f]{64}$/);
      expect(state.length).toBe(64);
    });

    it('generates different states on each call', () => {
      const state1 = generateState();
      const state2 = generateState();

      expect(state1).not.toBe(state2);
    });
  });

  describe('generateCodeVerifier', () => {
    it('generates a valid PKCE code verifier', () => {
      const verifier = generateCodeVerifier();

      // Should be base64url encoded, 43-128 characters
      expect(verifier.length).toBeGreaterThanOrEqual(43);
      expect(verifier.length).toBeLessThanOrEqual(128);
      expect(verifier).toMatch(/^[A-Za-z0-9_-]+$/);
    });

    it('generates different verifiers on each call', () => {
      const verifier1 = generateCodeVerifier();
      const verifier2 = generateCodeVerifier();

      expect(verifier1).not.toBe(verifier2);
    });
  });

  describe('generateCodeChallenge', () => {
    it('generates base64url encoded SHA256 hash', async () => {
      const verifier = generateCodeVerifier();
      const challenge = await generateCodeChallenge(verifier);

      // Should be base64url encoded
      expect(challenge).toMatch(/^[A-Za-z0-9_-]+$/);
      expect(challenge.length).toBeGreaterThan(0);
    });

    it('generates consistent challenge for same verifier', async () => {
      const verifier = generateCodeVerifier();
      const challenge1 = await generateCodeChallenge(verifier);
      const challenge2 = await generateCodeChallenge(verifier);

      expect(challenge1).toBe(challenge2);
    });

    it('generates different challenges for different verifiers', async () => {
      const verifier1 = generateCodeVerifier();
      const verifier2 = generateCodeVerifier();

      const challenge1 = await generateCodeChallenge(verifier1);
      const challenge2 = await generateCodeChallenge(verifier2);

      expect(challenge1).not.toBe(challenge2);
    });
  });

  describe('buildOAuth2Url', () => {
    it('builds Google OAuth2 URL with correct parameters', () => {
      const config = {
        provider: 'google' as const,
        clientId: 'google-client-id',
        redirectUri: 'http://localhost:3000/auth/callback',
        scopes: ['openid', 'email', 'profile'],
      };

      const url = buildOAuth2Url(config);
      const urlObj = new URL(url);

      expect(url).toContain('https://accounts.google.com/o/oauth2/v2/auth');
      expect(urlObj.searchParams.get('client_id')).toBe('google-client-id');
      expect(urlObj.searchParams.get('redirect_uri')).toBe(
        'http://localhost:3000/auth/callback'
      );
      expect(urlObj.searchParams.get('response_type')).toBe('code');
      expect(urlObj.searchParams.get('scope')).toContain('email');
      expect(urlObj.searchParams.has('state')).toBe(true);
    });

    it('stores state in sessionStorage for CSRF protection', () => {
      const config = {
        provider: 'google' as const,
        clientId: 'google-client-id',
      };

      buildOAuth2Url(config);

      expect(sessionStorage.getItem('oauth_state')).not.toBeNull();
    });

    it('includes access_type=offline for Google', () => {
      const config = {
        provider: 'google' as const,
        clientId: 'google-client-id',
      };

      const url = buildOAuth2Url(config);
      const urlObj = new URL(url);

      expect(urlObj.searchParams.get('access_type')).toBe('offline');
    });

    it('includes prompt=consent for Google', () => {
      const config = {
        provider: 'google' as const,
        clientId: 'google-client-id',
      };

      const url = buildOAuth2Url(config);
      const urlObj = new URL(url);

      expect(urlObj.searchParams.get('prompt')).toBe('consent');
    });

    it('builds GitHub OAuth2 URL', () => {
      const config = {
        provider: 'github' as const,
        clientId: 'github-client-id',
        redirectUri: 'http://localhost:3000/auth/callback',
      };

      const url = buildOAuth2Url(config);

      expect(url).toContain('https://github.com/login/oauth/authorize');
    });

    it('builds Microsoft OAuth2 URL', () => {
      const config = {
        provider: 'microsoft' as const,
        clientId: 'microsoft-client-id',
      };

      const url = buildOAuth2Url(config);

      expect(url).toContain('https://login.microsoftonline.com');
    });

    it('uses default scopes when not provided', () => {
      const config = {
        provider: 'google' as const,
        clientId: 'google-client-id',
      };

      const url = buildOAuth2Url(config);
      const urlObj = new URL(url);

      expect(urlObj.searchParams.get('scope')).toContain('openid');
      expect(urlObj.searchParams.get('scope')).toContain('email');
      expect(urlObj.searchParams.get('scope')).toContain('profile');
    });

    it('throws error for unknown provider', () => {
      const config = {
        provider: 'unknown' as any,
        clientId: 'client-id',
      };

      expect(() => buildOAuth2Url(config)).toThrow();
    });
  });

  describe('buildCustomOAuth2Url', () => {
    it('builds custom OAuth2 URL with provided auth URL', () => {
      const config = {
        provider: 'oauth2' as const,
        clientId: 'custom-client-id',
        authUrl: 'https://custom-provider.com/authorize',
        redirectUri: 'http://localhost:3000/auth/callback',
        label: 'Custom Provider',
      };

      const url = buildCustomOAuth2Url(config);
      const urlObj = new URL(url);

      expect(url).toContain('https://custom-provider.com/authorize');
      expect(urlObj.searchParams.get('client_id')).toBe('custom-client-id');
      expect(urlObj.searchParams.get('redirect_uri')).toBe(
        'http://localhost:3000/auth/callback'
      );
    });

    it('stores state in sessionStorage', () => {
      const config = {
        provider: 'oauth2' as const,
        clientId: 'custom-client-id',
        authUrl: 'https://custom-provider.com/authorize',
        label: 'Custom Provider',
      };

      buildCustomOAuth2Url(config);

      expect(sessionStorage.getItem('oauth_state')).not.toBeNull();
    });

    it('uses window.location.origin as default redirect URI', () => {
      const config = {
        provider: 'oauth2' as const,
        clientId: 'custom-client-id',
        authUrl: 'https://custom-provider.com/authorize',
        label: 'Custom Provider',
      };

      const url = buildCustomOAuth2Url(config);
      const urlObj = new URL(url);

      expect(urlObj.searchParams.get('redirect_uri')).toContain('http');
    });
  });

  describe('buildOIDCUrl', () => {
    beforeEach(() => {
      global.fetch = vi.fn();
    });

    it('fetches OIDC discovery document', async () => {
      const mockDiscovery = {
        authorization_endpoint: 'https://oidc-provider.com/authorize',
      };

      (global.fetch as any).mockResolvedValue({
        ok: true,
        json: async () => mockDiscovery,
      });

      const config = {
        provider: 'oidc' as const,
        issuerUrl: 'https://oidc-provider.com',
        clientId: 'oidc-client-id',
      };

      await buildOIDCUrl(config);

      expect(global.fetch).toHaveBeenCalledWith(
        'https://oidc-provider.com/.well-known/openid-configuration'
      );
    });

    it('builds OIDC URL with authorization endpoint from discovery', async () => {
      const mockDiscovery = {
        authorization_endpoint: 'https://oidc-provider.com/authorize',
      };

      (global.fetch as any).mockResolvedValue({
        ok: true,
        json: async () => mockDiscovery,
      });

      const config = {
        provider: 'oidc' as const,
        issuerUrl: 'https://oidc-provider.com',
        clientId: 'oidc-client-id',
      };

      const url = await buildOIDCUrl(config);
      const urlObj = new URL(url);

      expect(url).toContain('https://oidc-provider.com/authorize');
      expect(urlObj.searchParams.get('client_id')).toBe('oidc-client-id');
      expect(urlObj.searchParams.has('state')).toBe(true);
      expect(urlObj.searchParams.has('nonce')).toBe(true);
    });

    it('stores state and nonce in sessionStorage', async () => {
      const mockDiscovery = {
        authorization_endpoint: 'https://oidc-provider.com/authorize',
      };

      (global.fetch as any).mockResolvedValue({
        ok: true,
        json: async () => mockDiscovery,
      });

      const config = {
        provider: 'oidc' as const,
        issuerUrl: 'https://oidc-provider.com',
        clientId: 'oidc-client-id',
      };

      await buildOIDCUrl(config);

      expect(sessionStorage.getItem('oauth_state')).not.toBeNull();
      expect(sessionStorage.getItem('oidc_nonce')).not.toBeNull();
    });

    it('throws error on OIDC discovery failure', async () => {
      (global.fetch as any).mockResolvedValue({
        ok: false,
        status: 404,
      });

      const config = {
        provider: 'oidc' as const,
        issuerUrl: 'https://oidc-provider.com',
        clientId: 'oidc-client-id',
      };

      await expect(buildOIDCUrl(config)).rejects.toThrow();
    });

    it('throws error when authorization_endpoint not in discovery', async () => {
      const mockDiscovery = {};

      (global.fetch as any).mockResolvedValue({
        ok: true,
        json: async () => mockDiscovery,
      });

      const config = {
        provider: 'oidc' as const,
        issuerUrl: 'https://oidc-provider.com',
        clientId: 'oidc-client-id',
      };

      await expect(buildOIDCUrl(config)).rejects.toThrow(
        'No authorization_endpoint'
      );
    });
  });

  describe('validateState', () => {
    it('validates matching state parameter', () => {
      const state = generateState();
      sessionStorage.setItem('oauth_state', state);

      const isValid = validateState(state);

      expect(isValid).toBe(true);
    });

    it('clears state after validation', () => {
      const state = generateState();
      sessionStorage.setItem('oauth_state', state);

      validateState(state);

      expect(sessionStorage.getItem('oauth_state')).toBeNull();
    });

    it('rejects mismatched state', () => {
      sessionStorage.setItem('oauth_state', 'stored-state');

      const isValid = validateState('different-state');

      expect(isValid).toBe(false);
    });

    it('rejects validation when state not stored', () => {
      const isValid = validateState('any-state');

      expect(isValid).toBe(false);
    });
  });

  describe('getProviderLabel', () => {
    it('returns custom label when provided', () => {
      const config = {
        provider: 'oauth2' as const,
        clientId: 'client-id',
        authUrl: 'https://provider.com/authorize',
        label: 'My Custom Provider',
      };

      const label = getProviderLabel(config);

      expect(label).toBe('My Custom Provider');
    });

    it('returns default label for Google', () => {
      const config = {
        provider: 'google' as const,
        clientId: 'client-id',
      };

      const label = getProviderLabel(config);

      expect(label).toBe('Continue with Google');
    });

    it('returns default label for GitHub', () => {
      const config = {
        provider: 'github' as const,
        clientId: 'client-id',
      };

      const label = getProviderLabel(config);

      expect(label).toBe('Continue with GitHub');
    });

    it('returns OIDC label', () => {
      const config = {
        provider: 'oidc' as const,
        issuerUrl: 'https://provider.com',
        clientId: 'client-id',
      };

      const label = getProviderLabel(config);

      expect(label).toContain('SSO');
    });

    it('returns SAML label', () => {
      const config = {
        provider: 'saml' as const,
        idpSsoUrl: 'https://provider.com/sso',
        entityId: 'entity-id',
        acsUrl: 'http://localhost:3000/auth/callback',
      };

      const label = getProviderLabel(config);

      expect(label).toContain('Enterprise SSO');
    });
  });

  describe('getProviderColors', () => {
    it('returns colors for Google', () => {
      const colors = getProviderColors('google');

      expect(colors).toBeDefined();
      expect(colors?.background).toBe('bg-white');
      expect(colors?.text).toBe('text-gray-700');
    });

    it('returns colors for GitHub', () => {
      const colors = getProviderColors('github');

      expect(colors).toBeDefined();
      expect(colors?.background).toBe('bg-gray-900');
      expect(colors?.text).toBe('text-white');
    });

    it('returns colors for Microsoft', () => {
      const colors = getProviderColors('microsoft');

      expect(colors).toBeDefined();
      expect(colors?.background).toBe('bg-white');
    });

    it('returns colors for Apple', () => {
      const colors = getProviderColors('apple');

      expect(colors).toBeDefined();
      expect(colors?.background).toBe('bg-black');
    });

    it('returns colors for Twitch', () => {
      const colors = getProviderColors('twitch');

      expect(colors).toBeDefined();
      expect(colors?.background).toContain('9146FF');
    });

    it('returns colors for Discord', () => {
      const colors = getProviderColors('discord');

      expect(colors).toBeDefined();
      expect(colors?.background).toContain('5865F2');
    });

    it('returns null for unknown provider', () => {
      const colors = getProviderColors('unknown');

      expect(colors).toBeNull();
    });

    it('includes hover state in colors', () => {
      const colors = getProviderColors('google');

      expect(colors?.hover).toBeDefined();
      expect(colors?.hover).toContain('hover:');
    });
  });
});
