import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('redactSensitiveData', () {
    test('redacts an exact-match sensitive key', () {
      final result = redactSensitiveData({'password': 'hunter2'});
      expect(result['password'], '[REDACTED]');
    });

    test('normalizes case before matching', () {
      final result = redactSensitiveData({'PASSWORD': 'hunter2'});
      expect(result['PASSWORD'], '[REDACTED]');
    });

    test('normalizes snake_case before matching', () {
      final result = redactSensitiveData({'refresh_token': 'rt-123'});
      expect(result['refresh_token'], '[REDACTED]');
    });

    test('normalizes camelCase before matching the same entry as snake_case',
        () {
      final result = redactSensitiveData({'refreshToken': 'rt-123'});
      expect(result['refreshToken'], '[REDACTED]');
    });

    for (final key in [
      'accessToken',
      'idToken',
      'jwt',
      'clientSecret',
      'apiKey',
      'sessionId',
      'phone',
      'mfaCode',
      'creditCard',
      'cvv',
    ]) {
      test('redacts extended denylist entry "$key"', () {
        final result = redactSensitiveData({key: 'secret-value'});
        expect(result[key], '[REDACTED]');
      });
    }

    test('does not redact a non-sensitive key', () {
      final result = redactSensitiveData({'username': 'not-sensitive'});
      expect(result['username'], 'not-sensitive');
    });

    test('recurses into nested maps', () {
      final result = redactSensitiveData({
        'user': {'email': 'user@example.com', 'name': 'ok'},
      });
      final user = result['user'] as Map<String, dynamic>;
      expect(user['email'], '[REDACTED]');
      expect(user['name'], 'ok');
    });

    test('recurses into lists of maps', () {
      final result = redactSensitiveData({
        'sessions': [
          {'sessionId': 'abc', 'device': 'phone-model'},
          {'sessionId': 'def', 'device': 'laptop-model'},
        ],
      });
      final sessions = result['sessions'] as List<dynamic>;
      expect((sessions[0] as Map)['sessionId'], '[REDACTED]');
      expect((sessions[0] as Map)['device'], 'phone-model');
      expect((sessions[1] as Map)['sessionId'], '[REDACTED]');
    });

    test('leaves non-map/list values untouched', () {
      final result = redactSensitiveData({'count': 42, 'active': true});
      expect(result['count'], 42);
      expect(result['active'], true);
    });
  });

  group('sanitizedLog', () {
    test('does not throw with or without data', () {
      expect(() => sanitizedLog('event'), returnsNormally);
      expect(
        () => sanitizedLog('event', data: {'password': 'secret'}),
        returnsNormally,
      );
    });
  });
}
