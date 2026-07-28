import 'dart:developer' as developer;

/// Normalized (lowercased, `_`-stripped) keys whose values should be
/// redacted in logs. Keys are normalized before matching so `refresh_token`,
/// `refreshToken`, and `REFRESHTOKEN` all match the same entry.
const _sensitiveFields = {
  'password',
  'token',
  'accesstoken',
  'refreshtoken',
  'idtoken',
  'jwt',
  'secret',
  'clientsecret',
  'apikey',
  'authorization',
  'captchatoken',
  'mfacode',
  'email',
  'creditcard',
  'cardnumber',
  'cvv',
  'ssn',
  'sessionid',
  'phone',
  'phonenumber',
  'pin',
  'otp',
};

/// Normalize a key for sensitive-field matching: lowercase, strip `_`.
String _normalizeKey(String key) => key.toLowerCase().replaceAll('_', '');

/// Log a message with sensitive fields redacted.
///
/// Scans [data] for keys matching [_sensitiveFields] (case/format
/// insensitive) and replaces their values with `[REDACTED]`, recursing into
/// nested [Map]s and [List]s so sensitive values aren't exposed inside
/// nested structures either. See [redactSensitiveData] for the redaction
/// logic itself, exposed separately for testing and for callers that want
/// to redact data without immediately logging it.
void sanitizedLog(
  String message, {
  Map<String, dynamic>? data,
  String name = 'flutter_libs',
}) {
  final sanitized = data != null ? redactSensitiveData(data) : null;
  final logMessage =
      sanitized != null ? '$message | data: $sanitized' : message;
  developer.log(logMessage, name: name);
}

/// Redact sensitive values from [data] — replaces the value of any key
/// matching [_sensitiveFields] (after lowercasing and stripping `_`) with
/// `[REDACTED]`, recursing into nested [Map]s and [List]s. Used internally
/// by [sanitizedLog]; exposed publicly so the redaction logic can be unit
/// tested and reused outside of logging.
Map<String, dynamic> redactSensitiveData(Map<String, dynamic> data) {
  return data.map((key, value) => MapEntry(key, _redactEntry(key, value)));
}

dynamic _redactEntry(String key, dynamic value) {
  if (_sensitiveFields.contains(_normalizeKey(key))) {
    return '[REDACTED]';
  }
  return _redactValue(value);
}

dynamic _redactValue(dynamic value) {
  if (value is Map) {
    // Explicit <String, dynamic> type args: `value`'s static type after the
    // `is Map` check is the raw `Map<dynamic, dynamic>`, so an untyped
    // `.map()` call here would silently produce a `Map<dynamic, dynamic>`
    // result — breaking callers that (reasonably) expect nested objects to
    // stay `Map<String, dynamic>` like the rest of a decoded JSON tree.
    return value.map<String, dynamic>(
      (key, val) => MapEntry(key.toString(), _redactEntry(key.toString(), val)),
    );
  }
  if (value is List) {
    return value.map(_redactValue).toList();
  }
  return value;
}
