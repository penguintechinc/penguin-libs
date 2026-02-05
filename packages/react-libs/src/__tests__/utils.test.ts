import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  generateState,
  validateState,
  getProviderLabel,
  getProviderColors,
  parseVersion,
  buildSAMLRequest,
  buildSAMLRedirectUrl,
  validateRelayState,
  initiateSAMLLogin,
} from '../index';
import type { BuiltInOAuth2Provider } from '../index';

describe('OAuth utilities', () => {
  beforeEach(() => {
    // Mock sessionStorage for browser environment
    const sessionStorageMock = (() => {
      let store: Record<string, string> = {};
      return {
        getItem: (key: string) => store[key] || null,
        setItem: (key: string, value: string) => {
          store[key] = value.toString();
        },
        removeItem: (key: string) => {
          delete store[key];
        },
        clear: () => {
          store = {};
        },
      };
    })();
    Object.defineProperty(global, 'sessionStorage', {
      value: sessionStorageMock,
      writable: true,
    });
  });

  it('generateState returns a string', () => {
    const state = generateState();
    expect(state).toBeTypeOf('string');
    expect(state.length).toBeGreaterThan(0);
  });

  it('generateState creates unique values', () => {
    const state1 = generateState();
    const state2 = generateState();
    expect(state1).not.toBe(state2);
  });

  it('validateState returns boolean', () => {
    const state = generateState();
    const result = validateState(state);
    expect(typeof result).toBe('boolean');
  });

  it('getProviderLabel returns label for known providers', () => {
    const config: BuiltInOAuth2Provider = {
      provider: 'google',
      clientId: 'test-client-id',
      redirectUri: 'http://localhost/callback',
    };
    const label = getProviderLabel(config);
    expect(label).toBeTypeOf('string');
    expect(label.length).toBeGreaterThan(0);
  });

  it('getProviderLabel returns custom label when provided', () => {
    const config: BuiltInOAuth2Provider = {
      provider: 'google',
      clientId: 'test-client-id',
      redirectUri: 'http://localhost/callback',
      label: 'Custom Label',
    };
    const label = getProviderLabel(config);
    expect(label).toBe('Custom Label');
  });

  it('getProviderColors returns color config for known providers', () => {
    const colors = getProviderColors('google');
    expect(colors).toBeDefined();
    expect(typeof colors).toBe('object');
  });
});

describe('Version utilities', () => {
  it('parseVersion handles valid version strings', () => {
    const result = parseVersion('1.2.3.1234567890');
    expect(result).toBeDefined();
    expect(result.major).toBe(1);
    expect(result.minor).toBe(2);
    expect(result.patch).toBe(3);
    expect(result.buildEpoch).toBe(1234567890);
  });

  it('parseVersion handles version without build', () => {
    const result = parseVersion('1.2.3');
    expect(result).toBeDefined();
    expect(result.major).toBe(1);
    expect(result.minor).toBe(2);
    expect(result.patch).toBe(3);
  });

  it('parseVersion handles invalid version strings', () => {
    const result = parseVersion('invalid');
    expect(result).toBeDefined();
  });

  it('parseVersion handles v-prefixed versions', () => {
    const result = parseVersion('v1.2.3');
    expect(result).toBeDefined();
    expect(result.major).toBe(1);
  });

  it('parseVersion returns semver string', () => {
    const result = parseVersion('1.2.3');
    expect(result.semver).toBe('1.2.3');
  });
});

describe('SAML utilities', () => {
  it('buildSAMLRequest is a function', () => {
    expect(buildSAMLRequest).toBeTypeOf('function');
  });

  it('buildSAMLRedirectUrl is a function', () => {
    expect(buildSAMLRedirectUrl).toBeTypeOf('function');
  });

  it('validateRelayState is a function', () => {
    expect(validateRelayState).toBeTypeOf('function');
  });

  it('initiateSAMLLogin is a function', () => {
    expect(initiateSAMLLogin).toBeTypeOf('function');
  });
});
