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
        const config = SAMLProvider(
          idpSsoUrl: 'https://idp.example.com/sso',
          entityId: 'https://app.example.com',
          acsUrl: 'https://app.example.com/acs',
        );
        final request = buildSAMLRequest(config);
        expect(request, isNotEmpty);
      });
    });

    group('buildSAMLRedirectUrl', () {
      test('builds redirect URL with SAML request', () {
        const config = SAMLProvider(
          idpSsoUrl: 'https://idp.example.com/sso',
          entityId: 'https://app.example.com',
          acsUrl: 'https://app.example.com/acs',
        );
        final url = buildSAMLRedirectUrl(config, relayState: 'state123');
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
        const provider = SAMLProvider(
          idpSsoUrl: 'https://idp.example.com/sso',
          entityId: 'https://app.example.com',
          acsUrl: 'https://app.example.com/acs',
        );
        final url = initiateSAMLLogin(provider);
        expect(url, contains('idp.example.com'));
        expect(url, contains('SAMLRequest'));
      });
    });
  });
}
