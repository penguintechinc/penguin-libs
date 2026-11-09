import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, act, waitFor } from '@testing-library/react';
import { AuthProvider } from '../components/AuthProvider.js';
import { useAuthContext } from '../components/AuthContext.js';
import type { AuthContextValue } from '../components/AuthContext.js';
import type { OIDCClientConfig } from '../authn/oidc-client.js';
import type { TokenSet } from '../authn/types.js';

const mocks = vi.hoisted(() => ({
  oidc: {
    buildAuthUrl: vi.fn(),
    revoke: vi.fn(),
    refresh: vi.fn(),
    buildEndSessionUrl: vi.fn(),
  },
  tm: {
    store: vi.fn(),
    getAccessToken: vi.fn(),
    isExpired: vi.fn(),
    clear: vi.fn(),
  },
  tmOptions: { current: null as Record<string, unknown> | null },
  emitter: { emit: vi.fn(), flush: vi.fn(), destroy: vi.fn() },
  emitterCtor: vi.fn(),
}));

vi.mock('../authn/oidc-client.js', () => ({
  OIDCClient: class {
    constructor() {
      return mocks.oidc;
    }
  },
}));

vi.mock('../authn/token-manager.js', () => ({
  TokenManager: class {
    constructor(options: Record<string, unknown>) {
      mocks.tmOptions.current = options;
      return mocks.tm;
    }
  },
}));

vi.mock('../audit/emitter.js', () => ({
  AuditEmitter: class {
    constructor(endpoint: string, getToken: () => string | null, options: unknown) {
      mocks.emitterCtor(endpoint, getToken, options);
      return mocks.emitter;
    }
  },
}));

const oidcConfig: OIDCClientConfig = {
  issuerUrl: 'https://idp.example.com',
  clientId: 'client-1',
  redirectUrl: 'https://app.example.com/callback',
  scopes: ['openid'],
  codeChallengeMethod: 'S256',
};

function b64url(value: unknown): string {
  return btoa(JSON.stringify(value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function makeJwt(overrides: Record<string, unknown> = {}): string {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    sub: 'user-123',
    iss: 'https://idp.example.com',
    aud: 'my-app',
    iat: now,
    exp: now + 3600,
    ...overrides,
  };
  return `${b64url({ alg: 'none' })}.${b64url(payload)}.sig`;
}

function opt<T>(name: string): T {
  const value = mocks.tmOptions.current?.[name];
  if (value === undefined) {
    throw new Error(`TokenManager option ${name} was not passed`);
  }
  return value as T;
}

const originalLocation = Object.getOwnPropertyDescriptor(window, 'location');

function renderProvider(props: Partial<Parameters<typeof AuthProvider>[0]> = {}): {
  ctx: { current: AuthContextValue | null };
  unmount: () => void;
} {
  const ctx: { current: AuthContextValue | null } = { current: null };
  function Probe(): null {
    ctx.current = useAuthContext();
    return null;
  }
  const { unmount } = render(
    <AuthProvider oidcConfig={oidcConfig} {...props}>
      <Probe />
    </AuthProvider>,
  );
  return { ctx, unmount };
}

describe('AuthProvider', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: { href: 'https://app.example.com/start', origin: 'https://app.example.com' },
    });
    mocks.tmOptions.current = null;
    mocks.tm.getAccessToken.mockReset().mockReturnValue(null);
    mocks.tm.isExpired.mockReset().mockReturnValue(false);
    mocks.tm.store.mockReset();
    mocks.tm.clear.mockReset();
    mocks.oidc.buildAuthUrl.mockReset().mockResolvedValue('https://idp.example.com/authorize?state=s');
    mocks.oidc.revoke.mockReset().mockResolvedValue(undefined);
    mocks.oidc.refresh.mockReset();
    mocks.oidc.buildEndSessionUrl.mockReset().mockReturnValue(null);
    mocks.emitter.emit.mockReset();
    mocks.emitter.flush.mockReset();
    mocks.emitter.destroy.mockReset();
    mocks.emitterCtor.mockReset();
  });

  afterEach(() => {
    if (originalLocation) {
      Object.defineProperty(window, 'location', originalLocation);
    }
  });

  it('finishes loading unauthenticated when no token is stored', async () => {
    const { ctx } = renderProvider();

    await waitFor(() => expect(ctx.current?.isLoading).toBe(false));
    expect(ctx.current?.isAuthenticated).toBe(false);
    expect(ctx.current?.user).toBeNull();
    expect(ctx.current?.accessToken).toBeNull();
    expect(ctx.current?.emitter).toBeNull();
  });

  it('restores the user and access token from a stored, unexpired token', async () => {
    const token = makeJwt();
    mocks.tm.getAccessToken.mockReturnValue(token);

    const { ctx } = renderProvider();

    await waitFor(() => expect(ctx.current?.isLoading).toBe(false));
    expect(ctx.current?.isAuthenticated).toBe(true);
    expect(ctx.current?.accessToken).toBe(token);
    expect(ctx.current?.user?.sub).toBe('user-123');
    expect(ctx.current?.user?.iss).toBe('https://idp.example.com');
    expect(ctx.current?.user?.aud).toEqual(['my-app']);
    expect(ctx.current?.user?.exp.getTime()).toBe(
      (JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))) as { exp: number }).exp * 1000,
    );
  });

  it('ignores a stored token that is expired', async () => {
    mocks.tm.getAccessToken.mockReturnValue(makeJwt());
    mocks.tm.isExpired.mockReturnValue(true);

    const { ctx } = renderProvider();

    await waitFor(() => expect(ctx.current?.isLoading).toBe(false));
    expect(ctx.current?.isAuthenticated).toBe(false);
    expect(ctx.current?.accessToken).toBeNull();
    expect(ctx.current?.user).toBeNull();
  });

  it('keeps the access token but leaves user null when claims fail schema validation', async () => {
    const token = makeJwt({ iss: undefined });
    mocks.tm.getAccessToken.mockReturnValue(token);

    const { ctx } = renderProvider();

    await waitFor(() => expect(ctx.current?.isLoading).toBe(false));
    expect(ctx.current?.accessToken).toBe(token);
    expect(ctx.current?.user).toBeNull();
    expect(ctx.current?.isAuthenticated).toBe(true);
  });

  it('normalises a multi-value audience array and treats a missing iat or exp as invalid claims', async () => {
    mocks.tm.getAccessToken.mockReturnValue(makeJwt({ aud: ['app-a', 'app-b'] }));
    const first = renderProvider();
    await waitFor(() => expect(first.ctx.current?.isLoading).toBe(false));
    expect(first.ctx.current?.user?.aud).toEqual(['app-a', 'app-b']);
    first.unmount();

    mocks.tm.getAccessToken.mockReturnValue(makeJwt({ exp: undefined }));
    const second = renderProvider();
    await waitFor(() => expect(second.ctx.current?.isLoading).toBe(false));
    expect(second.ctx.current?.user).toBeNull();
    expect(second.ctx.current?.accessToken).not.toBeNull();
  });

  it('passes JWKS and issuer/audience validation options to the token manager', () => {
    renderProvider({
      jwksUri: 'https://idp.example.com/jwks',
      expectedIssuer: 'https://idp.example.com',
      expectedAudience: 'my-app',
    });

    expect(mocks.tmOptions.current).toMatchObject({
      jwksUri: 'https://idp.example.com/jwks',
      expectedIssuer: 'https://idp.example.com',
      expectedAudience: 'my-app',
    });
  });

  it('login navigates the window to the URL built by the OIDC client', async () => {
    const { ctx } = renderProvider();
    await waitFor(() => expect(ctx.current?.isLoading).toBe(false));

    await act(async () => {
      await ctx.current?.login();
    });

    expect(mocks.oidc.buildAuthUrl).toHaveBeenCalledTimes(1);
    expect(window.location.href).toBe('https://idp.example.com/authorize?state=s');
  });

  it('onTokenRefreshed sets the access token, parsed user, and authenticated state', async () => {
    const { ctx } = renderProvider();
    await waitFor(() => expect(ctx.current?.isLoading).toBe(false));

    const token = makeJwt({ sub: 'user-999', scope: undefined });
    const tokens: TokenSet = { access_token: token, expires_in: 3600, token_type: 'Bearer' };
    act(() => {
      (opt<(t: TokenSet) => void>('onTokenRefreshed'))(tokens);
    });

    expect(ctx.current?.accessToken).toBe(token);
    expect(ctx.current?.user?.sub).toBe('user-999');
    expect(ctx.current?.isAuthenticated).toBe(true);
  });

  it('onTokenExpired clears the access token, user, and authenticated state', async () => {
    mocks.tm.getAccessToken.mockReturnValue(makeJwt());
    const { ctx } = renderProvider();
    await waitFor(() => expect(ctx.current?.user?.sub).toBe('user-123'));

    act(() => {
      (opt<() => void>('onTokenExpired'))();
    });

    expect(ctx.current?.accessToken).toBeNull();
    expect(ctx.current?.user).toBeNull();
    expect(ctx.current?.isAuthenticated).toBe(false);
  });

  it('onRefresh delegates to the OIDC client refresh with the refresh token', async () => {
    const refreshed: TokenSet = { access_token: makeJwt(), expires_in: 3600, token_type: 'Bearer' };
    mocks.oidc.refresh.mockResolvedValue(refreshed);
    renderProvider();

    const result = await (opt<(r: string) => Promise<TokenSet>>('onRefresh'))('rt-1');

    expect(mocks.oidc.refresh).toHaveBeenCalledWith('rt-1');
    expect(result).toEqual(refreshed);
  });

  it('logout clears local state, revokes both tokens, and redirects to the end-session URL', async () => {
    const { ctx } = renderProvider();
    await waitFor(() => expect(ctx.current?.isLoading).toBe(false));

    const token = makeJwt();
    act(() => {
      (opt<(t: TokenSet) => void>('onTokenRefreshed'))({
        access_token: token,
        id_token: 'id-tok-1',
        refresh_token: 'rt-1',
        expires_in: 3600,
        token_type: 'Bearer',
      });
    });
    mocks.oidc.buildEndSessionUrl.mockReturnValue('https://idp.example.com/logout?x=1');

    await act(async () => {
      await ctx.current?.logout();
    });

    expect(mocks.tm.clear).toHaveBeenCalledTimes(1);
    expect(mocks.oidc.revoke).toHaveBeenCalledWith(token, 'access_token');
    expect(mocks.oidc.revoke).toHaveBeenCalledWith('rt-1', 'refresh_token');
    expect(mocks.oidc.buildEndSessionUrl).toHaveBeenCalledWith('id-tok-1', 'https://app.example.com/');
    expect(window.location.href).toBe('https://idp.example.com/logout?x=1');
    expect(ctx.current?.isAuthenticated).toBe(false);
    expect(ctx.current?.user).toBeNull();
  });

  it('logout without held tokens skips revocation and leaves href unchanged when no end-session URL exists', async () => {
    const { ctx } = renderProvider();
    await waitFor(() => expect(ctx.current?.isLoading).toBe(false));

    await act(async () => {
      await ctx.current?.logout();
    });

    expect(mocks.tm.clear).toHaveBeenCalledTimes(1);
    expect(mocks.oidc.revoke).not.toHaveBeenCalled();
    expect(mocks.oidc.buildEndSessionUrl).toHaveBeenCalledWith(undefined, 'https://app.example.com/');
    expect(window.location.href).toBe('https://app.example.com/start');
  });

  it('creates no audit emitter when auditEndpoint is not set', () => {
    const { ctx } = renderProvider();

    expect(mocks.emitterCtor).not.toHaveBeenCalled();
    expect(ctx.current?.emitter).toBeNull();
  });

  it('creates an audit emitter with the endpoint, options, and token getter when auditEndpoint is set', async () => {
    mocks.tm.getAccessToken.mockReturnValue(null);
    const { ctx } = renderProvider({
      auditEndpoint: 'https://audit.example.com/events',
      auditOptions: { batchSize: 5 },
    });

    expect(mocks.emitterCtor).toHaveBeenCalledTimes(1);
    const [endpoint, getToken, options] = mocks.emitterCtor.mock.calls[0] as [
      string,
      () => string | null,
      unknown,
    ];
    expect(endpoint).toBe('https://audit.example.com/events');
    expect(options).toEqual({ batchSize: 5 });

    mocks.tm.getAccessToken.mockReturnValue('tok-from-manager');
    expect(getToken()).toBe('tok-from-manager');
    expect(ctx.current?.emitter).toBe(mocks.emitter);
  });

  it('destroys the audit emitter on unmount', () => {
    const { unmount } = renderProvider({ auditEndpoint: 'https://audit.example.com/events' });

    unmount();

    expect(mocks.emitter.destroy).toHaveBeenCalledTimes(1);
  });
});
