import { describe, it, expect } from 'vitest';
import { z } from 'zod';

// Import utility functions to verify they're accessible
import {
  buildOAuth2Url,
  buildCustomOAuth2Url,
  buildOIDCUrl,
  generateState,
  validateState,
  getProviderLabel,
  getProviderColors,
  buildSAMLRequest,
  buildSAMLRedirectUrl,
  initiateSAMLLogin,
  validateRelayState,
} from '../index';

describe('OAuth2 utility function exports', () => {
  it('exports buildOAuth2Url', () => {
    expect(buildOAuth2Url).toBeTypeOf('function');
  });

  it('exports buildCustomOAuth2Url', () => {
    expect(buildCustomOAuth2Url).toBeTypeOf('function');
  });

  it('exports buildOIDCUrl', () => {
    expect(buildOIDCUrl).toBeTypeOf('function');
  });

  it('exports generateState', () => {
    expect(generateState).toBeTypeOf('function');
  });

  it('exports validateState', () => {
    expect(validateState).toBeTypeOf('function');
  });

  it('exports getProviderLabel', () => {
    expect(getProviderLabel).toBeTypeOf('function');
  });

  it('exports getProviderColors', () => {
    expect(getProviderColors).toBeTypeOf('function');
  });
});

describe('SAML utility function exports', () => {
  it('exports buildSAMLRequest', () => {
    expect(buildSAMLRequest).toBeTypeOf('function');
  });

  it('exports buildSAMLRedirectUrl', () => {
    expect(buildSAMLRedirectUrl).toBeTypeOf('function');
  });

  it('exports initiateSAMLLogin', () => {
    expect(initiateSAMLLogin).toBeTypeOf('function');
  });

  it('exports validateRelayState', () => {
    expect(validateRelayState).toBeTypeOf('function');
  });
});

describe('Zod re-export', () => {
  it('zod is available for schema validation', () => {
    const schema = z.object({
      name: z.string(),
      email: z.string().email(),
    });
    const result = schema.safeParse({ name: 'Test', email: 'test@example.com' });
    expect(result.success).toBe(true);
  });

  it('zod validation fails for invalid data', () => {
    const schema = z.object({
      name: z.string(),
      email: z.string().email(),
    });
    const result = schema.safeParse({ name: 'Test', email: 'invalid-email' });
    expect(result.success).toBe(false);
  });
});
