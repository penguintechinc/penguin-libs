import { describe, it, expect } from 'vitest';
import { render, act } from '@testing-library/react';
import { useAuthContext, type AuthContextValue } from '../components/AuthContext.js';

describe('AuthContext default value', () => {
  it('reports unauthenticated state with no provider mounted', () => {
    const captured: { current: AuthContextValue | null } = { current: null };
    function Probe(): null {
      captured.current = useAuthContext();
      return null;
    }
    render(<Probe />);

    expect(captured.current?.isAuthenticated).toBe(false);
    expect(captured.current?.isLoading).toBe(false);
    expect(captured.current?.user).toBeNull();
    expect(captured.current?.accessToken).toBeNull();
    expect(captured.current?.emitter).toBeNull();
  });

  it('default login and logout are safe no-ops that resolve without throwing', async () => {
    const captured: { current: AuthContextValue | null } = { current: null };
    function Probe(): null {
      captured.current = useAuthContext();
      return null;
    }
    render(<Probe />);

    await expect(act(async () => captured.current?.login())).resolves.toBeUndefined();
    expect(() => captured.current?.logout()).not.toThrow();
  });
});
