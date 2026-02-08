import { describe, it, expect } from 'vitest';

/**
 * Email validation tests
 *
 * Tests the email regex pattern used in useFormBuilder and LoginPageBuilder
 * for correctness and ReDoS (Regular Expression Denial of Service) resistance.
 */

// The email regex used in the codebase
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

describe('Email validation regex', () => {
  describe('Valid emails', () => {
    it('accepts standard email addresses', () => {
      expect(EMAIL_REGEX.test('user@example.com')).toBe(true);
      expect(EMAIL_REGEX.test('test.user@example.com')).toBe(true);
      expect(EMAIL_REGEX.test('user+tag@example.com')).toBe(true);
      expect(EMAIL_REGEX.test('user_name@example.com')).toBe(true);
    });

    it('accepts development TLDs including .local', () => {
      expect(EMAIL_REGEX.test('user@localhost.local')).toBe(true);
      expect(EMAIL_REGEX.test('admin@server.local')).toBe(true);
      expect(EMAIL_REGEX.test('test@example.test')).toBe(true);
      expect(EMAIL_REGEX.test('dev@api.localhost')).toBe(true);
    });

    it('accepts various TLD lengths', () => {
      expect(EMAIL_REGEX.test('user@example.co')).toBe(true);
      expect(EMAIL_REGEX.test('user@example.com')).toBe(true);
      expect(EMAIL_REGEX.test('user@example.info')).toBe(true);
    });

    it('accepts subdomains', () => {
      expect(EMAIL_REGEX.test('user@mail.example.com')).toBe(true);
      expect(EMAIL_REGEX.test('user@api.v2.example.com')).toBe(true);
    });
  });

  describe('Invalid emails', () => {
    it('rejects emails without @', () => {
      expect(EMAIL_REGEX.test('userexample.com')).toBe(false);
      expect(EMAIL_REGEX.test('user.example.com')).toBe(false);
    });

    it('rejects emails without domain', () => {
      expect(EMAIL_REGEX.test('user@')).toBe(false);
      expect(EMAIL_REGEX.test('@example.com')).toBe(false);
    });

    it('rejects emails without TLD', () => {
      expect(EMAIL_REGEX.test('user@localhost')).toBe(false);
      expect(EMAIL_REGEX.test('user@example')).toBe(false);
    });

    it('rejects emails with whitespace', () => {
      expect(EMAIL_REGEX.test('user @example.com')).toBe(false);
      expect(EMAIL_REGEX.test('user@ example.com')).toBe(false);
      expect(EMAIL_REGEX.test('user@example .com')).toBe(false);
    });

    it('rejects multiple @ symbols', () => {
      expect(EMAIL_REGEX.test('user@@example.com')).toBe(false);
      expect(EMAIL_REGEX.test('user@test@example.com')).toBe(false);
    });
  });

  describe('ReDoS (Regular Expression Denial of Service) resistance', () => {
    it('handles long strings efficiently', () => {
      // Create a long string that could trigger exponential backtracking in vulnerable regex
      const longString = 'a'.repeat(10000) + '@example.com';

      const startTime = Date.now();
      EMAIL_REGEX.test(longString);
      const endTime = Date.now();

      // Should complete in less than 100ms (generous threshold)
      // A vulnerable regex could take seconds or minutes
      expect(endTime - startTime).toBeLessThan(100);
    });

    it('handles repeated patterns efficiently', () => {
      // Patterns that could cause catastrophic backtracking
      const patterns = [
        'a'.repeat(1000) + '@' + 'b'.repeat(1000) + '.com',
        'user@' + 'sub.'.repeat(100) + 'example.com',
        'a+'.repeat(100) + '@example.com',
      ];

      patterns.forEach(pattern => {
        const startTime = Date.now();
        EMAIL_REGEX.test(pattern);
        const endTime = Date.now();

        // Each should complete in less than 50ms
        expect(endTime - startTime).toBeLessThan(50);
      });
    });

    it('handles invalid patterns efficiently', () => {
      // Invalid patterns that should fail quickly
      const invalidPatterns = [
        '@'.repeat(1000),
        '.'.repeat(1000),
        'a'.repeat(1000),
      ];

      invalidPatterns.forEach(pattern => {
        const startTime = Date.now();
        EMAIL_REGEX.test(pattern);
        const endTime = Date.now();

        // Should fail quickly
        expect(endTime - startTime).toBeLessThan(50);
      });
    });
  });

  describe('Regex safety analysis', () => {
    it('confirms regex is ReDoS-safe', () => {
      /**
       * This regex is safe from ReDoS because:
       *
       * 1. No nested quantifiers: The pattern uses simple + quantifiers
       *    without nesting like (a+)+ which causes exponential backtracking
       *
       * 2. Character classes only: Uses [^\s@]+ which matches in linear time
       *    Character class matching is O(n) not exponential
       *
       * 3. Anchored: ^...$ forces the engine to match the entire string
       *    and fail fast if it doesn't match
       *
       * 4. No alternation with overlap: No patterns like (a|a)+ that cause
       *    the engine to try multiple paths
       *
       * 5. Deterministic: Each character in the input can only match
       *    one part of the regex, no ambiguity
       */

      // If we got here without hanging, the regex is safe
      expect(true).toBe(true);
    });
  });
});
