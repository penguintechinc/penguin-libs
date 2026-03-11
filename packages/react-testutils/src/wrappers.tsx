/**
 * Generic React context wrapper factory for use with `renderHook`.
 */
import { type ComponentType, type ReactNode } from 'react';
import type { Context } from 'react';

/**
 * Create a React component that wraps children in the given context *value*.
 *
 * Use the returned wrapper as the `wrapper` option of `renderHook`:
 *
 * ```tsx
 * import { renderHook } from '@testing-library/react';
 * import { createContextWrapper } from '@penguintechinc/react-testutils';
 * import { AuthContext } from '../components/AuthContext.js';
 *
 * const wrapper = createContextWrapper(AuthContext, makeAuthContextValue());
 * const { result } = renderHook(() => useAuth(), { wrapper });
 * ```
 *
 * @param Context - The React context object.
 * @param value - The context value to provide.
 * @returns A wrapper component that provides *value* via *Context*.
 */
export function createContextWrapper<T>(
  Context: Context<T>,
  value: T,
): ComponentType<{ children: ReactNode }> {
  function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return <Context.Provider value={value}>{children}</Context.Provider>;
  }
  Wrapper.displayName = `ContextWrapper(${Context.displayName ?? 'Unknown'})`;
  return Wrapper;
}
