/**
 * Matches control characters (U+0000-U+001F, U+007F), any whitespace, and backslash.
 * Browsers strip or normalise these, so "/\t/evil" can become "//evil" (F-01).
 */
// eslint-disable-next-line no-control-regex
const FORBIDDEN_CHARS = /[\u0000-\u001F\u007F\s\\]/;

/**
 * Checks that a string has the shape of a single-slash relative path.
 * Rejects forbidden characters and any value not starting with exactly one '/'.
 */
function hasSafePathShape(value: string): boolean {
  return value.startsWith('/') && !value.startsWith('//') && !FORBIDDEN_CHARS.test(value);
}

/**
 * Detects "." or ".." path segments (case-insensitive, incl. percent-encoded) in the path
 * portion of a value. URL resolution collapses them, which can yield "//host" pathnames.
 */
function hasDotSegment(value: string): boolean {
  const pathOnly = value.split(/[?#]/, 1)[0];
  return pathOnly.split('/').some((seg) => /^(?:\.|%2e){1,2}$/i.test(seg));
}

/**
 * Sanitizes redirect paths to prevent open redirect attacks (F-01).
 * Accepts only a single-slash relative path that resolves to the current origin; the
 * raw and percent-decoded forms must both pass, and any failure returns defaultPath.
 */
export function sanitizeRedirectPath(path: string, defaultPath: string = '/'): string {
  if (!path || typeof path !== 'string') {
    return defaultPath;
  }
  if (!hasSafePathShape(path)) {
    return defaultPath;
  }

  let decoded: string;
  try {
    decoded = decodeURIComponent(path);
  } catch {
    return defaultPath;
  }
  if (!hasSafePathShape(decoded)) {
    return defaultPath;
  }
  if (hasDotSegment(path) || hasDotSegment(decoded)) {
    return defaultPath;
  }

  if (typeof window === 'undefined' || !window.location) {
    return defaultPath;
  }
  const origin = window.location.origin;
  let resolved: URL;
  try {
    resolved = new URL(path, origin);
  } catch {
    return defaultPath;
  }
  if (resolved.origin !== origin) {
    return defaultPath;
  }

  if (resolved.pathname.startsWith('//') || resolved.pathname.startsWith('/\\')) {
    return defaultPath;
  }

  return resolved.pathname + resolved.search + resolved.hash;
}
