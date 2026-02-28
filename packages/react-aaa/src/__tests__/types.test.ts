import { describe, it, expect } from 'vitest';
import { ClaimsSchema, TokenSetSchema } from '../authn/types.js';
import { RoleSchema, RBACConfigSchema } from '../authz/types.js';
import { AuditEventSchema, EventTypeSchema, OutcomeSchema } from '../audit/event.js';

describe('ClaimsSchema', () => {
  const validClaims = {
    sub: 'user-123',
    iss: 'https://auth.example.com',
    aud: ['my-app'],
    iat: new Date(),
    exp: new Date(Date.now() + 3600 * 1000),
  };

  it('accepts valid minimal claims', () => {
    const result = ClaimsSchema.safeParse(validClaims);
    expect(result.success).toBe(true);
  });

  it('accepts valid claims with optional fields', () => {
    const result = ClaimsSchema.safeParse({
      ...validClaims,
      scope: ['read', 'write'],
      roles: ['admin'],
      teams: ['platform'],
      tenant: 'acme',
      ext: { customField: 'value' },
    });
    expect(result.success).toBe(true);
  });

  it('rejects sub exceeding 256 characters', () => {
    const result = ClaimsSchema.safeParse({
      ...validClaims,
      sub: 'a'.repeat(257),
    });
    expect(result.success).toBe(false);
  });

  it('rejects missing required fields', () => {
    const result = ClaimsSchema.safeParse({ sub: 'user-123' });
    expect(result.success).toBe(false);
  });

  it('rejects non-array aud', () => {
    const result = ClaimsSchema.safeParse({ ...validClaims, aud: 'single-string' });
    expect(result.success).toBe(false);
  });
});

describe('TokenSetSchema', () => {
  const validTokenSet = {
    access_token: 'eyJhbGciOiJSUzI1NiJ9.test.sig',
    expires_in: 3600,
    token_type: 'Bearer' as const,
  };

  it('accepts a valid token set', () => {
    const result = TokenSetSchema.safeParse(validTokenSet);
    expect(result.success).toBe(true);
  });

  it('accepts optional id_token and refresh_token', () => {
    const result = TokenSetSchema.safeParse({
      ...validTokenSet,
      id_token: 'eyJhbGciOiJSUzI1NiJ9.id.sig',
      refresh_token: 'refresh-token-value',
    });
    expect(result.success).toBe(true);
  });

  it('rejects wrong token_type', () => {
    const result = TokenSetSchema.safeParse({ ...validTokenSet, token_type: 'Basic' });
    expect(result.success).toBe(false);
  });

  it('rejects missing access_token', () => {
    const result = TokenSetSchema.safeParse({ expires_in: 3600, token_type: 'Bearer' });
    expect(result.success).toBe(false);
  });

  it('rejects non-numeric expires_in', () => {
    const result = TokenSetSchema.safeParse({ ...validTokenSet, expires_in: '3600' });
    expect(result.success).toBe(false);
  });
});

describe('RoleSchema', () => {
  it('accepts valid role', () => {
    const result = RoleSchema.safeParse({ name: 'admin', scopes: ['read', 'write'] });
    expect(result.success).toBe(true);
  });

  it('accepts role with empty scopes', () => {
    const result = RoleSchema.safeParse({ name: 'viewer', scopes: [] });
    expect(result.success).toBe(true);
  });

  it('rejects missing name', () => {
    const result = RoleSchema.safeParse({ scopes: ['read'] });
    expect(result.success).toBe(false);
  });
});

describe('RBACConfigSchema', () => {
  it('accepts valid RBAC config', () => {
    const result = RBACConfigSchema.safeParse({
      roles: [
        { name: 'admin', scopes: ['read', 'write', 'delete'] },
        { name: 'viewer', scopes: ['read'] },
      ],
    });
    expect(result.success).toBe(true);
  });

  it('accepts empty roles array', () => {
    const result = RBACConfigSchema.safeParse({ roles: [] });
    expect(result.success).toBe(true);
  });
});

describe('EventTypeSchema', () => {
  it('accepts all defined event types', () => {
    const types = [
      'auth.login',
      'auth.logout',
      'auth.login_failed',
      'authz.access_granted',
      'authz.access_denied',
      'resource.created',
      'resource.read',
      'resource.updated',
      'resource.deleted',
      'admin.user_created',
    ] as const;

    for (const type of types) {
      const result = EventTypeSchema.safeParse(type);
      expect(result.success).toBe(true);
    }
  });

  it('rejects unknown event types', () => {
    const result = EventTypeSchema.safeParse('unknown.event');
    expect(result.success).toBe(false);
  });
});

describe('OutcomeSchema', () => {
  it('accepts success, failure, error', () => {
    for (const outcome of ['success', 'failure', 'error'] as const) {
      expect(OutcomeSchema.safeParse(outcome).success).toBe(true);
    }
  });

  it('rejects unknown outcomes', () => {
    expect(OutcomeSchema.safeParse('pending').success).toBe(false);
  });
});

describe('AuditEventSchema', () => {
  const validEvent = {
    type: 'auth.login' as const,
    outcome: 'success' as const,
    actor: { sub: 'user-123' },
  };

  it('accepts a minimal valid audit event', () => {
    const result = AuditEventSchema.safeParse(validEvent);
    expect(result.success).toBe(true);
  });

  it('accepts a full audit event', () => {
    const result = AuditEventSchema.safeParse({
      ...validEvent,
      actor: { sub: 'user-123', tenant: 'acme' },
      resource: { type: 'document', id: 'doc-456' },
      metadata: { ip: '192.168.1.1' },
      timestamp: new Date().toISOString(),
      traceId: 'trace-abc',
    });
    expect(result.success).toBe(true);
  });

  it('rejects event with invalid type', () => {
    const result = AuditEventSchema.safeParse({ ...validEvent, type: 'invalid.event' });
    expect(result.success).toBe(false);
  });

  it('rejects event missing actor', () => {
    const result = AuditEventSchema.safeParse({ type: 'auth.login', outcome: 'success' });
    expect(result.success).toBe(false);
  });
});
