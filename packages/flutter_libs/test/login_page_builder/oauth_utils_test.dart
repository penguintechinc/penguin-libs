import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('OAuth Utils', () {
    group('generateState', () {
      test('generates non-empty string', () {
        final state = generateState();
        expect(state, isNotEmpty);
      });

      test('generates unique values', () {
        final s1 = generateState();
        final s2 = generateState();
        expect(s1, isNot(equals(s2)));
      });
    });

    group('generateCodeVerifier', () {
      test('generates verifier of correct length', () {
        final v = generateCodeVerifier();
        expect(v.length, greaterThanOrEqualTo(43));
        expect(v.length, lessThanOrEqualTo(128));
      });
    });

    group('generateCodeChallenge', () {
      test('generates challenge from verifier', () {
        final verifier = generateCodeVerifier();
        final challenge = generateCodeChallenge(verifier);
        expect(challenge, isNotEmpty);
        expect(challenge, isNot(equals(verifier)));
      });
    });

    group('getProviderLabel', () {
      test('returns correct label for Google', () {
        expect(getProviderLabel(BuiltInProviderType.google), 'Google');
      });
      test('returns correct label for GitHub', () {
        expect(getProviderLabel(BuiltInProviderType.github), 'GitHub');
      });
    });

    group('getProviderColors', () {
      test('returns colors for Google', () {
        final colors = getProviderColors(BuiltInProviderType.google);
        expect(colors.background, isNonZero);
        expect(colors.text, isNonZero);
      });
    });

    group('buildOAuth2Url', () {
      test('builds valid URL for built-in provider', () {
        final provider = BuiltInOAuth2Provider(
          provider: BuiltInProviderType.google,
          clientId: 'test-client-id',
          redirectUri: 'https://example.com/callback',
        );
        final url = buildOAuth2Url(provider);
        expect(url, contains('accounts.google.com'));
        expect(url, contains('test-client-id'));
        expect(url, contains('callback'));
      });
    });
  });
}
