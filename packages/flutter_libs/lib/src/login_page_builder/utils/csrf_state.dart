/// Compare a CSRF `state` (OAuth2/OIDC) or `RelayState` (SAML) value
/// returned by an identity provider callback against the value originally
/// generated for that request.
///
/// Callers MUST call this in their callback/redirect handler before
/// exchanging an authorization code or accepting a SAML response — skipping
/// this check reopens the CSRF hole these values exist to close. Returns
/// `false` (never throws) for a missing/null [returned] value.
///
/// Uses a constant-time comparison so callback handling doesn't leak the
/// expected value's length/prefix via response timing.
bool isValidCallbackState(String expected, String? returned) {
  if (returned == null) return false;
  if (expected.length != returned.length) return false;

  var result = 0;
  for (var i = 0; i < expected.length; i++) {
    result |= expected.codeUnitAt(i) ^ returned.codeUnitAt(i);
  }
  return result == 0;
}
