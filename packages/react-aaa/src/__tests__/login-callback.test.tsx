import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { LoginCallback } from '../components/LoginCallback.js';
import type { OIDCClientConfig } from '../authn/oidc-client.js';
import type { TokenSet } from '../authn/types.js';

const mocks = vi.hoisted(() => ({
  handleCallback: vi.fn(),
  store: vi.fn(),
  clientConfigs: [] as unknown[],
}));

vi.mock('../authn/oidc-client.js', () => ({
  OIDCClient: class {
    constructor(config: unknown) {
      mocks.clientConfigs.push(config);
    }
    handleCallback(params: URLSearchParams): Promise<unknown> {
      return mocks.handleCallback(params);
    }
  },
}));

vi.mock('../authn/token-manager.js', () => ({
  TokenManager: class {
    store(tokens: unknown): void {
      mocks.store(tokens);
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

const tokens: TokenSet = {
  access_token: 'access-1',
  refresh_token: 'refresh-1',
  expires_in: 3600,
  token_type: 'Bearer',
};

const originalLocation = Object.getOwnPropertyDescriptor(window, 'location');

function stubLocation(search: string): { replace: ReturnType<typeof vi.fn> } {
  const replace = vi.fn();
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: { search, origin: 'https://app.example.com', href: '', replace },
  });
  return { replace };
}

describe('LoginCallback', () => {
  beforeEach(() => {
    mocks.handleCallback.mockReset().mockResolvedValue(tokens);
    mocks.store.mockReset();
    mocks.clientConfigs.length = 0;
  });

  afterEach(() => {
    if (originalLocation) {
      Object.defineProperty(window, 'location', originalLocation);
    }
  });

  it('exchanges the callback params, stores tokens, and passes a valid redirect path to onSuccess', async () => {
    stubLocation('?code=abc&state=xyz');
    const onSuccess = vi.fn();

    render(<LoginCallback oidcConfig={oidcConfig} onSuccess={onSuccess} redirectPath="/dashboard?x=1#y" />);

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('/dashboard?x=1#y'));
    const params = mocks.handleCallback.mock.calls[0][0] as URLSearchParams;
    expect(params.get('code')).toBe('abc');
    expect(params.get('state')).toBe('xyz');
    expect(mocks.clientConfigs[0]).toEqual(oidcConfig);
    expect(mocks.store).toHaveBeenCalledWith(tokens);
  });

  it('falls back to "/" for the default redirect path', async () => {
    stubLocation('?code=abc&state=xyz');
    const onSuccess = vi.fn();

    render(<LoginCallback oidcConfig={oidcConfig} onSuccess={onSuccess} />);

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('/'));
  });

  it('rejects an encoded protocol-relative redirect (%2F%09%2Fevil) and falls back to "/"', async () => {
    stubLocation('?code=abc&state=xyz');
    const onSuccess = vi.fn();

    render(<LoginCallback oidcConfig={oidcConfig} onSuccess={onSuccess} redirectPath="%2F%09%2Fevil" />);

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(onSuccess).toHaveBeenCalledWith('/');
    expect(onSuccess.mock.calls[0][0]).not.toContain('evil');
  });

  it('never navigates off-site: default navigation replaces with "/" for the encoded attack path', async () => {
    const { replace } = stubLocation('?code=abc&state=xyz');

    render(<LoginCallback oidcConfig={oidcConfig} redirectPath="%2F%09%2Fevil" />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/'));
    expect(replace).toHaveBeenCalledTimes(1);
  });

  it('navigates via location.replace to a valid same-origin path when no onSuccess is given', async () => {
    const { replace } = stubLocation('?code=abc&state=xyz');

    render(<LoginCallback oidcConfig={oidcConfig} redirectPath="/dashboard?x=1#y" />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard?x=1#y'));
  });

  it('calls onError with the rejection when the callback fails', async () => {
    stubLocation('?code=abc&state=bad');
    mocks.handleCallback.mockRejectedValueOnce(new Error('State mismatch — possible CSRF attack'));
    const onSuccess = vi.fn();
    const onError = vi.fn();

    render(<LoginCallback oidcConfig={oidcConfig} onSuccess={onSuccess} onError={onError} />);

    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    const err = onError.mock.calls[0][0] as Error;
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe('State mismatch — possible CSRF attack');
    expect(onSuccess).not.toHaveBeenCalled();
    expect(mocks.store).not.toHaveBeenCalled();
  });

  it('does not throw when the callback fails and no onError is given', async () => {
    stubLocation('?code=abc&state=bad');
    mocks.handleCallback.mockRejectedValueOnce(new Error('bad state'));
    const onSuccess = vi.fn();

    render(<LoginCallback oidcConfig={oidcConfig} onSuccess={onSuccess} />);

    await waitFor(() => expect(mocks.handleCallback).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(onSuccess).not.toHaveBeenCalled();
    expect(mocks.store).not.toHaveBeenCalled();
  });

  it('wraps non-Error rejections in an Error', async () => {
    stubLocation('?code=abc&state=xyz');
    mocks.handleCallback.mockRejectedValueOnce('boom');
    const onError = vi.fn();

    render(<LoginCallback oidcConfig={oidcConfig} onError={onError} />);

    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    const err = onError.mock.calls[0][0] as Error;
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe('boom');
  });

  it('processes the callback only once across re-renders', async () => {
    stubLocation('?code=abc&state=xyz');
    const onSuccess = vi.fn();

    const { rerender } = render(
      <LoginCallback oidcConfig={oidcConfig} onSuccess={onSuccess} redirectPath="/a" />,
    );
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));

    rerender(<LoginCallback oidcConfig={oidcConfig} onSuccess={onSuccess} redirectPath="/b" />);

    expect(mocks.handleCallback).toHaveBeenCalledTimes(1);
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it('renders the loading fallback while the callback is pending', () => {
    stubLocation('?code=abc&state=xyz');
    mocks.handleCallback.mockReturnValueOnce(new Promise(() => {}));

    const { getByText, container } = render(
      <LoginCallback oidcConfig={oidcConfig} loadingFallback={<p>Signing you in</p>} />,
    );

    expect(getByText('Signing you in').textContent).toBe('Signing you in');
    expect(container.innerHTML).toBe('<p>Signing you in</p>');
  });

  it('renders nothing when no loadingFallback is provided', () => {
    stubLocation('?code=abc&state=xyz');
    mocks.handleCallback.mockReturnValueOnce(new Promise(() => {}));

    const { container } = render(<LoginCallback oidcConfig={oidcConfig} />);

    expect(container.innerHTML).toBe('');
  });
});
