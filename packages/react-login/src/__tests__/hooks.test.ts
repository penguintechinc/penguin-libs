import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useCaptcha } from '../hooks/useCaptcha';
import { useCookieConsent } from '../hooks/useCookieConsent';
import type { CaptchaConfig, GDPRConfig } from '../types';

describe('useCaptcha Hook', () => {
  const mockCaptchaConfig: CaptchaConfig = {
    enabled: true,
    provider: 'altcha',
    challengeUrl: 'http://localhost:3000/captcha',
    failedAttemptsThreshold: 3,
    resetTimeoutMs: 900000, // 15 minutes
  };

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  it('initializes with zero failed attempts', () => {
    const { result } = renderHook(() => useCaptcha(mockCaptchaConfig));

    expect(result.current.failedAttempts).toBe(0);
    expect(result.current.showCaptcha).toBe(false);
    expect(result.current.captchaToken).toBeNull();
  });

  it('shows CAPTCHA after exceeding failed attempts threshold', () => {
    const { result } = renderHook(() => useCaptcha(mockCaptchaConfig));

    act(() => {
      result.current.incrementFailedAttempts();
      result.current.incrementFailedAttempts();
      result.current.incrementFailedAttempts();
    });

    expect(result.current.failedAttempts).toBe(3);
    expect(result.current.showCaptcha).toBe(true);
  });

  it('does not show CAPTCHA below threshold', () => {
    const { result } = renderHook(() => useCaptcha(mockCaptchaConfig));

    act(() => {
      result.current.incrementFailedAttempts();
      result.current.incrementFailedAttempts();
    });

    expect(result.current.failedAttempts).toBe(2);
    expect(result.current.showCaptcha).toBe(false);
  });

  it('stores CAPTCHA token when verified', () => {
    const { result } = renderHook(() => useCaptcha(mockCaptchaConfig));

    act(() => {
      result.current.setCaptchaToken('captcha-token-123');
    });

    expect(result.current.captchaToken).toBe('captcha-token-123');
    expect(result.current.isVerified).toBe(true);
  });

  it('clears CAPTCHA token when reset', () => {
    const { result } = renderHook(() => useCaptcha(mockCaptchaConfig));

    act(() => {
      result.current.setCaptchaToken('captcha-token-123');
    });

    expect(result.current.captchaToken).toBe('captcha-token-123');

    act(() => {
      result.current.setCaptchaToken(null);
    });

    expect(result.current.captchaToken).toBeNull();
    expect(result.current.isVerified).toBe(false);
  });

  it('resets failed attempts counter', () => {
    const { result } = renderHook(() => useCaptcha(mockCaptchaConfig));

    act(() => {
      result.current.incrementFailedAttempts();
      result.current.incrementFailedAttempts();
    });

    expect(result.current.failedAttempts).toBe(2);

    act(() => {
      result.current.resetFailedAttempts();
    });

    expect(result.current.failedAttempts).toBe(0);
    expect(result.current.showCaptcha).toBe(false);
  });

  it('disables CAPTCHA when disabled in config', () => {
    const config: CaptchaConfig = {
      ...mockCaptchaConfig,
      enabled: false,
    };

    const { result } = renderHook(() => useCaptcha(config));

    act(() => {
      result.current.incrementFailedAttempts();
      result.current.incrementFailedAttempts();
      result.current.incrementFailedAttempts();
      result.current.incrementFailedAttempts();
    });

    expect(result.current.showCaptcha).toBe(false);
  });

  it('uses custom failed attempts threshold', () => {
    const config: CaptchaConfig = {
      ...mockCaptchaConfig,
      failedAttemptsThreshold: 5,
    };

    const { result } = renderHook(() => useCaptcha(config));

    act(() => {
      for (let i = 0; i < 4; i++) {
        result.current.incrementFailedAttempts();
      }
    });

    expect(result.current.showCaptcha).toBe(false);

    act(() => {
      result.current.incrementFailedAttempts();
    });

    expect(result.current.showCaptcha).toBe(true);
  });

  it('maintains failed attempts across hook lifecycle', () => {
    const { result, rerender } = renderHook(() => useCaptcha(mockCaptchaConfig));

    act(() => {
      result.current.incrementFailedAttempts();
      result.current.incrementFailedAttempts();
    });

    expect(result.current.failedAttempts).toBe(2);

    rerender();

    expect(result.current.failedAttempts).toBe(2);
  });
});

describe('useCookieConsent Hook', () => {
  const mockGDPRConfig: GDPRConfig = {
    enabled: true,
    privacyPolicyUrl: 'http://localhost:3000/privacy',
    cookiePolicyUrl: 'http://localhost:3000/cookies',
    consentText: 'We use cookies to enhance your experience.',
    showPreferences: true,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it('shows banner initially when GDPR is enabled', () => {
    const { result } = renderHook(() => useCookieConsent(mockGDPRConfig));

    expect(result.current.showBanner).toBe(true);
    expect(result.current.canInteract).toBe(false);
  });

  it('hides banner when GDPR is disabled', () => {
    const config: GDPRConfig = {
      ...mockGDPRConfig,
      enabled: false,
    };

    const { result } = renderHook(() => useCookieConsent(config));

    expect(result.current.showBanner).toBe(false);
    expect(result.current.canInteract).toBe(true);
  });

  it('allows interaction when consent is accepted', () => {
    const { result } = renderHook(() => useCookieConsent(mockGDPRConfig));

    expect(result.current.canInteract).toBe(false);

    act(() => {
      result.current.acceptAll();
    });

    expect(result.current.canInteract).toBe(true);
    expect(result.current.showBanner).toBe(false);
  });

  it('saves consent to localStorage when accepted', () => {
    const { result } = renderHook(() => useCookieConsent(mockGDPRConfig));

    act(() => {
      result.current.acceptAll();
    });

    const stored = localStorage.getItem('gdpr_consent');
    expect(stored).not.toBeNull();

    const consent = JSON.parse(stored!);
    expect(consent.accepted).toBe(true);
    expect(consent.essential).toBe(true);
    expect(consent.functional).toBe(true);
    expect(consent.analytics).toBe(true);
    expect(consent.marketing).toBe(true);
  });

  it('restores consent from localStorage on mount', () => {
    const storedConsent = {
      accepted: true,
      essential: true,
      functional: true,
      analytics: true,
      marketing: true,
      timestamp: Date.now(),
    };

    localStorage.setItem('gdpr_consent', JSON.stringify(storedConsent));

    const { result } = renderHook(() => useCookieConsent(mockGDPRConfig));

    expect(result.current.canInteract).toBe(true);
    expect(result.current.showBanner).toBe(false);
  });

  it('acceptEssential only accepts essential cookies', () => {
    const { result } = renderHook(() => useCookieConsent(mockGDPRConfig));

    act(() => {
      result.current.acceptEssential();
    });

    const stored = localStorage.getItem('gdpr_consent');
    const consent = JSON.parse(stored!);

    expect(consent.essential).toBe(true);
    expect(consent.functional).toBe(false);
    expect(consent.analytics).toBe(false);
    expect(consent.marketing).toBe(false);
  });

  it('savePreferences saves custom preferences', () => {
    const { result } = renderHook(() => useCookieConsent(mockGDPRConfig));

    const preferences = {
      accepted: true,
      essential: true,
      functional: true,
      analytics: false,
      marketing: false,
    };

    act(() => {
      result.current.savePreferences(preferences);
    });

    const stored = localStorage.getItem('gdpr_consent');
    const consent = JSON.parse(stored!);

    expect(consent.functional).toBe(true);
    expect(consent.analytics).toBe(false);
    expect(consent.marketing).toBe(false);
  });

  it('allows interaction immediately after accept', () => {
    const { result } = renderHook(() => useCookieConsent(mockGDPRConfig));

    expect(result.current.canInteract).toBe(false);

    act(() => {
      result.current.acceptAll();
    });

    expect(result.current.canInteract).toBe(true);
  });

  it('includes timestamp when saving consent', () => {
    const { result } = renderHook(() => useCookieConsent(mockGDPRConfig));

    act(() => {
      result.current.acceptAll();
    });

    const stored = localStorage.getItem('gdpr_consent');
    const consent = JSON.parse(stored!);

    expect(consent.timestamp).toBeDefined();
    expect(typeof consent.timestamp).toBe('number');
    expect(consent.timestamp).toBeGreaterThan(0);
  });

  it('respects initial accepted state from localStorage', () => {
    const storedConsent = {
      accepted: false,
      essential: true,
      functional: false,
      analytics: false,
      marketing: false,
    };

    localStorage.setItem('gdpr_consent', JSON.stringify(storedConsent));

    const { result } = renderHook(() => useCookieConsent(mockGDPRConfig));

    expect(result.current.canInteract).toBe(false);
  });

  it('behavior when GDPR config is not provided', () => {
    const { result } = renderHook(() => useCookieConsent(undefined));

    // When config is not provided, use default behavior
    expect(result.current.canInteract).toBe(true);
  });
});
