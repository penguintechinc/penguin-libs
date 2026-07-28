import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useCaptcha } from './useCaptcha';
import type { CaptchaConfig } from '../types';

const STORAGE_KEY = 'login_failed_attempts';

function enabledConfig(overrides?: Partial<CaptchaConfig>): CaptchaConfig {
  return {
    enabled: true,
    provider: 'altcha',
    challengeUrl: 'https://example.com/captcha/challenge',
    failedAttemptsThreshold: 3,
    ...overrides,
  };
}

describe('useCaptcha', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  // ---------------------------------------------------------------------------
  // Initial state – disabled
  // ---------------------------------------------------------------------------

  describe('disabled (no config or enabled=false)', () => {
    it('showCaptcha is false', () => {
      const { result } = renderHook(() => useCaptcha(undefined));
      expect(result.current.showCaptcha).toBe(false);
    });

    it('isVerified is true (bypass when disabled)', () => {
      const { result } = renderHook(() => useCaptcha(undefined));
      expect(result.current.isVerified).toBe(true);
    });

    it('incrementFailedAttempts does nothing when disabled', () => {
      const { result } = renderHook(() => useCaptcha(undefined));
      act(() => result.current.incrementFailedAttempts());
      expect(result.current.failedAttempts).toBe(0);
    });

    it('resetFailedAttempts does nothing when disabled', () => {
      const { result } = renderHook(() => useCaptcha({ enabled: false, provider: 'altcha', challengeUrl: '' }));
      act(() => result.current.resetFailedAttempts());
      expect(result.current.failedAttempts).toBe(0);
    });
  });

  // ---------------------------------------------------------------------------
  // Initial state – enabled
  // ---------------------------------------------------------------------------

  describe('enabled', () => {
    it('starts with failedAttempts=0 when no storage', () => {
      const { result } = renderHook(() => useCaptcha(enabledConfig()));
      expect(result.current.failedAttempts).toBe(0);
    });

    it('showCaptcha is false below threshold', () => {
      const { result } = renderHook(() => useCaptcha(enabledConfig({ failedAttemptsThreshold: 3 })));
      expect(result.current.showCaptcha).toBe(false);
    });

    it('isVerified is false when captchaToken is null', () => {
      const { result } = renderHook(() => useCaptcha(enabledConfig()));
      expect(result.current.isVerified).toBe(false);
    });

    it('setCaptchaToken sets token and makes isVerified true', () => {
      const { result } = renderHook(() => useCaptcha(enabledConfig()));
      act(() => result.current.setCaptchaToken('tok_test'));
      expect(result.current.captchaToken).toBe('tok_test');
      expect(result.current.isVerified).toBe(true);
    });
  });

  // ---------------------------------------------------------------------------
  // incrementFailedAttempts
  // ---------------------------------------------------------------------------

  describe('incrementFailedAttempts', () => {
    it('increments count on each call', () => {
      const { result } = renderHook(() => useCaptcha(enabledConfig()));
      act(() => result.current.incrementFailedAttempts());
      act(() => result.current.incrementFailedAttempts());
      expect(result.current.failedAttempts).toBe(2);
    });

    it('persists count to localStorage', () => {
      const { result } = renderHook(() => useCaptcha(enabledConfig()));
      act(() => result.current.incrementFailedAttempts());
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
      expect(stored.count).toBe(1);
    });

    it('shows CAPTCHA once threshold is reached', () => {
      const { result } = renderHook(() => useCaptcha(enabledConfig({ failedAttemptsThreshold: 2 })));
      act(() => result.current.incrementFailedAttempts());
      act(() => result.current.incrementFailedAttempts());
      expect(result.current.showCaptcha).toBe(true);
    });

    it('resets captchaToken after each failure', () => {
      const { result } = renderHook(() => useCaptcha(enabledConfig()));
      act(() => result.current.setCaptchaToken('tok'));
      act(() => result.current.incrementFailedAttempts());
      expect(result.current.captchaToken).toBeNull();
    });
  });

  // ---------------------------------------------------------------------------
  // resetFailedAttempts
  // ---------------------------------------------------------------------------

  describe('resetFailedAttempts', () => {
    it('sets failedAttempts back to 0', () => {
      const { result } = renderHook(() => useCaptcha(enabledConfig()));
      act(() => result.current.incrementFailedAttempts());
      act(() => result.current.incrementFailedAttempts());
      act(() => result.current.resetFailedAttempts());
      expect(result.current.failedAttempts).toBe(0);
    });

    it('removes localStorage entry', () => {
      const { result } = renderHook(() => useCaptcha(enabledConfig()));
      act(() => result.current.incrementFailedAttempts());
      act(() => result.current.resetFailedAttempts());
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it('hides CAPTCHA after reset', () => {
      const { result } = renderHook(() => useCaptcha(enabledConfig({ failedAttemptsThreshold: 1 })));
      act(() => result.current.incrementFailedAttempts());
      expect(result.current.showCaptcha).toBe(true);
      act(() => result.current.resetFailedAttempts());
      expect(result.current.showCaptcha).toBe(false);
    });
  });

  // ---------------------------------------------------------------------------
  // Loading stored attempts on mount
  // ---------------------------------------------------------------------------

  describe('loading stored attempts', () => {
    it('loads valid stored attempts on mount', () => {
      const data = { count: 4, timestamp: Date.now() };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
      const { result } = renderHook(() => useCaptcha(enabledConfig({ failedAttemptsThreshold: 3 })));
      expect(result.current.failedAttempts).toBe(4);
      expect(result.current.showCaptcha).toBe(true);
    });

    it('resets expired stored attempts on mount', () => {
      const data = { count: 5, timestamp: Date.now() - 1_000_000 }; // very old
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
      const { result } = renderHook(() => useCaptcha(enabledConfig({ resetTimeoutMs: 900000 })));
      expect(result.current.failedAttempts).toBe(0);
    });

    it('handles corrupt localStorage gracefully', () => {
      localStorage.setItem(STORAGE_KEY, 'not-valid-json');
      const { result } = renderHook(() => useCaptcha(enabledConfig()));
      expect(result.current.failedAttempts).toBe(0);
    });

    it('does not load stored attempts when disabled', () => {
      const data = { count: 10, timestamp: Date.now() };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
      const { result } = renderHook(() => useCaptcha({ enabled: false, provider: 'altcha', challengeUrl: '' }));
      expect(result.current.failedAttempts).toBe(0);
    });
  });
});
