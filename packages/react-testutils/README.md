# @penguintechinc/react-testutils

Shared Vitest + React Testing Library utilities for PenguinTech React packages.

## Installation

```bash
npm install -D @penguintechinc/react-testutils
```

Required peer dependencies:
```bash
npm install -D vitest @testing-library/react @testing-library/jest-dom
```

## Setup

Add the setup file to your vitest config:

```ts
// vitest.config.ts
export default defineConfig({
  test: {
    setupFiles: ['@penguintechinc/react-testutils/setup'],
  },
});
```

## API

### Factories

```ts
import { makeObject, makeClaims, makeTokenSet, makeAuthContextValue } from '@penguintechinc/react-testutils';

const claims = makeClaims({ sub: 'my-user', roles: ['viewer'] });
const tokens = makeTokenSet({ access_token: 'custom-jwt' });
const ctx = makeAuthContextValue({ isAuthenticated: false, user: null });
```

### Context Wrappers

```tsx
import { createContextWrapper } from '@penguintechinc/react-testutils';
import { renderHook } from '@testing-library/react';
import { AuthContext } from '../components/AuthContext.js';

const wrapper = createContextWrapper(AuthContext, makeAuthContextValue());
const { result } = renderHook(() => useAuth(), { wrapper });
```

### Storage Mocks

```ts
import { mockSessionStorage } from '@penguintechinc/react-testutils';

let storageMock = mockSessionStorage();
afterEach(() => storageMock.restore());
```
