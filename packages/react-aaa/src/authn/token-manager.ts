import { decodeJwt, jwtVerify, createRemoteJWKSet } from 'jose';
import { sessionTokenStorage } from './storage.js';
import type { TokenSet, Claims } from './types.js';
import type { TokenStorage } from './storage.js';
import { ClaimsSchema } from './types.js';

const STORAGE_KEY = 'oidc_token_set';
const REFRESH_BUFFER_MS = 60_000;

export type TokenRefreshedCallback = (tokens: TokenSet) => void;
export type TokenExpiredCallback = () => void;

export type RefreshHandler = (refreshToken: string) => Promise<TokenSet>;

export interface TokenManagerOptions {
  jwksUri?: string;
  expectedIssuer?: string;
  expectedAudience?: string;
  onTokenRefreshed?: TokenRefreshedCallback;
  onTokenExpired?: TokenExpiredCallback;
  onRefresh?: RefreshHandler;
  storage?: TokenStorage;
}

export class TokenManager {
  private refreshTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly onTokenRefreshed: TokenRefreshedCallback | undefined;
  private readonly onTokenExpired: TokenExpiredCallback | undefined;
  private readonly onRefresh: RefreshHandler | undefined;
  private readonly jwksUri: string | undefined;
  private readonly expectedIssuer: string | undefined;
  private readonly expectedAudience: string | undefined;
  private readonly storage: TokenStorage;

  constructor(options: TokenManagerOptions = {}) {
    this.onTokenRefreshed = options.onTokenRefreshed;
    this.onTokenExpired = options.onTokenExpired;
    this.onRefresh = options.onRefresh;
    this.jwksUri = options.jwksUri;
    this.expectedIssuer = options.expectedIssuer;
    this.expectedAudience = options.expectedAudience;
    this.storage = options.storage ?? sessionTokenStorage;
  }

  store(tokens: TokenSet): void {
    this.storage.setItem(STORAGE_KEY, JSON.stringify(tokens));
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
    this.storage.removeItem(STORAGE_KEY);
  }

  /**
   * Verify JWT signature and parse claims using JWKS.
   * Falls back to decode-only (development mode) if jwksUri is not configured.
   * @param accessToken - JWT access token
   * @returns Parsed and validated claims, or null if verification fails
   */
  async verifyAndParseClaims(accessToken: string): Promise<Claims | null> {
    if (!this.jwksUri) {
      // Fall back to decode-only (development mode)
      return this.decodeOnlyClaims(accessToken);
    }

    try {
      const JWKS = createRemoteJWKSet(new URL(this.jwksUri));
      const { payload } = await jwtVerify(accessToken, JWKS, {
        issuer: this.expectedIssuer,
        audience: this.expectedAudience,
      });

      const result = ClaimsSchema.safeParse({
        ...payload,
        iat: payload.iat ? new Date(payload.iat * 1000) : undefined,
        exp: payload.exp ? new Date(payload.exp * 1000) : undefined,
        aud: Array.isArray(payload.aud) ? payload.aud : [payload.aud],
      });

      return result.success ? result.data : null;
    } catch {
      return null;
    }
  }

  /**
   * Decode JWT claims without signature verification.
   * Used as fallback in development when jwksUri is not available.
   * @param token - JWT token
   * @returns Parsed claims, or null if decoding fails
   */
  private decodeOnlyClaims(token: string): Claims | null {
    try {
      const payload = decodeJwt(token);
      const result = ClaimsSchema.safeParse({
        ...payload,
        iat: payload.iat ? new Date(payload.iat * 1000) : undefined,
        exp: payload.exp ? new Date(payload.exp * 1000) : undefined,
        aud: Array.isArray(payload.aud) ? payload.aud : [payload.aud],
      });
      return result.success ? result.data : null;
    } catch {
      return null;
    }
  }

  private loadTokens(): TokenSet | null {
    const raw = this.storage.getItem(STORAGE_KEY);
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
