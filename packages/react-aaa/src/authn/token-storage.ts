import type { TokenSet } from './types.js';

/**
 * Interface for pluggable token storage backends.
 * Implementations must be XSS-safe and handle token lifecycle (store, retrieve, clear).
 */
export interface TokenStorage {
  /**
   * Store a token set.
   */
  set(key: string, tokens: TokenSet): void;

  /**
   * Retrieve a token set.
   * Returns null if not found or if storage is unavailable.
   */
  get(key: string): TokenSet | null;

  /**
   * Clear a stored token set.
   */
  remove(key: string): void;
}

/**
 * In-memory token storage (default).
 * Tokens are cleared on page refresh, requiring re-authentication.
 * XSS-safe: tokens never written to DOM or accessible via document APIs.
 */
export class MemoryTokenStorage implements TokenStorage {
  private readonly store = new Map<string, TokenSet>();

  set(key: string, tokens: TokenSet): void {
    this.store.set(key, tokens);
  }

  get(key: string): TokenSet | null {
    const tokens = this.store.get(key);
    return tokens ?? null;
  }

  remove(key: string): void {
    this.store.delete(key);
  }
}

/**
 * Session Storage token storage (opt-in, XSS-exfiltrable).
 * Tokens persist for the session but are cleared when the browser tab closes.
 * WARNING: Vulnerable to XSS attacks—only use if XSS protections are in place.
 */
export class SessionStorageTokenStorage implements TokenStorage {
  set(key: string, tokens: TokenSet): void {
    try {
      sessionStorage.setItem(key, JSON.stringify(tokens));
    } catch {
      // Storage quota exceeded or unavailable—fail silently
    }
  }

  get(key: string): TokenSet | null {
    try {
      const raw = sessionStorage.getItem(key);
      if (!raw) {
        return null;
      }
      return JSON.parse(raw) as TokenSet;
    } catch {
      // Invalid JSON or storage unavailable
      return null;
    }
  }

  remove(key: string): void {
    try {
      sessionStorage.removeItem(key);
    } catch {
      // Storage unavailable—fail silently
    }
  }
}
