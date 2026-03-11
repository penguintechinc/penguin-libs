import { describe, it, expect } from 'vitest';
import { makeObject, makeClaims, makeTokenSet, makeAuthContextValue } from '../factories.js';

describe('makeObject', () => {
  it('returns defaults when no overrides given', () => {
    const result = makeObject({ a: 1, b: 2 });
    expect(result).toEqual({ a: 1, b: 2 });
  });

  it('merges overrides onto defaults', () => {
    const result = makeObject({ a: 1, b: 2 }, { b: 99 });
    expect(result).toEqual({ a: 1, b: 99 });
  });

  it('does not mutate the defaults object', () => {
    const defaults = { a: 1, b: 2 };
    makeObject(defaults, { b: 99 });
    expect(defaults.b).toBe(2);
  });
});

describe('makeClaims', () => {
  it('returns an object with required fields', () => {
    const claims = makeClaims();
    expect(claims.sub).toBe('user-123');
    expect(claims.scope).toContain('read');
    expect(claims.roles).toContain('admin');
    expect(claims.exp.getTime()).toBeGreaterThan(Date.now());
  });

  it('applies overrides', () => {
    const claims = makeClaims({ sub: 'custom-user', scope: ['admin'] });
    expect(claims.sub).toBe('custom-user');
    expect(claims.scope).toEqual(['admin']);
  });
});

describe('makeTokenSet', () => {
  it('returns an object with required fields', () => {
    const tokens = makeTokenSet();
    expect(tokens.access_token).toBe('test-access-token');
    expect(tokens.token_type).toBe('Bearer');
    expect(tokens.expires_in).toBe(3600);
  });

  it('applies overrides', () => {
    const tokens = makeTokenSet({ access_token: 'custom-token', refresh_token: 'refresh' });
    expect(tokens.access_token).toBe('custom-token');
    expect(tokens.refresh_token).toBe('refresh');
  });
});

describe('makeAuthContextValue', () => {
  it('returns an authenticated context by default', () => {
    const ctx = makeAuthContextValue();
    expect(ctx.isAuthenticated).toBe(true);
    expect(ctx.isLoading).toBe(false);
    expect(ctx.user).not.toBeNull();
    expect(ctx.accessToken).toBe('test-token');
  });

  it('applies overrides', () => {
    const ctx = makeAuthContextValue({ isAuthenticated: false, user: null, accessToken: null });
    expect(ctx.isAuthenticated).toBe(false);
    expect(ctx.user).toBeNull();
    expect(ctx.accessToken).toBeNull();
  });

  it('provides function stubs for login and logout', () => {
    const ctx = makeAuthContextValue();
    expect(typeof ctx.login).toBe('function');
    expect(typeof ctx.logout).toBe('function');
  });
});
