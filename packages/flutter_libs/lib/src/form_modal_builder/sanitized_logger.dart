import 'dart:developer' as developer;

/// Fields whose values should be redacted in logs.
const _sensitiveFields = {
  'password',
  'token',
  'refreshToken',
  'refresh_token',
  'secret',
  'apiKey',
  'api_key',
  'authorization',
  'captchaToken',
  'captcha_token',
  'mfaCode',
  'mfa_code',
  'email',
  'creditCard',
  'credit_card',
  'ssn',
};

/// Log a message with sensitive fields redacted.
///
/// Scans [data] for keys matching [_sensitiveFields] and replaces
/// their values with `[REDACTED]`.
void sanitizedLog(
  String message, {
  Map<String, dynamic>? data,
  String name = 'flutter_libs',
}) {
  final sanitized = data != null ? _redact(data) : null;
  final logMessage =
      sanitized != null ? '$message | data: $sanitized' : message;
  developer.log(logMessage, name: name);
}

Map<String, dynamic> _redact(Map<String, dynamic> data) {
  return data.map((key, value) {
    if (_sensitiveFields.contains(key.toLowerCase()) ||
        _sensitiveFields.contains(key)) {
      return MapEntry(key, '[REDACTED]');
    }
    if (value is Map<String, dynamic>) {
      return MapEntry(key, _redact(value));
    }
    return MapEntry(key, value);
  });
}
