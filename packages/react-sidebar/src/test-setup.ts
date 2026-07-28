import * as matchers from '@testing-library/jest-dom/matchers';
import { expect } from 'vitest';

// Register jest-dom matchers via vitest's own expect.extend rather than
// importing '@testing-library/jest-dom/vitest'. jest-dom 6.x's vitest entry
// patches chai in a way that breaks vitest 4's async `rejects.toThrow(string)`
// chain; expect.extend is framework-agnostic and leaves the chain intact.
expect.extend(matchers);
