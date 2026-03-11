/**
 * Generic factory utilities and pre-built factories for common test data.
 */

/** Shallow-merge *overrides* onto *defaults*, returning a new object. */
export function makeObject<T extends object>(defaults: T, overrides: Partial<T> = {}): T {
  return { ...defaults, ...overrides };
}

// ---------------------------------------------------------------------------
// react-aaa compatible shapes — defined inline so this package does not
// import from @penguintechinc/react-aaa at runtime.
// ---------------------------------------------------------------------------

/** Minimal shape matching `Claims` from `@penguintechinc/react-aaa`. */
export interface ClaimsShape {
  sub: string;
  iss: string;
  aud: string[];
  iat: Date;
  exp: Date;
  scope: string[];
  roles: string[];
  [key: string]: unknown;
}

/** Minimal shape matching `TokenSet` from `@penguintechinc/react-aaa`. */
export interface TokenSetShape {
  access_token: string;
  expires_in: number;
  token_type: string;
  refresh_token?: string;
  id_token?: string;
  [key: string]: unknown;
}

/** Minimal shape matching `AuthContextValue` from `@penguintechinc/react-aaa`. */
export interface AuthContextValueShape {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: ClaimsShape | null;
  accessToken: string | null;
  login: (...args: unknown[]) => unknown;
  logout: (...args: unknown[]) => unknown;
  emitter: unknown;
  [key: string]: unknown;
}

/**
 * Create a `Claims`-shaped object with sensible defaults.
 *
 * @param overrides - Partial overrides applied on top of the defaults.
 */
export function makeClaims(overrides: Partial<ClaimsShape> = {}): ClaimsShape {
  return makeObject<ClaimsShape>(
    {
      sub: 'user-123',
      iss: 'https://auth.example.com',
      aud: ['my-app'],
      iat: new Date(),
      exp: new Date(Date.now() + 3600 * 1000),
      scope: ['read', 'write'],
      roles: ['admin'],
    },
    overrides,
  );
}

/**
 * Create a `TokenSet`-shaped object with sensible defaults.
 *
 * @param overrides - Partial overrides applied on top of the defaults.
 */
export function makeTokenSet(overrides: Partial<TokenSetShape> = {}): TokenSetShape {
  return makeObject<TokenSetShape>(
    {
      access_token: 'test-access-token',
      expires_in: 3600,
      token_type: 'Bearer',
    },
    overrides,
  );
}

/**
 * Create an `AuthContextValue`-shaped object with sensible defaults.
 *
 * The `login` and `logout` fields default to plain `() => undefined` stubs.
 * Override them with `vi.fn()` when you need to assert on calls:
 *
 * ```ts
 * const ctx = makeAuthContextValue({ login: vi.fn(), logout: vi.fn() });
 * ```
 *
 * @param overrides - Partial overrides applied on top of the defaults.
 */
export function makeAuthContextValue(
  overrides: Partial<AuthContextValueShape> = {},
): AuthContextValueShape {
  return makeObject<AuthContextValueShape>(
    {
      isAuthenticated: true,
      isLoading: false,
      user: makeClaims(),
      accessToken: 'test-token',
      login: () => undefined,
      logout: () => undefined,
      emitter: null,
    },
    overrides,
  );
}
