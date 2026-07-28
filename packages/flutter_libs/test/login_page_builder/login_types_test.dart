import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('isSecureLoginUrl', () {
    test('allows any scheme outside of release builds', () {
      expect(isSecureLoginUrl('http://insecure.example.com', isRelease: false),
          isTrue);
    });

    test('allows https in release builds', () {
      expect(isSecureLoginUrl('https://api.example.com/login', isRelease: true),
          isTrue);
    });

    test('rejects plain http in release builds', () {
      expect(isSecureLoginUrl('http://api.example.com/login', isRelease: true),
          isFalse);
    });

    test('allows http://localhost in release builds', () {
      expect(isSecureLoginUrl('http://localhost:8080/login', isRelease: true),
          isTrue);
    });

    test('allows http://127.0.0.1 in release builds', () {
      expect(isSecureLoginUrl('http://127.0.0.1:8080/login', isRelease: true),
          isTrue);
    });

    test('rejects an unparsable URL in release builds', () {
      expect(isSecureLoginUrl('::not a url::', isRelease: true), isFalse);
    });

    test('rejects a non-http(s) scheme in release builds', () {
      expect(isSecureLoginUrl('ftp://api.example.com/login', isRelease: true),
          isFalse);
    });
  });

  group('LoginApiConfig', () {
    test('accepts an https loginUrl', () {
      expect(
        () => LoginApiConfig(loginUrl: 'https://api.example.com/login'),
        returnsNormally,
      );
    });

    // Note: LoginApiConfig's constructor gates on the real `kReleaseMode`,
    // which is always false under `flutter test` — so its release-mode
    // rejection path can't be exercised end-to-end here. The gating logic
    // itself is fully covered above via isSecureLoginUrl's `isRelease`
    // parameter, which LoginApiConfig delegates to.
  });

  group('LoginPayload.toJson', () {
    test('omits rememberDevice when there is no mfaCode', () {
      const payload = LoginPayload(
        email: 'user@example.com',
        password: 'secret',
        rememberDevice: true,
      );
      expect(payload.toJson().containsKey('rememberDevice'), isFalse);
    });

    test('includes rememberDevice alongside a mfaCode', () {
      const payload = LoginPayload(
        email: 'user@example.com',
        password: 'secret',
        mfaCode: '123456',
        rememberDevice: true,
      );
      final json = payload.toJson();
      expect(json['mfaCode'], '123456');
      expect(json['rememberDevice'], true);
    });

    test('omits rememberDevice when false even with a mfaCode', () {
      const payload = LoginPayload(
        email: 'user@example.com',
        password: 'secret',
        mfaCode: '123456',
      );
      expect(payload.toJson().containsKey('rememberDevice'), isFalse);
    });
  });
}
