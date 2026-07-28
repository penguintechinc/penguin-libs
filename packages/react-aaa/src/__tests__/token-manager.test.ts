import { describe, it, expect, beforeEach, vi } from 'vitest';
import { TokenManager } from '../authn/token-manager.js';
import { MemoryTokenStorage, SessionStorageTokenStorage } from '../authn/token-storage.js';
import type { TokenSet } from '../authn/types.js';

const EXPIRED_JWT =
  'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEyMyIsImV4cCI6MX0.invalid';

const FUTURE_JWT =
  'eyJhbGciOiJIUzI1NiJ9.' +
  btoa(
    JSON.stringify({
      sub: 'user-123',
      iss: 'https://auth.example.com',
      aud: ['my-app'],
      iat: Math.floor(Date.now() / 1000),
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  )
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
    it('accepts a SessionStorageTokenStorage instance directly', () => {
      const manager = new TokenManager({ storage: new SessionStorageTokenStorage() });
      const tokens = makeTokenSet();

      manager.store(tokens);
      expect(sessionStorageMock['oidc_token_set']).toBeDefined();
    });

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
    it('does not schedule a refresh when no refresh handler is configured', () => {
      vi.useFakeTimers();
      const onTokenExpired = vi.fn();
      const manager = new TokenManager({ onTokenExpired });

      manager.store(makeTokenSet({ expires_in: 1 }));
      vi.advanceTimersByTime(2000);

      // scheduleRefresh returns early without an onRefresh handler, so no timer fires
      expect(onTokenExpired).not.toHaveBeenCalled();
      vi.useRealTimers();
    });

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

  describe('MemoryTokenStorage', () => {
    it('stores and retrieves tokens in memory', () => {
      const storage = new MemoryTokenStorage();
      const tokens = makeTokenSet();
      storage.set('test-key', tokens);
      expect(storage.get('test-key')).toEqual(tokens);
    });

    it('removes tokens from memory', () => {
      const storage = new MemoryTokenStorage();
      storage.set('test-key', makeTokenSet());
      storage.remove('test-key');
      expect(storage.get('test-key')).toBeNull();
    });

    it('returns null for a key that was never stored', () => {
      const storage = new MemoryTokenStorage();
      expect(storage.get('never-set')).toBeNull();
    });

    it('uses memory storage when provided', () => {
      const memoryStorage = new MemoryTokenStorage();
      const manager = new TokenManager({ storage: memoryStorage });
      const tokens = makeTokenSet();

      manager.store(tokens);
      expect(memoryStorage.get('oidc_token_set')).toEqual(tokens);
      expect(sessionStorageMock['oidc_token_set']).toBeUndefined();
    });
  });

  describe('verifyAndParseClaims', () => {
    it('falls back to decode-only when jwksUri is not provided', async () => {
      const manager = new TokenManager();
      const claims = await manager.verifyAndParseClaims(FUTURE_JWT);
      expect(claims).not.toBeNull();
      expect(claims?.sub).toBe('user-123');
    });

    it('returns null for invalid JWT', async () => {
      const manager = new TokenManager();
      const claims = await manager.verifyAndParseClaims('invalid.jwt.token');
      expect(claims).toBeNull();
    });

    it('rejects a token whose signature does not verify against the JWKS', async () => {
      const manager = new TokenManager({
        jwksUri: 'https://auth.example.com/.well-known/jwks.json',
        expectedIssuer: 'https://auth.example.com',
        expectedAudience: 'penguin-api',
      });

      // Well-formed JWKS response, but FUTURE_JWT is unsigned/HS-less so verification must fail
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({ keys: [] }),
        }),
      );

      const claims = await manager.verifyAndParseClaims(FUTURE_JWT);
      expect(claims).toBeNull();
    });

    it('returns null when JWT verification fails with jwksUri', async () => {
      const manager = new TokenManager({
        jwksUri: 'https://auth.example.com/.well-known/jwks.json',
        expectedIssuer: 'https://auth.example.com',
      });

      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')));

      const claims = await manager.verifyAndParseClaims(FUTURE_JWT);
      expect(claims).toBeNull();
    });
  });
});
