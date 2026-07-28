import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

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
      test('builds valid URL for built-in provider with PKCE and state', () {
        const provider = BuiltInOAuth2Provider(
          provider: BuiltInProviderType.google,
          clientId: 'test-client-id',
          redirectUri: 'https://example.com/callback',
        );
        final result = buildOAuth2Url(provider);
        expect(result.url, contains('accounts.google.com'));
        expect(result.url, contains('test-client-id'));
        expect(result.url, contains('callback'));
        expect(result.url, contains('code_challenge='));
        expect(result.url, contains('code_challenge_method=S256'));
        expect(result.url, contains('state=${result.state}'));
        expect(result.state, isNotEmpty);
        expect(result.codeVerifier, isNotEmpty);
      });

      test('code_challenge in the URL matches the returned codeVerifier', () {
        const provider = BuiltInOAuth2Provider(
          provider: BuiltInProviderType.github,
          clientId: 'client',
        );
        final result = buildOAuth2Url(provider);
        final expectedChallenge = generateCodeChallenge(result.codeVerifier);
        final uri = Uri.parse(result.url);
        expect(uri.queryParameters['code_challenge'], expectedChallenge);
      });

      test('honors an explicit state override', () {
        const provider = BuiltInOAuth2Provider(
          provider: BuiltInProviderType.google,
          clientId: 'client',
        );
        final result = buildOAuth2Url(provider, state: 'my-state');
        expect(result.state, 'my-state');
        expect(result.url, contains('state=my-state'));
      });
    });

    group('buildCustomOAuth2Url', () {
      test('wires PKCE and state into a custom provider URL', () {
        const provider = CustomOAuth2Provider(
          authUrl: 'https://auth.example.com/authorize',
          clientId: 'custom-client',
          label: 'Custom',
        );
        final result = buildCustomOAuth2Url(provider);
        expect(result.url, contains('auth.example.com'));
        expect(result.url, contains('code_challenge_method=S256'));
        expect(result.codeVerifier, isNotEmpty);
      });
    });

    group('buildOIDCUrl', () {
      test('uses authorization_endpoint from discovery document', () async {
        final client = MockClient((request) async {
          expect(
            request.url.toString(),
            'https://issuer.example.com/.well-known/openid-configuration',
          );
          return http.Response(
            json.encode({
              'authorization_endpoint':
                  'https://issuer.example.com/oidc/authorize',
            }),
            200,
          );
        });

        const provider = OIDCProvider(
          issuerUrl: 'https://issuer.example.com',
          clientId: 'oidc-client',
        );

        final result = await buildOIDCUrl(provider, client: client);
        expect(result.url,
            startsWith('https://issuer.example.com/oidc/authorize'));
        expect(result.url, contains('code_challenge_method=S256'));
        expect(result.state, isNotEmpty);
        expect(result.codeVerifier, isNotEmpty);
      });

      test('throws on a non-200 discovery response (fail closed)', () async {
        final client = MockClient((request) async {
          return http.Response('not found', 404);
        });

        const provider = OIDCProvider(
          issuerUrl: 'https://issuer.example.com',
          clientId: 'oidc-client',
        );

        expect(
          () => buildOIDCUrl(provider, client: client),
          throwsA(isA<http.ClientException>()),
        );
      });

      test('throws when authorization_endpoint is missing', () async {
        final client = MockClient((request) async {
          return http.Response(json.encode({'issuer': 'x'}), 200);
        });

        const provider = OIDCProvider(
          issuerUrl: 'https://issuer.example.com',
          clientId: 'oidc-client',
        );

        expect(
          () => buildOIDCUrl(provider, client: client),
          throwsA(isA<FormatException>()),
        );
      });
    });

    group('isValidCallbackState', () {
      test('accepts a matching state', () {
        expect(isValidCallbackState('abc123', 'abc123'), isTrue);
      });

      test('rejects a mismatched state', () {
        expect(isValidCallbackState('abc123', 'other'), isFalse);
      });

      test('rejects a null returned state', () {
        expect(isValidCallbackState('abc123', null), isFalse);
      });

      test('rejects a different-length state', () {
        expect(isValidCallbackState('abc123', 'abc1234'), isFalse);
      });
    });
  });
}
