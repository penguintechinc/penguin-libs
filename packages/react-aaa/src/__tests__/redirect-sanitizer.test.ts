import { sanitizeRedirectPath } from '../utils/redirect-sanitizer.js';
import { describe, it, expect, afterEach, vi } from 'vitest';

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

  it('rejects paths containing whitespace (regression: F-01)', () => {
    expect(sanitizeRedirectPath('  /dashboard  ')).toBe('/');
    expect(sanitizeRedirectPath('\t/page\n')).toBe('/');
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

describe('sanitizeRedirectPath regression: F-01 (control chars, whitespace, backslash)', () => {
  const DEFAULT = '/home';

  it('regression: F-01 falls back on literal tab in /\\t/evil.example', () => {
    expect(sanitizeRedirectPath('/\t/evil.example', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on encoded tab %09', () => {
    expect(sanitizeRedirectPath('/%09/evil.example', DEFAULT)).toBe(DEFAULT);
    expect(sanitizeRedirectPath('%2F%09%2Fevil', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on literal newline', () => {
    expect(sanitizeRedirectPath('/\n/evil.example', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on encoded newline %0A', () => {
    expect(sanitizeRedirectPath('/%0A/evil.example', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on literal carriage return', () => {
    expect(sanitizeRedirectPath('/\r/evil.example', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on encoded carriage return %0D', () => {
    expect(sanitizeRedirectPath('/%0D/evil.example', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on literal backslash', () => {
    expect(sanitizeRedirectPath('\\', DEFAULT)).toBe(DEFAULT);
    expect(sanitizeRedirectPath('/\\evil', DEFAULT)).toBe(DEFAULT);
    expect(sanitizeRedirectPath('/a\\b', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on encoded backslash %5C', () => {
    expect(sanitizeRedirectPath('/%5Cevil', DEFAULT)).toBe(DEFAULT);
    expect(sanitizeRedirectPath('%2F%5Cevil', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on protocol-relative //evil', () => {
    expect(sanitizeRedirectPath('//evil', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on /\\evil', () => {
    expect(sanitizeRedirectPath('/\\evil', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on https://evil', () => {
    expect(sanitizeRedirectPath('https://evil', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on javascript:alert(1)', () => {
    expect(sanitizeRedirectPath('javascript:alert(1)', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on encoded //evil (%2F%2Fevil)', () => {
    expect(sanitizeRedirectPath('%2F%2Fevil', DEFAULT)).toBe(DEFAULT);
    expect(sanitizeRedirectPath('/%2F%2Fevil', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back on malformed percent-encoding', () => {
    expect(sanitizeRedirectPath('/%E0%A4%A', DEFAULT)).toBe(DEFAULT);
  });

  it('regression: F-01 falls back when no window is available', () => {
    const original = globalThis.window;
    // @ts-expect-error simulate non-browser environment
    delete globalThis.window;
    try {
      expect(sanitizeRedirectPath('/dashboard', DEFAULT)).toBe(DEFAULT);
    } finally {
      globalThis.window = original;
    }
  });

  it('regression: F-01 accepts a safe same-origin path with query and hash', () => {
    expect(sanitizeRedirectPath('/dashboard?x=1#y', DEFAULT)).toBe('/dashboard?x=1#y');
  });
});

describe('sanitizeRedirectPath regression: F-01 defensive resolution branches', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('regression: F-01 falls back when resolved origin differs from current origin', () => {
    class OtherOriginURL {
      origin = 'https://other.example';
      pathname = '/';
      search = '';
      hash = '';
      constructor(_path: string, _base: string) {}
    }
    vi.stubGlobal('URL', OtherOriginURL);
    expect(sanitizeRedirectPath('/dashboard', '/home')).toBe('/home');
  });

  it('regression: F-01 falls back when URL resolution throws', () => {
    class ThrowingURL {
      constructor(_path: string, _base: string) {
        throw new TypeError('Invalid URL');
      }
    }
    vi.stubGlobal('URL', ThrowingURL);
    expect(sanitizeRedirectPath('/dashboard', '/home')).toBe('/home');
  });
});

describe('sanitizeRedirectPath regression: dot-segment protocol-relative bypass', () => {
  it.each([
    '/.//evil.com',
    '/..//evil.com',
    '/%2e%2e//evil.com',
    '/%2E%2E//evil.com',
    '/./%2F%2Fevil.com',
    '/a/../..//evil.com',
    '/a/./b',
    '/a/../b',
    '/%2e/x',
    '/x/%2E%2e/y',
  ])('rejects %s', (input) => {
    expect(sanitizeRedirectPath(input, '/home')).toBe('/home');
  });

  it('still accepts dots that are not whole segments', () => {
    expect(sanitizeRedirectPath('/file.name/..hidden/a.b')).toBe('/file.name/..hidden/a.b');
  });

  it('rejects when resolution yields a // or /\\ pathname', () => {
    class FakeURL {
      origin = window.location.origin;
      pathname: string;
      search = '';
      hash = '';
      constructor(_p: string, _b: string) {
        this.pathname = FakeURL.next;
      }
      static next = '//evil.com';
    }
    vi.stubGlobal('URL', FakeURL);
    try {
      FakeURL.next = '//evil.com';
      expect(sanitizeRedirectPath('/ok', '/home')).toBe('/home');
      FakeURL.next = '/\\evil.com';
      expect(sanitizeRedirectPath('/ok', '/home')).toBe('/home');
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
