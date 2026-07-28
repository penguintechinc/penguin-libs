/**
 * Ambient jest-dom matcher types for vitest 4.
 *
 * jest-dom 6.x ships `declare module 'vitest'`, but vitest 4 moved the assertion
 * interfaces into `@vitest/expect`, so that augmentation no longer reaches
 * `expect(...)`. Augmenting `@vitest/expect`'s purpose-built empty `Matchers`
 * interface is the supported hook — `Assertion<T>` extends it.
 *
 * Runtime registration of the matchers lives in src/test-setup.ts.
 */
import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers';

declare module '@vitest/expect' {
  // eslint-disable-next-line @typescript-eslint/no-empty-interface
  interface Matchers<T = any> extends TestingLibraryMatchers<any, T> {}
}

export {};
