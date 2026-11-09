import { describe, it, expect } from 'vitest';
import { ClaimsSchema } from '../authn/types.js';
import { OIDCClientConfigSchema } from '../authn/oidc-client.js';
import { AuditEventSchema } from '../audit/event.js';

/** Behaviour contract for schemas that changed API between zod 3 and zod 4. */
describe('zod 4 schema behaviour', () => {
  const baseClaims = {
    sub: 's',
    iss: 'https://i',
    aud: ['a'],
    iat: new Date(),
    exp: new Date(Date.now() + 1000),
  };
  const baseEvent = { type: 'auth.login', outcome: 'success', actor: { sub: 'u' } } as const;

  describe('record(string, unknown) fields', () => {
    it('accepts a string-keyed ext record and preserves values', () => {
      const r = ClaimsSchema.parse({ ...baseClaims, ext: { a: 1, b: { c: [2] }, d: null } });
      expect(r.ext).toEqual({ a: 1, b: { c: [2] }, d: null });
    });
    it('rejects a non-object ext', () => {
      expect(ClaimsSchema.safeParse({ ...baseClaims, ext: 'x' }).success).toBe(false);
      expect(ClaimsSchema.safeParse({ ...baseClaims, ext: [1] }).success).toBe(false);
    });
    it('accepts and preserves audit metadata', () => {
      const r = AuditEventSchema.parse({ ...baseEvent, metadata: { ip: 'x', n: 1 } });
      expect(r.metadata).toEqual({ ip: 'x', n: 1 });
    });
    it('rejects non-object audit metadata', () => {
      expect(AuditEventSchema.safeParse({ ...baseEvent, metadata: 'x' }).success).toBe(false);
      expect(AuditEventSchema.safeParse({ ...baseEvent, metadata: [] }).success).toBe(false);
    });
  });

  describe('ISO datetime timestamp', () => {
    it.each(['2026-01-02T03:04:05Z', '2026-01-02T03:04:05.123Z'])('accepts %s', (ts) => {
      expect(AuditEventSchema.safeParse({ ...baseEvent, timestamp: ts }).success).toBe(true);
    });
    it.each(['2026-01-02', 'not-a-date', '2026-13-02T03:04:05Z', '2026-01-02 03:04:05'])(
      'rejects %s',
      (ts) => {
        expect(AuditEventSchema.safeParse({ ...baseEvent, timestamp: ts }).success).toBe(false);
      },
    );
    it('treats timestamp as optional', () => {
      expect(AuditEventSchema.safeParse(baseEvent).success).toBe(true);
    });
  });

  describe('OIDCClientConfigSchema', () => {
    const cfg = {
      issuerUrl: 'https://auth.example.com',
      clientId: 'c',
      redirectUrl: 'https://app/cb',
      codeChallengeMethod: 'S256',
    };
    it('applies default scopes', () => {
      expect(OIDCClientConfigSchema.parse(cfg).scopes).toEqual(['openid', 'profile', 'email']);
    });
    it('rejects an invalid issuer URL and non-S256 method', () => {
      expect(OIDCClientConfigSchema.safeParse({ ...cfg, issuerUrl: 'nope' }).success).toBe(false);
      expect(OIDCClientConfigSchema.safeParse({ ...cfg, codeChallengeMethod: 'plain' }).success).toBe(false);
    });
  });
});
