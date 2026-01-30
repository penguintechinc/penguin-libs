import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('SAML Utils', () {
    group('generateRequestId', () {
      test('generates unique IDs', () {
        final id1 = generateRequestId();
        final id2 = generateRequestId();
        expect(id1, isNot(equals(id2)));
      });

      test('starts with underscore', () {
        final id = generateRequestId();
        expect(id.startsWith('_'), isTrue);
      });
    });

    group('buildSAMLRequest', () {
      test('builds valid SAML request', () {
        final request = buildSAMLRequest(
          issuer: 'https://app.example.com',
          acsUrl: 'https://app.example.com/acs',
        );
        expect(request, isNotEmpty);
      });
    });

    group('buildSAMLRedirectUrl', () {
      test('builds redirect URL with SAML request', () {
        final url = buildSAMLRedirectUrl(
          ssoUrl: 'https://idp.example.com/sso',
          samlRequest: 'base64encodedrequest',
          relayState: 'state123',
        );
        expect(url, contains('idp.example.com'));
        expect(url, contains('SAMLRequest'));
        expect(url, contains('RelayState'));
      });
    });

    group('generateRelayState', () {
      test('generates non-empty relay state', () {
        final state = generateRelayState();
        expect(state, isNotEmpty);
      });
    });

    group('initiateSAMLLogin', () {
      test('builds complete SAML login URL', () {
        final provider = SAMLProvider(
          ssoUrl: 'https://idp.example.com/sso',
          issuer: 'https://app.example.com',
          callbackUrl: 'https://app.example.com/acs',
        );
        final url = initiateSAMLLogin(provider);
        expect(url, contains('idp.example.com'));
        expect(url, contains('SAMLRequest'));
      });
    });
  });
}
