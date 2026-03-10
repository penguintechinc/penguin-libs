# go-common Changelog

## 0.1.0

- Initial release
- `logging.NewSanitizedLogger(service)` — zap logger with PII sanitization core
- `logging.SanitizeValue(key, value)` — sanitize individual string values
- `logging.SanitizeFields(fields)` — sanitize a slice of zap fields
- Sanitization rules: passwords, tokens, secrets, API keys, emails (domain-only), MFA codes, session IDs
