import { z } from 'zod';
import { TokenSetSchema } from './types.js';
import type { TokenSet } from './types.js';

export const OIDCClientConfigSchema = z.object({
  issuerUrl: z.string().url(),
  clientId: z.string(),
  redirectUrl: z.string(),
  scopes: z.array(z.string()).default(['openid', 'profile', 'email']),
  codeChallengeMethod: z.literal('S256'),
});

export type OIDCClientConfig = z.infer<typeof OIDCClientConfigSchema>;

interface OIDCDiscovery {
  authorization_endpoint: string;
  token_endpoint: string;
  end_session_endpoint?: string;
}

interface PKCEPair {
  verifier: string;
  challenge: string;
}

function base64UrlEncode(buffer: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buffer)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');
}

function generateRandomString(length: number): string {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes.buffer);
}

async function generatePKCEPair(): Promise<PKCEPair> {
  const verifier = generateRandomString(32);
  const encoded = new TextEncoder().encode(verifier);
  const hash = await crypto.subtle.digest('SHA-256', encoded);
  const challenge = base64UrlEncode(hash);
  return { verifier, challenge };
}

export class OIDCClient {
  private readonly config: OIDCClientConfig;
  private discovery: OIDCDiscovery | null = null;

  constructor(config: unknown) {
    this.config = OIDCClientConfigSchema.parse(config);
  }

  async discover(): Promise<void> {
    const url = `${this.config.issuerUrl}/.well-known/openid-configuration`;
    const response = await fetch(url);

    if (!response.ok) {
      throw new Error(`OIDC discovery failed: ${response.status} ${response.statusText}`);
    }

    this.discovery = (await response.json()) as OIDCDiscovery;
  }

  async buildAuthUrl(): Promise<string> {
    if (!this.discovery) {
      await this.discover();
    }

    const { verifier, challenge } = await generatePKCEPair();
    const state = generateRandomString(16);
    const nonce = generateRandomString(16);

    sessionStorage.setItem('oidc_pkce_verifier', verifier);
    sessionStorage.setItem('oidc_state', state);
    sessionStorage.setItem('oidc_nonce', nonce);

    const params = new URLSearchParams({
      response_type: 'code',
      client_id: this.config.clientId,
      redirect_uri: this.config.redirectUrl,
      scope: this.config.scopes.join(' '),
      state,
      nonce,
      code_challenge: challenge,
      code_challenge_method: this.config.codeChallengeMethod,
    });

    return `${this.discovery!.authorization_endpoint}?${params.toString()}`;
  }

  async handleCallback(params: URLSearchParams): Promise<TokenSet> {
    if (!this.discovery) {
      await this.discover();
    }

    const code = params.get('code');
    const state = params.get('state');
    const storedState = sessionStorage.getItem('oidc_state');
    const verifier = sessionStorage.getItem('oidc_pkce_verifier');

    if (!code) {
      throw new Error('Authorization code missing from callback');
    }

    if (!state || state !== storedState) {
      throw new Error('State mismatch — possible CSRF attack');
    }

    if (!verifier) {
      throw new Error('PKCE verifier missing from session storage');
    }

    sessionStorage.removeItem('oidc_state');
    sessionStorage.removeItem('oidc_pkce_verifier');
    sessionStorage.removeItem('oidc_nonce');

    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      redirect_uri: this.config.redirectUrl,
      client_id: this.config.clientId,
      code_verifier: verifier,
    });

    const response = await fetch(this.discovery!.token_endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });

    if (!response.ok) {
      throw new Error(`Token exchange failed: ${response.status} ${response.statusText}`);
    }

    const raw = await response.json();
    return TokenSetSchema.parse(raw);
  }

  getDiscovery(): OIDCDiscovery | null {
    return this.discovery;
  }
}
