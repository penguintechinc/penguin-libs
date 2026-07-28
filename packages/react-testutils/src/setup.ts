/**
 * Re-export @testing-library/jest-dom matchers for Vitest.
 *
 * Import this file in vitest `setupFiles` to extend `expect` with custom
 * DOM matchers like `toBeInTheDocument`, `toHaveValue`, etc.
 *
 * ```ts
 * // vitest.config.ts
 * export default defineConfig({
 *   test: { setupFiles: ['@penguintechinc/react-testutils/setup'] },
 * });
 * ```
 */
import * as matchers from '@testing-library/jest-dom/matchers';
import { expect } from 'vitest';

// Register jest-dom matchers through vitest's own expect.extend. jest-dom 6.x's
// '@testing-library/jest-dom/vitest' entry patches chai in a way that breaks
// vitest 4's async `rejects.toThrow(string)` chain; expect.extend is
// framework-agnostic and leaves that chain intact.
expect.extend(matchers);
