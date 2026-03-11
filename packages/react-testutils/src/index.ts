/**
 * @penguintechinc/react-testutils
 *
 * Shared Vitest + React Testing Library utilities for PenguinTech React packages.
 *
 * @example
 * ```ts
 * import { makeObject, makeClaims, createContextWrapper, mockSessionStorage } from '@penguintechinc/react-testutils';
 * ```
 */

export { makeObject, makeClaims, makeTokenSet, makeAuthContextValue } from './factories.js';
export type { ClaimsShape, TokenSetShape, AuthContextValueShape } from './factories.js';

export { createContextWrapper } from './wrappers.js';

export { mockSessionStorage, mockLocalStorage } from './mocks.js';
export type { StorageMock } from './mocks.js';
