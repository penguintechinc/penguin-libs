import { describe, it, expect } from 'vitest';
import { hasScope, hasAnyScope, hasAllScopes, hasRole } from '../authz/permissions.js';

describe('hasScope', () => {
  it('returns true when scope is present', () => {
    expect(hasScope(['read', 'write'], 'read')).toBe(true);
  });

  it('returns false when scope is absent', () => {
    expect(hasScope(['read', 'write'], 'delete')).toBe(false);
  });

  it('returns false for empty scopes', () => {
    expect(hasScope([], 'read')).toBe(false);
  });

  it('is case-sensitive', () => {
    expect(hasScope(['Read'], 'read')).toBe(false);
  });
});

describe('hasAnyScope', () => {
  it('returns true when at least one scope matches', () => {
    expect(hasAnyScope(['read', 'write'], ['write', 'delete'])).toBe(true);
  });

  it('returns false when no scopes match', () => {
    expect(hasAnyScope(['read'], ['write', 'delete'])).toBe(false);
  });

  it('returns false for empty user scopes', () => {
    expect(hasAnyScope([], ['read'])).toBe(false);
  });

  it('returns false for empty required scopes', () => {
    expect(hasAnyScope(['read'], [])).toBe(false);
  });
});

describe('hasAllScopes', () => {
  it('returns true when all scopes are present', () => {
    expect(hasAllScopes(['read', 'write', 'delete'], ['read', 'write'])).toBe(true);
  });

  it('returns false when any scope is missing', () => {
    expect(hasAllScopes(['read', 'write'], ['read', 'write', 'delete'])).toBe(false);
  });

  it('returns true for empty required scopes', () => {
    expect(hasAllScopes(['read'], [])).toBe(true);
  });

  it('returns false for empty user scopes with non-empty required', () => {
    expect(hasAllScopes([], ['read'])).toBe(false);
  });

  it('returns true when scopes exactly match', () => {
    expect(hasAllScopes(['read', 'write'], ['read', 'write'])).toBe(true);
  });
});

describe('hasRole', () => {
  it('returns true when role is present', () => {
    expect(hasRole(['admin', 'viewer'], 'admin')).toBe(true);
  });

  it('returns false when role is absent', () => {
    expect(hasRole(['viewer'], 'admin')).toBe(false);
  });

  it('returns false for empty roles', () => {
    expect(hasRole([], 'admin')).toBe(false);
  });

  it('is case-sensitive', () => {
    expect(hasRole(['Admin'], 'admin')).toBe(false);
  });
});
