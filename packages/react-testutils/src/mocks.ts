/**
 * Browser storage mocks for Vitest tests.
 */

/** Returned by {@link mockSessionStorage} and {@link mockLocalStorage}. */
export interface StorageMock {
  /** The underlying record that backs the mock. */
  store: Record<string, string>;
  /** Restore the original storage implementation on `globalThis`. */
  restore: () => void;
}

function createStorageMock(
  key: 'sessionStorage' | 'localStorage',
): StorageMock {
  const original = Object.getOwnPropertyDescriptor(globalThis, key);
  const store: Record<string, string> = {};

  Object.defineProperty(globalThis, key, {
    value: {
      getItem: (k: string): string | null => store[k] ?? null,
      setItem: (k: string, v: string): void => {
        store[k] = v;
      },
      removeItem: (k: string): void => {
        delete store[k];
      },
      clear: (): void => {
        for (const k of Object.keys(store)) {
          delete store[k];
        }
      },
      get length() {
        return Object.keys(store).length;
      },
      key: (index: number): string | null => Object.keys(store)[index] ?? null,
    } satisfies Storage,
    writable: true,
    configurable: true,
  });

  return {
    store,
    restore: () => {
      if (original) {
        Object.defineProperty(globalThis, key, original);
      }
    },
  };
}

/**
 * Replace `globalThis.sessionStorage` with a plain-object mock.
 *
 * Call `mock.restore()` in `afterEach` to reset the original implementation.
 *
 * @returns A {@link StorageMock} with `.store` (the backing record) and
 *   `.restore()` to undo the mock.
 *
 * @example
 * ```ts
 * let storageMock: StorageMock;
 * beforeEach(() => { storageMock = mockSessionStorage(); });
 * afterEach(() => storageMock.restore());
 * ```
 */
export function mockSessionStorage(): StorageMock {
  return createStorageMock('sessionStorage');
}

/**
 * Replace `globalThis.localStorage` with a plain-object mock.
 *
 * @returns A {@link StorageMock} with `.store` and `.restore()`.
 */
export function mockLocalStorage(): StorageMock {
  return createStorageMock('localStorage');
}
