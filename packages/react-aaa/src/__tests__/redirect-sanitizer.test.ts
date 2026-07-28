import { sanitizeRedirectPath } from '../utils/redirect-sanitizer.js';
import { describe, it, expect } from 'vitest';

describe('sanitizeRedirectPath', () => {
  it('accepts valid same-origin paths', () => {
    expect(sanitizeRedirectPath('/')).toBe('/');
    expect(sanitizeRedirectPath('/dashboard')).toBe('/dashboard');
    expect(sanitizeRedirectPath('/users/profile')).toBe('/users/profile');
    expect(sanitizeRedirectPath('/path?query=param#hash')).toBe('/path?query=param#hash');
  });

  it('rejects protocol-relative URLs (//)—open redirect vector', () => {
    expect(sanitizeRedirectPath('//')).toBe('/');
    expect(sanitizeRedirectPath('//example.com')).toBe('/');
    expect(sanitizeRedirectPath('//evil.com/path')).toBe('/');
  });

  it('rejects backslash tricks (\\)—browsers treat as //', () => {
    expect(sanitizeRedirectPath('\\')).toBe('/');
    expect(sanitizeRedirectPath('\\\\example.com')).toBe('/');
  });

  it('rejects absolute URLs with protocols—open redirect', () => {
    expect(sanitizeRedirectPath('http://example.com')).toBe('/');
    expect(sanitizeRedirectPath('https://evil.com')).toBe('/');
    expect(sanitizeRedirectPath('ftp://files.example.com')).toBe('/');
  });

  it('rejects data: and javascript: URLs', () => {
    expect(sanitizeRedirectPath('data:text/html,<script>alert("xss")</script>')).toBe('/');
    expect(sanitizeRedirectPath('javascript:alert("xss")')).toBe('/');
    expect(sanitizeRedirectPath('JavaScript:alert("xss")')).toBe('/');
  });

  it('rejects non-relative paths', () => {
    expect(sanitizeRedirectPath('example.com')).toBe('/');
    expect(sanitizeRedirectPath('path/to/page')).toBe('/');
    expect(sanitizeRedirectPath('..')).toBe('/');
  });

  it('rejects encoded attack variants', () => {
    // %2F%2F decodes to //
    expect(sanitizeRedirectPath('%2F%2Fevil.com')).toBe('/');
    // %5C decodes to backslash
    expect(sanitizeRedirectPath('%5C%5Cevil.com')).toBe('/');
  });

  it('handles null/undefined/empty strings with default', () => {
    expect(sanitizeRedirectPath('')).toBe('/');
    expect(sanitizeRedirectPath('   ')).toBe('/');
    expect(sanitizeRedirectPath(null as unknown as string)).toBe('/');
    expect(sanitizeRedirectPath(undefined as unknown as string)).toBe('/');
  });

  it('accepts custom default fallback', () => {
    expect(sanitizeRedirectPath('//evil.com', '/home')).toBe('/home');
    expect(sanitizeRedirectPath('', '/dashboard')).toBe('/dashboard');
  });

  it('handles edge cases with whitespace', () => {
    expect(sanitizeRedirectPath('  /dashboard  ')).toBe('/dashboard');
    expect(sanitizeRedirectPath('\t/page\n')).toBe('/page');
  });

  it('preserves trailing slashes', () => {
    expect(sanitizeRedirectPath('/dashboard/')).toBe('/dashboard/');
  });

  it('handles multiple slashes at start', () => {
    expect(sanitizeRedirectPath('///path')).toBe('/');
  });

  it('rejects invalid characters via improper encoding', () => {
    // Invalid UTF-8 sequence → should not crash, return default
    expect(() => sanitizeRedirectPath('%FF%FE')).not.toThrow();
  });

  it('blocks /\\ attack vector (slash-backslash)', () => {
    expect(sanitizeRedirectPath('/\\evil.com')).toBe('/');
    expect(sanitizeRedirectPath('/\\\\evil.com')).toBe('/');
    expect(sanitizeRedirectPath('/\\test')).toBe('/');
  });

  it('blocks %5C variants (percent-encoded backslash)', () => {
    expect(sanitizeRedirectPath('/%5C/evil.com')).toBe('/');
    expect(sanitizeRedirectPath('/%5C%5Cevil.com')).toBe('/');
    expect(sanitizeRedirectPath('/%2f%5c/evil.com')).toBe('/');
  });
});
