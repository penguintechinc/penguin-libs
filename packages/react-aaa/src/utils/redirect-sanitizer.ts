/**
 * Sanitizes redirect paths to prevent open redirect attacks.
 * Accepts only same-origin relative paths starting with '/', rejects protocol-relative
 * paths ('//'), backslash tricks ('\\' or '/%5C'), and other attack vectors.
 */
export function sanitizeRedirectPath(path: string, defaultPath: string = '/'): string {
  // Null/undefined → default
  if (!path || typeof path !== 'string') {
    return defaultPath;
  }

  // Trim whitespace
  const trimmed = path.trim();

  // Reject if empty after trim
  if (trimmed.length === 0) {
    return defaultPath;
  }

  // Reject protocol-relative URLs (//) — open redirect vector
  if (trimmed.startsWith('//')) {
    return defaultPath;
  }

  // Reject backslash tricks (\\) — some browsers treat \\ as //
  if (trimmed.startsWith('\\')) {
    return defaultPath;
  }

  // Reject absolute URLs with protocol (http://, https://, etc.) — open redirect
  if (/^[a-z][a-z0-9+\-.]*:/i.test(trimmed)) {
    return defaultPath;
  }

  // Reject data: and javascript: URLs
  if (/^(data|javascript):/i.test(trimmed)) {
    return defaultPath;
  }

  // Only accept paths starting with / (relative, same-origin)
  if (!trimmed.startsWith('/')) {
    return defaultPath;
  }

  // Reject /\ attack vector (slash followed by backslash)
  // This can be interpreted as // in some browser contexts
  if (trimmed.length > 1 && trimmed[1] === '\\') {
    return defaultPath;
  }

  // Reject encoded variants of attack patterns
  try {
    const decoded = decodeURIComponent(trimmed);

    // After decoding, check for // or \ at start
    if (decoded.startsWith('//') || decoded.startsWith('\\')) {
      return defaultPath;
    }

    // Check for /\ pattern after decoding (e.g., /%5C decodes to /\)
    if (decoded.length > 1 && decoded[1] === '\\') {
      return defaultPath;
    }
  } catch {
    // Invalid encoding → reject as potential attack
    return defaultPath;
  }

  return trimmed;
}
