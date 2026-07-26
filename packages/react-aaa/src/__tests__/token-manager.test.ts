import { describe, it, expect, beforeEach, vi } from 'vitest';
import { TokenManager } from '../authn/token-manager.js';
import { MemoryTokenStorage, SessionStorageTokenStorage } from '../authn/token-storage.js';
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

  describe('with default memory storage (XSS-safe)', () => {
    it('stores tokens in memory (not in sessionStorage)', () => {
      const manager = new TokenManager({ storage: 'memory' });
      manager.store(makeTokenSet());
      expect(sessionStorageMock['oidc_token_set']).toBeUndefined();
      expect(manager.getAccessToken()).toBeDefined();
    });

    it('retrieves the access token after storing', () => {
      const manager = new TokenManager({ storage: 'memory' });
      const tokens = makeTokenSet();
      manager.store(tokens);
      expect(manager.getAccessToken()).toBe(tokens.access_token);
    });

    it('returns null when nothing is stored', () => {
      const manager = new TokenManager({ storage: 'memory' });
      expect(manager.getAccessToken()).toBeNull();
    });

    it('clears tokens from memory', () => {
      const manager = new TokenManager({ storage: 'memory' });
      manager.store(makeTokenSet());
      manager.clear();
      expect(manager.getAccessToken()).toBeNull();
    });

    it('is used by default (no storage option specified)', () => {
      const manager = new TokenManager();
      manager.store(makeTokenSet());
      // Should be in memory, not sessionStorage
      expect(sessionStorageMock['oidc_token_set']).toBeUndefined();
      expect(manager.getAccessToken()).toBeDefined();
    });
  });

  describe('with explicit sessionStorage backend (XSS-exfiltrable, opt-in)', () => {
    it('stores tokens in sessionStorage when explicitly opted in', () => {
      const manager = new TokenManager({ storage: 'session' });
      manager.store(makeTokenSet());
      expect(sessionStorageMock['oidc_token_set']).toBeDefined();
    });

    it('retrieves the access token from sessionStorage', () => {
      const manager = new TokenManager({ storage: 'session' });
      const tokens = makeTokenSet();
      manager.store(tokens);
      expect(manager.getAccessToken()).toBe(tokens.access_token);
    });

    it('clears tokens from sessionStorage', () => {
      const manager = new TokenManager({ storage: 'session' });
      manager.store(makeTokenSet());
      manager.clear();
      expect(manager.getAccessToken()).toBeNull();
      expect(sessionStorageMock['oidc_token_set']).toBeUndefined();
    });

    it('handles storage quota exceeded gracefully', () => {
      const manager = new TokenManager({ storage: 'session' });
      Object.defineProperty(globalThis, 'sessionStorage', {
        value: {
          setItem: () => {
            throw new Error('QuotaExceededError');
          },
          getItem: () => null,
          removeItem: () => {},
          clear: () => {},
        },
        writable: true,
      });

      expect(() => {
        manager.store(makeTokenSet());
      }).not.toThrow();
    });
  });

  describe('with custom TokenStorage implementation', () => {
    it('uses custom storage backend when provided', () => {
      const customStorage = {
        stored: new Map<string, TokenSet>(),
        set(key: string, tokens: TokenSet) {
          this.stored.set(key, tokens);
        },
        get(key: string) {
          return this.stored.get(key) ?? null;
        },
        remove(key: string) {
          this.stored.delete(key);
        },
      };

      const manager = new TokenManager({ storage: customStorage });
      const tokens = makeTokenSet();
      manager.store(tokens);
      expect(customStorage.stored.has('oidc_token_set')).toBe(true);
      expect(manager.getAccessToken()).toBe(tokens.access_token);
    });
  });

  describe('isExpired', () => {
    it('returns true when no tokens are stored', () => {
      const manager = new TokenManager({ storage: 'memory' });
      expect(manager.isExpired()).toBe(true);
    });

    it('returns true for a token with exp in the past', () => {
      const manager = new TokenManager({ storage: 'memory' });
      manager.store(makeTokenSet({ access_token: EXPIRED_JWT }));
      expect(manager.isExpired()).toBe(true);
    });

    it('returns false for a token with exp in the future', () => {
      const manager = new TokenManager({ storage: 'memory' });
      manager.store(makeTokenSet({ access_token: FUTURE_JWT }));
      expect(manager.isExpired()).toBe(false);
    });
  });

  describe('getTokenSet', () => {
    it('returns the full token set', () => {
      const manager = new TokenManager({ storage: 'memory' });
      const tokens = makeTokenSet({ refresh_token: 'refresh-abc' });
      manager.store(tokens);
      const retrieved = manager.getTokenSet();
      expect(retrieved?.refresh_token).toBe('refresh-abc');
    });

    it('returns null when nothing is stored', () => {
      const manager = new TokenManager({ storage: 'memory' });
      expect(manager.getTokenSet()).toBeNull();
    });
  });

  describe('callbacks', () => {
    it('calls onTokenRefreshed after a successful refresh', async () => {
      vi.useFakeTimers();
      const refreshedTokens = makeTokenSet({ expires_in: 7200 });
      const onRefresh = vi.fn().mockResolvedValue(refreshedTokens);
      const onTokenRefreshed = vi.fn();

      const manager = new TokenManager({ onRefresh, onTokenRefreshed, storage: 'memory' });
      manager.store(makeTokenSet({ expires_in: 1, refresh_token: 'old-refresh' }));

      await vi.runAllTimersAsync();

      expect(onRefresh).toHaveBeenCalledWith('old-refresh');
      expect(onTokenRefreshed).toHaveBeenCalledWith(refreshedTokens);
      vi.useRealTimers();
    });
  });
});
