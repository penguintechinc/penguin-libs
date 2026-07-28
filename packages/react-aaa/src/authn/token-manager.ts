import { createRemoteJWKSet, decodeJwt, jwtVerify } from 'jose';
import { MemoryTokenStorage, SessionStorageTokenStorage } from './token-storage.js';
import { ClaimsSchema } from './types.js';
import type { Claims, TokenSet } from './types.js';
import type { TokenStorage } from './token-storage.js';

const STORAGE_KEY = 'oidc_token_set';
const REFRESH_BUFFER_MS = 60_000;

export type TokenRefreshedCallback = (tokens: TokenSet) => void;
export type TokenExpiredCallback = () => void;

export type RefreshHandler = (refreshToken: string) => Promise<TokenSet>;

export type TokenStorageType = 'memory' | 'session' | TokenStorage;

export interface TokenManagerOptions {
  jwksUri?: string;
  expectedIssuer?: string;
  expectedAudience?: string;
  onTokenRefreshed?: TokenRefreshedCallback;
  onTokenExpired?: TokenExpiredCallback;
  onRefresh?: RefreshHandler;
  /**
   * Token storage backend.
   * 'memory' (default): In-memory storage, XSS-safe, cleared on page refresh
   * 'session': sessionStorage, XSS-exfiltrable, persists for session
   * TokenStorage: custom implementation
   */
  storage?: TokenStorageType;
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

    // Initialize storage backend
    const storageOpt = options.storage ?? 'memory';
    if (storageOpt === 'memory') {
      this.storage = new MemoryTokenStorage();
    } else if (storageOpt === 'session') {
      this.storage = new SessionStorageTokenStorage();
    } else {
      this.storage = storageOpt;
    }
  }

  store(tokens: TokenSet): void {
    this.storage.set(STORAGE_KEY, tokens);
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
    this.storage.remove(STORAGE_KEY);
  }

  /**
   * Verify a JWT signature against the configured JWKS and return its claims.
   * Falls back to decode-only (development mode) when `jwksUri` is not configured,
   * so an unconfigured manager still parses claims without asserting authenticity.
   * @param accessToken - JWT access token
   * @returns Validated claims, or null if verification or claim validation fails
   */
  async verifyAndParseClaims(accessToken: string): Promise<Claims | null> {
    if (!this.jwksUri) {
      return this.decodeOnlyClaims(accessToken);
    }

    try {
      const JWKS = createRemoteJWKSet(new URL(this.jwksUri));
      const { payload } = await jwtVerify(accessToken, JWKS, {
        issuer: this.expectedIssuer,
        audience: this.expectedAudience,
      });
      return this.parseClaims(payload);
    } catch {
      return null;
    }
  }

  /**
   * Decode JWT claims without verifying the signature.
   * Development-only fallback used when no `jwksUri` is configured; never treat
   * the result as proof of authenticity.
   * @param token - JWT token
   * @returns Parsed claims, or null if decoding or claim validation fails
   */
  private decodeOnlyClaims(token: string): Claims | null {
    try {
      return this.parseClaims(decodeJwt(token));
    } catch {
      return null;
    }
  }

  /**
   * Normalize a raw JWT payload and validate it against ClaimsSchema.
   * Shared by the verified and decode-only paths so both apply identical
   * claim validation rules.
   */
  private parseClaims(payload: Record<string, unknown>): Claims | null {
    const iat = payload['iat'];
    const exp = payload['exp'];
    const aud = payload['aud'];
    const result = ClaimsSchema.safeParse({
      ...payload,
      iat: typeof iat === 'number' ? new Date(iat * 1000) : undefined,
      exp: typeof exp === 'number' ? new Date(exp * 1000) : undefined,
      aud: Array.isArray(aud) ? aud : [aud],
    });
    return result.success ? result.data : null;
  }

  private loadTokens(): TokenSet | null {
    return this.storage.get(STORAGE_KEY);
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
