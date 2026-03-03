import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('FormValidators', () {
    group('validateRequired', () {
      test('returns error for null', () {
        expect(FormValidators.validateRequired(null), isNotNull);
      });
      test('returns error for empty string', () {
        expect(FormValidators.validateRequired(''), isNotNull);
      });
      test('returns null for valid value', () {
        expect(FormValidators.validateRequired('test'), isNull);
      });
    });

    group('validateEmail', () {
      test('accepts valid email', () {
        expect(FormValidators.validateEmail('user@example.com'), isNull);
      });
      test('rejects invalid email', () {
        expect(FormValidators.validateEmail('not-an-email'), isNotNull);
      });
      test('allows null (not required)', () {
        expect(FormValidators.validateEmail(null), isNull);
      });
    });

    group('validateUrl', () {
      test('accepts valid URL', () {
        expect(FormValidators.validateUrl('https://example.com'), isNull);
      });
      test('rejects invalid URL', () {
        expect(FormValidators.validateUrl('not a url'), isNotNull);
      });
    });

    group('validatePhone', () {
      test('accepts valid phone', () {
        expect(FormValidators.validatePhone('+1234567890'), isNull);
      });
      test('rejects invalid phone', () {
        expect(FormValidators.validatePhone('abc'), isNotNull);
      });
    });

    group('validateNumber', () {
      test('validates min', () {
        expect(FormValidators.validateNumber('3', min: 5), isNotNull);
        expect(FormValidators.validateNumber('5', min: 5), isNull);
        expect(FormValidators.validateNumber('10', min: 5), isNull);
      });
      test('validates max', () {
        expect(FormValidators.validateNumber('15', max: 10), isNotNull);
        expect(FormValidators.validateNumber('10', max: 10), isNull);
      });
    });

    group('validatePassword', () {
      test('rejects short password', () {
        expect(FormValidators.validatePassword('ab'), isNotNull);
      });
      test('accepts valid password', () {
        expect(FormValidators.validatePassword('password123'), isNull);
      });
    });

    group('buildValidator', () {
      test('builds composite required email validator', () {
        final v = FormValidators.buildValidator(
          type: 'email',
          required: true,
        );
        expect(v(null), isNotNull);
        expect(v(''), isNotNull);
        expect(v('bad'), isNotNull);
        expect(v('good@test.com'), isNull);
      });
    });
  });
}
