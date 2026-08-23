import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useBreakpoint, resolveTheme } from '../src/index';

describe('useBreakpoint', () => {
  let innerWidthSpy: any;

  beforeEach(() => {
    // Mock window.innerWidth
    innerWidthSpy = vi.spyOn(window, 'innerWidth', 'get');
  });

  afterEach(() => {
    innerWidthSpy.mockRestore();
  });

  describe('breakpoint detection', () => {
    it('returns xs breakpoint at 320px width (mobile)', () => {
      innerWidthSpy.mockReturnValue(320);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('xs');
      expect(result.current.width).toBe(320);
    });

    it('returns sm breakpoint at 640px width', () => {
      innerWidthSpy.mockReturnValue(640);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('sm');
    });

    it('returns md breakpoint at 768px width (tablet)', () => {
      innerWidthSpy.mockReturnValue(768);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('md');
    });

    it('returns lg breakpoint at 1024px width (desktop)', () => {
      innerWidthSpy.mockReturnValue(1024);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('lg');
    });

    it('returns xl breakpoint at 1280px width', () => {
      innerWidthSpy.mockReturnValue(1280);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('xl');
    });

    it('returns 2xl breakpoint at 1536px width', () => {
      innerWidthSpy.mockReturnValue(1536);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('2xl');
    });
  });

  describe('boolean helpers', () => {
    it('returns correct isMobile flag at 320px', () => {
      innerWidthSpy.mockReturnValue(320);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.isMobile).toBe(true);
      expect(result.current.isTablet).toBe(false);
      expect(result.current.isDesktop).toBe(false);
      expect(result.current.isMobileOrTablet).toBe(true);
    });

    it('returns correct isTablet flag at 768px', () => {
      innerWidthSpy.mockReturnValue(768);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.isMobile).toBe(false);
      expect(result.current.isTablet).toBe(true);
      expect(result.current.isDesktop).toBe(false);
      expect(result.current.isMobileOrTablet).toBe(true);
    });

    it('returns correct isDesktop flag at 1024px', () => {
      innerWidthSpy.mockReturnValue(1024);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.isMobile).toBe(false);
      expect(result.current.isTablet).toBe(false);
      expect(result.current.isDesktop).toBe(true);
      expect(result.current.isMobileOrTablet).toBe(false);
    });
  });

  describe('hook stability', () => {
    it('provides stable hook return values across renders', () => {
      innerWidthSpy.mockReturnValue(1024);
      const { result, rerender } = renderHook(() => useBreakpoint());

      const firstResult = result.current;
      rerender();
      const secondResult = result.current;

      // Should maintain breakpoint classification across re-renders
      expect(secondResult.breakpoint).toBe(firstResult.breakpoint);
      expect(secondResult.isDesktop).toBe(firstResult.isDesktop);
    });

    it('initializes with correct breakpoint for given width', () => {
      // Test multiple width values to verify initialization
      const widthTests = [
        { width: 320, expected: 'xs' },
        { width: 768, expected: 'md' },
        { width: 1024, expected: 'lg' },
      ];

      widthTests.forEach(({ width, expected }) => {
        innerWidthSpy.mockReturnValue(width);
        const { result } = renderHook(() => useBreakpoint());
        expect(result.current.breakpoint).toBe(expected);
        expect(result.current.width).toBe(width);
      });
    });
  });

  describe('SSR safety', () => {
    it('provides width value at time of render', () => {
      // useBreakpoint uses window.innerWidth which is available in jsdom
      innerWidthSpy.mockReturnValue(1024);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.width).toBe(1024);
      expect(result.current.isDesktop).toBe(true);
    });

    it('handles all breakpoint boundaries correctly', () => {
      const tests = [
        { width: 0, expected: 'xs', isMobile: true },
        { width: 320, expected: 'xs', isMobile: true },
        { width: 640, expected: 'sm', isMobile: false },
        { width: 768, expected: 'md', isMobile: false },
        { width: 1024, expected: 'lg', isMobile: false },
        { width: 1280, expected: 'xl', isMobile: false },
        { width: 1536, expected: '2xl', isMobile: false },
      ];

      tests.forEach(({ width, expected, isMobile }) => {
        innerWidthSpy.mockReturnValue(width);
        const { result } = renderHook(() => useBreakpoint());
        expect(result.current.breakpoint).toBe(expected);
        expect(result.current.isMobile).toBe(isMobile);
      });
    });
  });

  describe('edge cases', () => {
    it('handles boundary widths correctly', () => {
      innerWidthSpy.mockReturnValue(639);
      const { result: result1 } = renderHook(() => useBreakpoint());
      expect(result1.current.breakpoint).toBe('xs');

      innerWidthSpy.mockReturnValue(640);
      const { result: result2 } = renderHook(() => useBreakpoint());
      expect(result2.current.breakpoint).toBe('sm');
    });

    it('handles very large widths', () => {
      innerWidthSpy.mockReturnValue(9999);
      const { result } = renderHook(() => useBreakpoint());

      expect(result.current.breakpoint).toBe('2xl');
      expect(result.current.isDesktop).toBe(true);
    });
  });
});

describe('resolveTheme', () => {
  const darkPreset = {
    bg: '#000',
    text: '#fff',
    primary: '#007bff',
  };

  const lightPreset = {
    bg: '#fff',
    text: '#000',
    primary: '#0056b3',
  };

  const presets = {
    dark: darkPreset,
    light: lightPreset,
  };

  it('returns dark theme by default', () => {
    const result = resolveTheme(presets);
    expect(result).toEqual(darkPreset);
  });

  it('returns dark theme when explicitly specified', () => {
    const result = resolveTheme(presets, 'dark');
    expect(result).toEqual(darkPreset);
  });

  it('returns light theme when specified', () => {
    const result = resolveTheme(presets, 'light');
    expect(result).toEqual(lightPreset);
  });

  it('merges overrides with dark theme', () => {
    const overrides = { primary: '#ffff00' };
    const result = resolveTheme(presets, 'dark', overrides);
    expect(result).toEqual({
      bg: '#000',
      text: '#fff',
      primary: '#ffff00',
    });
  });

  it('merges overrides with light theme', () => {
    const overrides = { bg: '#f5f5f5' };
    const result = resolveTheme(presets, 'light', overrides);
    expect(result).toEqual({
      bg: '#f5f5f5',
      text: '#000',
      primary: '#0056b3',
    });
  });

  it('merges multiple overrides', () => {
    const overrides = { bg: '#f0f0f0', text: '#333', primary: '#ff0000' };
    const result = resolveTheme(presets, 'dark', overrides);
    expect(result).toEqual({
      bg: '#f0f0f0',
      text: '#333',
      primary: '#ff0000',
    });
  });

  it('returns base theme when overrides is undefined', () => {
    const result = resolveTheme(presets, 'dark', undefined);
    expect(result).toEqual(darkPreset);
  });

  it('does not mutate the original preset', () => {
    const overrides = { primary: '#ffff00' };
    resolveTheme(presets, 'dark', overrides);
    expect(presets.dark.primary).toBe('#007bff');
  });

  it('works with generic types', () => {
    interface CustomColors {
      background: string;
      foreground: string;
      accent: string;
    }

    const customPresets: Record<'dark' | 'light', CustomColors> = {
      dark: { background: '#1a1a1a', foreground: '#fff', accent: '#00ff00' },
      light: { background: '#fff', foreground: '#000', accent: '#0000ff' },
    };

    const result = resolveTheme(customPresets, 'dark', { accent: '#ff00ff' });
    expect(result.accent).toBe('#ff00ff');
    expect(result.background).toBe('#1a1a1a');
  });
});
