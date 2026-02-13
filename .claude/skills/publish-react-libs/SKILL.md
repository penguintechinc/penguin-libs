---
name: publish-react-libs
description: Use when react-libs code changes need to be published to GitHub Packages npm registry for consumers like Elder
---

# Publish react-libs to GitHub Packages

## Overview

Publish `@penguintechinc/react-libs` to GitHub Packages npm registry after making changes. Authentication uses a token at the workspace root `.npmrc`.

## When to Use

- After modifying react-libs source code and bumping version
- When a consumer (Elder, etc.) needs the latest react-libs

## Workflow

### 1. Bump version

```bash
cd packages/react-libs
npm version patch   # or minor/major
```

### 2. Build

```bash
npm run build
```

Verify: `dist/` contains updated `.js` and `.d.ts` files.

### 3. Publish

```bash
npm publish
```

This uses the workspace root `.npmrc` for auth (`//npm.pkg.github.com/:_authToken=...`).

**Known issue:** Package-level `.npmrc` is IGNORED in npm workspaces. Auth must be at workspace root (`/home/penguin/code/penguin-libs/.npmrc`).

### 4. Verify

```bash
npm view @penguintechinc/react-libs version
```

Should show the new version.

### 5. Commit and push

```bash
git add packages/react-libs/package.json packages/react-libs/dist/
git commit -m "chore(react-libs): bump to vX.X.X"
git push origin main
```

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `npm ERR! 401 Unauthorized` | Check workspace root `.npmrc` has valid token |
| Publishing from wrong directory | Must be in `packages/react-libs/` |
| Forgot to build before publish | `dist/` will contain stale code |
| Bumped all packages | Only bump packages with actual changes |
