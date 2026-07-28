import * as matchers from '@testing-library/jest-dom/matchers';
import { expect } from 'vitest';

// Register jest-dom matchers through vitest's own expect.extend. jest-dom 6.x's
// '@testing-library/jest-dom/vitest' entry patches chai in a way that breaks
// vitest 4's async `rejects.toThrow(string)` chain; expect.extend is
// framework-agnostic and leaves that chain intact.
expect.extend(matchers);

// Mock matchMedia for useBreakpoint hook tests
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {}, // deprecated
    removeListener: () => {}, // deprecated
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => {},
  }),
});
