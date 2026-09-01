import { describe, it, expect, vi } from 'vitest';
import { generatePassword } from '../components/FormModalBuilder';

describe('generatePassword (CSPRNG)', () => {
  // regression: password generation must use a cryptographically secure RNG
  // (crypto.getRandomValues), not Math.random(), since users may submit the
  // generated value as a real password. This file mirrors
  // react-form-builder/__tests__/FormModalBuilder.test.tsx's generatePassword
  // suite; keep both in sync.
  it('does not call Math.random and does call crypto.getRandomValues', () => {
    const mathRandomSpy = vi.spyOn(Math, 'random');
    const getRandomValuesSpy = vi.spyOn(crypto, 'getRandomValues');

    generatePassword(20);

    expect(mathRandomSpy).not.toHaveBeenCalled();
    expect(getRandomValuesSpy).toHaveBeenCalled();

    mathRandomSpy.mockRestore();
    getRandomValuesSpy.mockRestore();
  });

  it('returns a string of the requested length from the expected charset', () => {
    const allowedChars = /^[A-Za-z0-9]+$/;

    for (const length of [1, 8, 14, 32]) {
      const password = generatePassword(length);
      expect(password).toHaveLength(length);
      expect(password).toMatch(allowedChars);
    }
  });

  it('defaults to a length-14 password when no length is provided', () => {
    const password = generatePassword();
    expect(password).toHaveLength(14);
  });

  it('produces different output across calls (not deterministic/predictable)', () => {
    const passwords = new Set(Array.from({ length: 10 }, () => generatePassword(20)));
    expect(passwords.size).toBeGreaterThan(1);
  });
});
