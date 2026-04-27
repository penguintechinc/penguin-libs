/**
 * Token storage abstractions for secure OIDC token management.
 */

/**
 * Interface for token storage implementations.
 * Implementations should ensure tokens are stored securely.
 */
export interface TokenStorage {
  /**
   * Retrieve a token from storage.
   * @param key - Storage key
   * @returns Token value or null if not found
   */
  getItem(key: string): string | null;

  /**
   * Store a token in storage.
   * @param key - Storage key
   * @param value - Token value to store
   */
  setItem(key: string, value: string): void;

  /**
   * Remove a token from storage.
   * @param key - Storage key
   */
  removeItem(key: string): void;
}

/**
 * In-memory token storage implementation.
 * Tokens are stored in process memory, not persisted.
 * More secure than sessionStorage: tokens disappear on page reload,
 * not visible in DevTools, reduced XSS exposure window.
 */
export class MemoryTokenStorage implements TokenStorage {
  private readonly store = new Map<string, string>();

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }
}

/**
 * SessionStorage-backed token storage implementation.
 * Tokens persisted across page reloads within the same session.
 */
export const sessionTokenStorage: TokenStorage = {
  getItem: (key) => globalThis.sessionStorage?.getItem(key) ?? null,
  setItem: (key, value) => globalThis.sessionStorage?.setItem(key, value),
  removeItem: (key) => globalThis.sessionStorage?.removeItem(key),
};
