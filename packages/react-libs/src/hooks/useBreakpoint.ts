import { useState, useEffect } from 'react';

export type Breakpoint = 'xs' | 'sm' | 'md' | 'lg' | 'xl' | '2xl';

export interface UseBreakpointReturn {
  breakpoint: Breakpoint;
  isMobile: boolean;
  isTablet: boolean;
  isDesktop: boolean;
  isMobileOrTablet: boolean;
  width: number;
}

const BREAKPOINTS: Record<Breakpoint, number> = {
  'xs': 0,
  'sm': 640,
  'md': 768,
  'lg': 1024,
  'xl': 1280,
  '2xl': 1536,
};

function getBreakpoint(width: number): Breakpoint {
  if (width >= BREAKPOINTS['2xl']) return '2xl';
  if (width >= BREAKPOINTS.xl) return 'xl';
  if (width >= BREAKPOINTS.lg) return 'lg';
  if (width >= BREAKPOINTS.md) return 'md';
  if (width >= BREAKPOINTS.sm) return 'sm';
  return 'xs';
}

/**
 * Hook that provides responsive breakpoint information matching Tailwind CSS defaults.
 * SSR-safe: defaults to desktop (1024px) on server, hydrates on mount.
 */
export function useBreakpoint(): UseBreakpointReturn {
  const [width, setWidth] = useState(() => {
    if (typeof window !== 'undefined') return window.innerWidth;
    return 1024; // SSR default: desktop
  });

  useEffect(() => {
    // Hydrate with actual width on mount
    setWidth(window.innerWidth);

    const queries: { mql: MediaQueryList; handler: () => void }[] = [];

    const update = () => setWidth(window.innerWidth);

    // Listen to each breakpoint boundary for precise change detection
    const breakpointValues = Object.values(BREAKPOINTS).filter((v) => v > 0);
    for (const bp of breakpointValues) {
      const mql = window.matchMedia(`(min-width: ${bp}px)`);
      const handler = () => update();
      mql.addEventListener('change', handler);
      queries.push({ mql, handler });
    }

    return () => {
      for (const { mql, handler } of queries) {
        mql.removeEventListener('change', handler);
      }
    };
  }, []);

  const breakpoint = getBreakpoint(width);

  return {
    breakpoint,
    isMobile: width < 640,
    isTablet: width >= 640 && width < 1024,
    isDesktop: width >= 1024,
    isMobileOrTablet: width < 1024,
    width,
  };
}
