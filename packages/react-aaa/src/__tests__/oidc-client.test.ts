import { describe, it, expect, beforeEach, vi } from 'vitest';
import { OIDCClient, OIDCClientConfigSchema } from '../authn/oidc-client.js';

const VALID_CONFIG = {
  issuerUrl: 'https://auth.example.com',
  clientId: 'my-app',
  redirectUrl: 'https://app.example.com/callback',
  scopes: ['openid', 'profile', 'email'],
  codeChallengeMethod: 'S256' as const,
};

const DISCOVERY_RESPONSE = {
  authorization_endpoint: 'https://auth.example.com/authorize',
  token_endpoint: 'https://auth.example.com/token',
  end_session_endpoint: 'https://auth.example.com/logout',
};

describe('OIDCClientConfigSchema', () => {
  it('accepts a valid config', () => {
    const result = OIDCClientConfigSchema.safeParse(VALID_CONFIG);
    expect(result.success).toBe(true);
  });

  it('applies default scopes when omitted', () => {
    const result = OIDCClientConfigSchema.safeParse({
      issuerUrl: 'https://auth.example.com',
      clientId: 'my-app',
      redirectUrl: 'https://app.example.com/callback',
      codeChallengeMethod: 'S256',
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.scopes).toEqual(['openid', 'profile', 'email']);
    }
  });

  it('rejects invalid issuerUrl', () => {
    const result = OIDCClientConfigSchema.safeParse({ ...VALID_CONFIG, issuerUrl: 'not-a-url' });
    expect(result.success).toBe(false);
  });

  it('rejects non-S256 codeChallengeMethod', () => {
    const result = OIDCClientConfigSchema.safeParse({
      ...VALID_CONFIG,
      codeChallengeMethod: 'plain',
    });
    expect(result.success).toBe(false);
  });

  it('rejects missing clientId', () => {
    const { clientId: _clientId, ...rest } = VALID_CONFIG;
    const result = OIDCClientConfigSchema.safeParse(rest);
    expect(result.success).toBe(false);
  });
});

describe('OIDCClient', () => {
  let sessionStorageMock: Record<string, string>;

  beforeEach(() => {
    sessionStorageMock = {};
    Object.defineProperty(globalThis, 'sessionStorage', {
      value: {
        getItem: (key: string) => sessionStorageMock[key] ?? null,
        setItem: (key: string, value: string) => {
          sessionStorageMock[key] = value;
        },
        removeItem: (key: string) => {
          delete sessionStorageMock[key];
        },
        clear: () => {
          sessionStorageMock = {};
        },
      },
      writable: true,
    });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(DISCOVERY_RESPONSE),
    }));
  });

  it('throws on invalid config', () => {
    expect(() => new OIDCClient({})).toThrow();
  });

  it('constructs with valid config', () => {
    expect(() => new OIDCClient(VALID_CONFIG)).not.toThrow();
  });

  it('discover fetches the well-known endpoint', async () => {
    const client = new OIDCClient(VALID_CONFIG);
    await client.discover();
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      'https://auth.example.com/.well-known/openid-configuration',
    );
  });

  it('buildAuthUrl returns a valid URL with PKCE params', async () => {
    const client = new OIDCClient(VALID_CONFIG);
    const url = await client.buildAuthUrl();

    const parsed = new URL(url);
    expect(parsed.searchParams.get('response_type')).toBe('code');
    expect(parsed.searchParams.get('client_id')).toBe('my-app');
    expect(parsed.searchParams.get('code_challenge_method')).toBe('S256');
    expect(parsed.searchParams.get('code_challenge')).toBeTruthy();
    expect(parsed.searchParams.get('state')).toBeTruthy();
    expect(parsed.searchParams.get('nonce')).toBeTruthy();
  });

  it('buildAuthUrl stores PKCE verifier and state in sessionStorage', async () => {
    const client = new OIDCClient(VALID_CONFIG);
    await client.buildAuthUrl();
    expect(sessionStorageMock['oidc_pkce_verifier']).toBeTruthy();
    expect(sessionStorageMock['oidc_state']).toBeTruthy();
    expect(sessionStorageMock['oidc_nonce']).toBeTruthy();
  });

  it('handleCallback throws on state mismatch', async () => {
    const client = new OIDCClient(VALID_CONFIG);
    sessionStorageMock['oidc_state'] = 'expected-state';
    sessionStorageMock['oidc_pkce_verifier'] = 'some-verifier';

    const params = new URLSearchParams({ code: 'auth-code', state: 'wrong-state' });
    await expect(client.handleCallback(params)).rejects.toThrow('State mismatch');
  });

  it('handleCallback throws when code is missing', async () => {
    const client = new OIDCClient(VALID_CONFIG);
    const params = new URLSearchParams({ state: 'some-state' });
    await expect(client.handleCallback(params)).rejects.toThrow('Authorization code missing');
  });

  it('handleCallback throws when verifier is missing', async () => {
    const client = new OIDCClient(VALID_CONFIG);
    sessionStorageMock['oidc_state'] = 'correct-state';

    const params = new URLSearchParams({ code: 'auth-code', state: 'correct-state' });
    await expect(client.handleCallback(params)).rejects.toThrow('PKCE verifier missing');
  });

  it('discover throws on non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
    }));

    const client = new OIDCClient(VALID_CONFIG);
    await expect(client.discover()).rejects.toThrow('OIDC discovery failed');
  });
});
