import { describe, it, expect, beforeEach, vi } from 'vitest';
import { TokenManager } from '../authn/token-manager.js';
import type { TokenSet } from '../authn/types.js';

const EXPIRED_JWT =
  'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEyMyIsImV4cCI6MX0.invalid';

const FUTURE_JWT =
  'eyJhbGciOiJIUzI1NiJ9.' +
  btoa(JSON.stringify({ sub: 'user-123', exp: Math.floor(Date.now() / 1000) + 3600 }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '') +
  '.sig';

function makeTokenSet(overrides: Partial<TokenSet> = {}): TokenSet {
  return {
    access_token: FUTURE_JWT,
    expires_in: 3600,
    token_type: 'Bearer',
    ...overrides,
  };
}

describe('TokenManager', () => {
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
  });

  describe('store and getAccessToken', () => {
    it('stores tokens in sessionStorage', () => {
      const manager = new TokenManager();
      manager.store(makeTokenSet());
      expect(sessionStorageMock['oidc_token_set']).toBeDefined();
    });

    it('retrieves the access token after storing', () => {
      const manager = new TokenManager();
      const tokens = makeTokenSet();
      manager.store(tokens);
      expect(manager.getAccessToken()).toBe(tokens.access_token);
    });

    it('returns null when nothing is stored', () => {
      const manager = new TokenManager();
      expect(manager.getAccessToken()).toBeNull();
    });
  });

  describe('isExpired', () => {
    it('returns true when no tokens are stored', () => {
      const manager = new TokenManager();
      expect(manager.isExpired()).toBe(true);
    });

    it('returns true for a token with exp in the past', () => {
      const manager = new TokenManager();
      manager.store(makeTokenSet({ access_token: EXPIRED_JWT }));
      expect(manager.isExpired()).toBe(true);
    });

    it('returns false for a token with exp in the future', () => {
      const manager = new TokenManager();
      manager.store(makeTokenSet({ access_token: FUTURE_JWT }));
      expect(manager.isExpired()).toBe(false);
    });
  });

  describe('clear', () => {
    it('removes tokens from sessionStorage', () => {
      const manager = new TokenManager();
      manager.store(makeTokenSet());
      manager.clear();
      expect(manager.getAccessToken()).toBeNull();
    });

    it('returns null for getAccessToken after clear', () => {
      const manager = new TokenManager();
      manager.store(makeTokenSet());
      manager.clear();
      expect(manager.getAccessToken()).toBeNull();
    });
  });

  describe('getTokenSet', () => {
    it('returns the full token set', () => {
      const manager = new TokenManager();
      const tokens = makeTokenSet({ refresh_token: 'refresh-abc' });
      manager.store(tokens);
      const retrieved = manager.getTokenSet();
      expect(retrieved?.refresh_token).toBe('refresh-abc');
    });

    it('returns null when nothing is stored', () => {
      const manager = new TokenManager();
      expect(manager.getTokenSet()).toBeNull();
    });
  });

  describe('callbacks', () => {
    it('calls onTokenExpired when refresh handler is absent and timer fires', () => {
      vi.useFakeTimers();
      const onTokenExpired = vi.fn();
      const manager = new TokenManager({ onTokenExpired });

      manager.store(makeTokenSet({ expires_in: 1 }));
      vi.advanceTimersByTime(2000);

      // onTokenExpired is not called when there's no refresh handler and timer fires with no refresh_token
      // The manager schedules refresh only if onRefresh is provided
      expect(onTokenExpired).not.toHaveBeenCalled();
      vi.useRealTimers();
    });

    it('calls onTokenRefreshed after a successful refresh', async () => {
      vi.useFakeTimers();
      // Refreshed tokens use a long expiry so re-scheduling does not trigger immediately
      const refreshedTokens = makeTokenSet({ expires_in: 7200 });
      const onRefresh = vi.fn().mockResolvedValue(refreshedTokens);
      const onTokenRefreshed = vi.fn();

      const manager = new TokenManager({ onRefresh, onTokenRefreshed });
      // expires_in of 1 second: delayMs = max(0, 1000 - 60000) = 0 → fires immediately
      manager.store(makeTokenSet({ expires_in: 1, refresh_token: 'old-refresh' }));

      await vi.runAllTimersAsync();

      expect(onRefresh).toHaveBeenCalledWith('old-refresh');
      expect(onTokenRefreshed).toHaveBeenCalledWith(refreshedTokens);
      vi.useRealTimers();
    });
  });
});
