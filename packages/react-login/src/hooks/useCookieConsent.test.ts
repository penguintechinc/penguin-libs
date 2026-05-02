import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useCookieConsent } from './useCookieConsent';
import type { GDPRConfig } from '../types';

const STORAGE_KEY = 'gdpr_consent';

function gdprConfig(overrides?: Partial<GDPRConfig>): GDPRConfig {
  return {
    privacyPolicyUrl: 'https://example.com/privacy',
    enabled: true,
    ...overrides,
  };
}

describe('useCookieConsent', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  // ---------------------------------------------------------------------------
  // Initial state
  // ---------------------------------------------------------------------------

  describe('initial state', () => {
    it('showBanner=true when enabled and no stored consent', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      expect(result.current.showBanner).toBe(true);
    });

    it('canInteract=false when enabled and not accepted', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      expect(result.current.canInteract).toBe(false);
    });

    it('canInteract=true when GDPR disabled (no config)', () => {
      const { result } = renderHook(() => useCookieConsent(undefined));
      expect(result.current.canInteract).toBe(true);
    });

    it('showBanner=false when gdpr disabled', () => {
      const { result } = renderHook(() => useCookieConsent({ ...gdprConfig(), enabled: false }));
      expect(result.current.showBanner).toBe(false);
    });

    it('loads previous consent from localStorage', () => {
      const consent = {
        accepted: true,
        essential: true,
        functional: true,
        analytics: false,
        marketing: false,
        timestamp: Date.now(),
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(consent));
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      expect(result.current.canInteract).toBe(true);
      expect(result.current.showBanner).toBe(false);
    });

    it('falls back to default on corrupt localStorage', () => {
      localStorage.setItem(STORAGE_KEY, 'bad-json');
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      expect(result.current.canInteract).toBe(false);
    });
  });

  // ---------------------------------------------------------------------------
  // acceptAll
  // ---------------------------------------------------------------------------

  describe('acceptAll', () => {
    it('sets canInteract to true', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.acceptAll());
      expect(result.current.canInteract).toBe(true);
    });

    it('hides banner', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.acceptAll());
      expect(result.current.showBanner).toBe(false);
    });

    it('persists consent with all categories true', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.acceptAll());
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
      expect(stored.functional).toBe(true);
      expect(stored.analytics).toBe(true);
      expect(stored.marketing).toBe(true);
      expect(stored.essential).toBe(true);
    });

    it('returns the new consent object', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      let returned: unknown;
      act(() => { returned = result.current.acceptAll(); });
      expect((returned as { accepted: boolean }).accepted).toBe(true);
    });
  });

  // ---------------------------------------------------------------------------
  // acceptEssential
  // ---------------------------------------------------------------------------

  describe('acceptEssential', () => {
    it('sets canInteract to true', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.acceptEssential());
      expect(result.current.canInteract).toBe(true);
    });

    it('persists only essential=true, rest false', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.acceptEssential());
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
      expect(stored.essential).toBe(true);
      expect(stored.functional).toBe(false);
      expect(stored.analytics).toBe(false);
      expect(stored.marketing).toBe(false);
    });
  });

  // ---------------------------------------------------------------------------
  // savePreferences
  // ---------------------------------------------------------------------------

  describe('savePreferences', () => {
    it('saves custom preferences and sets accepted=true', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.savePreferences({ functional: true, analytics: false, marketing: true }));
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
      expect(stored.accepted).toBe(true);
      expect(stored.functional).toBe(true);
      expect(stored.analytics).toBe(false);
      expect(stored.marketing).toBe(true);
    });

    it('always sets essential=true regardless of input', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.savePreferences({ essential: false }));
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
      expect(stored.essential).toBe(true);
    });

    it('hides banner after saving', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.savePreferences({ functional: true }));
      expect(result.current.showBanner).toBe(false);
    });
  });

  // ---------------------------------------------------------------------------
  // openPreferences / closePreferences
  // ---------------------------------------------------------------------------

  describe('openPreferences / closePreferences', () => {
    it('openPreferences sets showPreferences=true', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.openPreferences());
      expect(result.current.showPreferences).toBe(true);
    });

    it('closePreferences sets showPreferences=false', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.openPreferences());
      act(() => result.current.closePreferences());
      expect(result.current.showPreferences).toBe(false);
    });
  });

  // ---------------------------------------------------------------------------
  // resetConsent
  // ---------------------------------------------------------------------------

  describe('resetConsent', () => {
    it('resets canInteract to false', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.acceptAll());
      act(() => result.current.resetConsent());
      expect(result.current.canInteract).toBe(false);
    });

    it('removes localStorage consent', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.acceptAll());
      act(() => result.current.resetConsent());
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it('shows banner again after reset when enabled', () => {
      const { result } = renderHook(() => useCookieConsent(gdprConfig()));
      act(() => result.current.acceptAll());
      act(() => result.current.resetConsent());
      expect(result.current.showBanner).toBe(true);
    });
  });
});
