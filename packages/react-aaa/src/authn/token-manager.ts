import { decodeJwt } from 'jose';
import type { TokenSet } from './types.js';

const STORAGE_KEY = 'oidc_token_set';
const REFRESH_BUFFER_MS = 60_000;

export type TokenRefreshedCallback = (tokens: TokenSet) => void;
export type TokenExpiredCallback = () => void;

export type RefreshHandler = (refreshToken: string) => Promise<TokenSet>;

export interface TokenManagerOptions {
  onTokenRefreshed?: TokenRefreshedCallback;
  onTokenExpired?: TokenExpiredCallback;
  onRefresh?: RefreshHandler;
}

export class TokenManager {
  private refreshTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly onTokenRefreshed: TokenRefreshedCallback | undefined;
  private readonly onTokenExpired: TokenExpiredCallback | undefined;
  private readonly onRefresh: RefreshHandler | undefined;

  constructor(options: TokenManagerOptions = {}) {
    this.onTokenRefreshed = options.onTokenRefreshed;
    this.onTokenExpired = options.onTokenExpired;
    this.onRefresh = options.onRefresh;
  }

  store(tokens: TokenSet): void {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(tokens));
    this.scheduleRefresh(tokens);
  }

  getAccessToken(): string | null {
    const tokens = this.loadTokens();
    return tokens?.access_token ?? null;
  }

  getTokenSet(): TokenSet | null {
    return this.loadTokens();
  }

  isExpired(): boolean {
    const tokens = this.loadTokens();
    if (!tokens) {
      return true;
    }

    try {
      const payload = decodeJwt(tokens.access_token);
      if (typeof payload.exp !== 'number') {
        return false;
      }
      return Date.now() >= payload.exp * 1000;
    } catch {
      return true;
    }
  }

  clear(): void {
    this.cancelRefresh();
    sessionStorage.removeItem(STORAGE_KEY);
  }

  private loadTokens(): TokenSet | null {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }

    try {
      return JSON.parse(raw) as TokenSet;
    } catch {
      return null;
    }
  }

  private scheduleRefresh(tokens: TokenSet): void {
    this.cancelRefresh();

    if (!this.onRefresh) {
      return;
    }

    const expiresInMs = tokens.expires_in * 1000;
    const delayMs = Math.max(0, expiresInMs - REFRESH_BUFFER_MS);

    this.refreshTimer = setTimeout(() => {
      void this.performRefresh(tokens);
    }, delayMs);
  }

  private async performRefresh(tokens: TokenSet): Promise<void> {
    if (!tokens.refresh_token || !this.onRefresh) {
      this.onTokenExpired?.();
      return;
    }

    try {
      const refreshed = await this.onRefresh(tokens.refresh_token);
      this.store(refreshed);
      this.onTokenRefreshed?.(refreshed);
    } catch {
      this.clear();
      this.onTokenExpired?.();
    }
  }

  private cancelRefresh(): void {
    if (this.refreshTimer !== null) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
  }
}
