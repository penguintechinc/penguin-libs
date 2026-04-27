import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
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
} from './oauth';
import type {
  BuiltInOAuth2Provider,
  CustomOAuth2Provider,
  OIDCProvider,
  SAMLProvider,
} from '../types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function googleConfig(overrides?: Partial<BuiltInOAuth2Provider>): BuiltInOAuth2Provider {
  return {
    provider: 'google',
    clientId: 'test-client-id',
    redirectUri: 'https://example.com/auth/callback',
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// generateState
// ---------------------------------------------------------------------------

describe('generateState', () => {
  it('returns a non-empty hex string of length 64', () => {
    const state = generateState();
    expect(state).toMatch(/^[0-9a-f]{64}$/);
  });

  it('generates unique values on each call', () => {
    const a = generateState();
    const b = generateState();
    expect(a).not.toBe(b);
  });
});

// ---------------------------------------------------------------------------
// generateCodeVerifier
// ---------------------------------------------------------------------------

describe('generateCodeVerifier', () => {
  it('returns a base64url string (no +, /, or =)', () => {
    const verifier = generateCodeVerifier();
    expect(verifier).not.toMatch(/[+/=]/);
    expect(verifier.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// generateCodeChallenge
// ---------------------------------------------------------------------------

describe('generateCodeChallenge', () => {
  it('returns a non-empty base64url string for a given verifier', async () => {
    const verifier = generateCodeVerifier();
    const challenge = await generateCodeChallenge(verifier);
    expect(challenge).toBeTruthy();
    expect(challenge).not.toMatch(/[+/=]/);
  });

  it('produces consistent output for the same verifier', async () => {
    const verifier = 'fixed-verifier-value-for-testing';
    const c1 = await generateCodeChallenge(verifier);
    const c2 = await generateCodeChallenge(verifier);
    expect(c1).toBe(c2);
  });

  it('produces different output for different verifiers', async () => {
    const c1 = await generateCodeChallenge('verifier-one');
    const c2 = await generateCodeChallenge('verifier-two');
    expect(c1).not.toBe(c2);
  });
});

// ---------------------------------------------------------------------------
// buildOAuth2Url – built-in providers
// ---------------------------------------------------------------------------

describe('buildOAuth2Url', () => {
  beforeEach(() => {
    sessionStorage.clear();
    Object.defineProperty(window, 'location', {
      value: { origin: 'https://example.com' },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  it('builds a valid URL for google', () => {
    const url = buildOAuth2Url(googleConfig());
    const parsed = new URL(url);
    expect(parsed.origin + parsed.pathname).toBe('https://accounts.google.com/o/oauth2/v2/auth');
    expect(parsed.searchParams.get('client_id')).toBe('test-client-id');
    expect(parsed.searchParams.get('response_type')).toBe('code');
    expect(parsed.searchParams.get('redirect_uri')).toBe('https://example.com/auth/callback');
    expect(parsed.searchParams.get('scope')).toContain('openid');
  });

  it('includes state parameter (CSRF protection)', () => {
    const url = buildOAuth2Url(googleConfig());
    const state = new URL(url).searchParams.get('state');
    expect(state).toBeTruthy();
    expect(state).toMatch(/^[0-9a-f]{64}$/);
  });

  it('stores state in sessionStorage for later validation', () => {
    buildOAuth2Url(googleConfig());
    expect(sessionStorage.getItem('oauth_state')).toBeTruthy();
  });

  it('includes google-specific params (access_type, prompt)', () => {
    const url = buildOAuth2Url(googleConfig());
    const parsed = new URL(url);
    expect(parsed.searchParams.get('access_type')).toBe('offline');
    expect(parsed.searchParams.get('prompt')).toBe('consent');
  });

  it('includes apple-specific response_mode=form_post', () => {
    const url = buildOAuth2Url({ provider: 'apple', clientId: 'abc' });
    expect(new URL(url).searchParams.get('response_mode')).toBe('form_post');
  });

  it('builds correct URL for github', () => {
    const url = buildOAuth2Url({ provider: 'github', clientId: 'gh-id' });
    expect(url).toContain('github.com/login/oauth/authorize');
  });

  it('builds correct URL for microsoft', () => {
    const url = buildOAuth2Url({ provider: 'microsoft', clientId: 'ms-id' });
    expect(url).toContain('microsoftonline.com');
  });

  it('builds correct URL for twitch', () => {
    const url = buildOAuth2Url({ provider: 'twitch', clientId: 'twitch-id' });
    expect(url).toContain('twitch.tv');
  });

  it('builds correct URL for discord', () => {
    const url = buildOAuth2Url({ provider: 'discord', clientId: 'discord-id' });
    expect(url).toContain('discord.com');
  });

  it('uses custom scopes when provided', () => {
    const url = buildOAuth2Url(googleConfig({ scopes: ['custom_scope'] }));
    expect(new URL(url).searchParams.get('scope')).toBe('custom_scope');
  });

  it('falls back to window.location.origin for redirectUri when not specified', () => {
    const url = buildOAuth2Url({ provider: 'github', clientId: 'abc' });
    expect(new URL(url).searchParams.get('redirect_uri')).toBe(
      'https://example.com/auth/callback'
    );
  });
});

// ---------------------------------------------------------------------------
// buildCustomOAuth2Url
// ---------------------------------------------------------------------------

describe('buildCustomOAuth2Url', () => {
  beforeEach(() => {
    sessionStorage.clear();
    Object.defineProperty(window, 'location', {
      value: { origin: 'https://example.com' },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  const customConfig: CustomOAuth2Provider = {
    provider: 'oauth2',
    clientId: 'custom-id',
    authUrl: 'https://auth.example.com/oauth/authorize',
    label: 'My Provider',
    redirectUri: 'https://example.com/callback',
    scopes: ['read', 'write'],
  };

  it('builds URL from the provided authUrl', () => {
    const url = buildCustomOAuth2Url(customConfig);
    expect(url).toContain('auth.example.com/oauth/authorize');
  });

  it('includes state parameter', () => {
    const url = buildCustomOAuth2Url(customConfig);
    expect(new URL(url).searchParams.get('state')).toMatch(/^[0-9a-f]{64}$/);
  });

  it('stores state in sessionStorage', () => {
    buildCustomOAuth2Url(customConfig);
    expect(sessionStorage.getItem('oauth_state')).toBeTruthy();
  });

  it('includes scope when provided', () => {
    const url = buildCustomOAuth2Url(customConfig);
    expect(new URL(url).searchParams.get('scope')).toBe('read write');
  });

  it('omits scope when not provided', () => {
    const noScope: CustomOAuth2Provider = { ...customConfig, scopes: undefined };
    const url = buildCustomOAuth2Url(noScope);
    expect(new URL(url).searchParams.has('scope')).toBe(false);
  });

  it('includes redirect_uri and client_id', () => {
    const url = buildCustomOAuth2Url(customConfig);
    const parsed = new URL(url);
    expect(parsed.searchParams.get('client_id')).toBe('custom-id');
    expect(parsed.searchParams.get('redirect_uri')).toBe('https://example.com/callback');
  });
});

// ---------------------------------------------------------------------------
// buildOIDCUrl
// ---------------------------------------------------------------------------

describe('buildOIDCUrl', () => {
  const oidcConfig: OIDCProvider = {
    provider: 'oidc',
    issuerUrl: 'https://sso.example.com',
    clientId: 'oidc-client',
    redirectUri: 'https://app.example.com/callback',
  };

  beforeEach(() => {
    sessionStorage.clear();
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it('fetches discovery document from well-known URL', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        authorization_endpoint: 'https://sso.example.com/auth',
      }),
    });
    vi.stubGlobal('fetch', mockFetch);

    await buildOIDCUrl(oidcConfig);
    expect(mockFetch).toHaveBeenCalledWith(
      'https://sso.example.com/.well-known/openid-configuration'
    );
  });

  it('builds URL from discovered authorization_endpoint', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ authorization_endpoint: 'https://sso.example.com/authorize' }),
    }));

    const url = await buildOIDCUrl(oidcConfig);
    expect(url).toContain('sso.example.com/authorize');
  });

  it('includes state and nonce parameters', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ authorization_endpoint: 'https://sso.example.com/authorize' }),
    }));

    const url = await buildOIDCUrl(oidcConfig);
    const parsed = new URL(url);
    expect(parsed.searchParams.get('state')).toMatch(/^[0-9a-f]{64}$/);
    expect(parsed.searchParams.get('nonce')).toMatch(/^[0-9a-f]{64}$/);
  });

  it('stores state and nonce in sessionStorage', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ authorization_endpoint: 'https://sso.example.com/authorize' }),
    }));

    await buildOIDCUrl(oidcConfig);
    expect(sessionStorage.getItem('oauth_state')).toBeTruthy();
    expect(sessionStorage.getItem('oidc_nonce')).toBeTruthy();
  });

  it('throws when discovery endpoint returns non-ok', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));

    await expect(buildOIDCUrl(oidcConfig)).rejects.toThrow('OIDC discovery failed: 404');
  });

  it('throws when authorization_endpoint missing from discovery', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    }));

    await expect(buildOIDCUrl(oidcConfig)).rejects.toThrow(
      'No authorization_endpoint in OIDC discovery'
    );
  });

  it('strips trailing slash from issuerUrl before appending well-known path', async () => {
    const configWithSlash: OIDCProvider = { ...oidcConfig, issuerUrl: 'https://sso.example.com/' };
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ authorization_endpoint: 'https://sso.example.com/authorize' }),
    });
    vi.stubGlobal('fetch', mockFetch);

    await buildOIDCUrl(configWithSlash);
    expect(mockFetch).toHaveBeenCalledWith(
      'https://sso.example.com/.well-known/openid-configuration'
    );
  });
});

// ---------------------------------------------------------------------------
// validateState
// ---------------------------------------------------------------------------

describe('validateState', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => sessionStorage.clear());

  it('returns true when stored state matches received state', () => {
    sessionStorage.setItem('oauth_state', 'abc123');
    expect(validateState('abc123')).toBe(true);
  });

  it('removes state from sessionStorage after successful validation', () => {
    sessionStorage.setItem('oauth_state', 'abc123');
    validateState('abc123');
    expect(sessionStorage.getItem('oauth_state')).toBeNull();
  });

  it('returns false when states do not match', () => {
    sessionStorage.setItem('oauth_state', 'abc123');
    expect(validateState('wrong-state')).toBe(false);
  });

  it('returns false when no state is stored', () => {
    expect(validateState('any-state')).toBe(false);
  });

  it('does NOT remove state from sessionStorage on failed validation', () => {
    sessionStorage.setItem('oauth_state', 'abc123');
    validateState('wrong');
    expect(sessionStorage.getItem('oauth_state')).toBe('abc123');
  });
});

// ---------------------------------------------------------------------------
// getProviderLabel
// ---------------------------------------------------------------------------

describe('getProviderLabel', () => {
  it('returns built-in label for google', () => {
    expect(getProviderLabel({ provider: 'google', clientId: 'id' })).toBe('Continue with Google');
  });

  it('returns built-in label for github', () => {
    expect(getProviderLabel({ provider: 'github', clientId: 'id' })).toBe('Continue with GitHub');
  });

  it('returns "Continue with Enterprise SSO" for saml without label', () => {
    const saml: SAMLProvider = {
      provider: 'saml',
      idpSsoUrl: 'https://idp.example.com',
      entityId: 'sp',
      acsUrl: 'https://sp.example.com/acs',
    };
    expect(getProviderLabel(saml)).toBe('Continue with Enterprise SSO');
  });

  it('returns "Continue with SSO" for oidc without label', () => {
    const oidc: OIDCProvider = {
      provider: 'oidc',
      issuerUrl: 'https://sso.example.com',
      clientId: 'id',
    };
    expect(getProviderLabel(oidc)).toBe('Continue with SSO');
  });

  it('returns custom label when provided for saml', () => {
    const saml: SAMLProvider = {
      provider: 'saml',
      idpSsoUrl: 'https://idp.example.com',
      entityId: 'sp',
      acsUrl: 'https://sp.example.com/acs',
      label: 'My SSO',
    };
    expect(getProviderLabel(saml)).toBe('My SSO');
  });

  it('returns custom label when provided for oauth2', () => {
    const custom: CustomOAuth2Provider = {
      provider: 'oauth2',
      clientId: 'id',
      authUrl: 'https://auth.example.com',
      label: 'Acme Login',
    };
    expect(getProviderLabel(custom)).toBe('Acme Login');
  });
});

// ---------------------------------------------------------------------------
// getProviderColors
// ---------------------------------------------------------------------------

describe('getProviderColors', () => {
  it('returns colors for google', () => {
    const colors = getProviderColors('google');
    expect(colors).not.toBeNull();
    expect(colors?.background).toBe('bg-white');
    expect(colors?.text).toBe('text-gray-700');
  });

  it('returns colors for github', () => {
    const colors = getProviderColors('github');
    expect(colors?.background).toBe('bg-gray-900');
    expect(colors?.text).toBe('text-white');
  });

  it('returns colors for microsoft', () => {
    expect(getProviderColors('microsoft')).not.toBeNull();
  });

  it('returns colors for apple', () => {
    expect(getProviderColors('apple')?.background).toBe('bg-black');
  });

  it('returns colors for twitch', () => {
    expect(getProviderColors('twitch')?.background).toContain('9146FF');
  });

  it('returns colors for discord', () => {
    expect(getProviderColors('discord')?.background).toContain('5865F2');
  });

  it('returns null for unknown provider', () => {
    expect(getProviderColors('unknown_provider')).toBeNull();
  });

  it('returns null for saml (no brand colors)', () => {
    expect(getProviderColors('saml')).toBeNull();
  });
});
