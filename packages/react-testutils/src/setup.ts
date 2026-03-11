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
import '@testing-library/jest-dom/vitest';
