import 'dart:convert';
import 'dart:io';

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
        expect(request, contains('https://idp.example.com/sso'));
      });

      test('XML-escapes special characters in provider fields', () {
        const config = SAMLProvider(
          idpSsoUrl: 'https://idp.example.com/sso?a=1&b=2',
          entityId: 'https://app.example.com/"><evil>',
          acsUrl: 'https://app.example.com/acs',
        );
        final request = buildSAMLRequest(config);
        expect(request, isNot(contains('&b=2"')));
        expect(request, contains('&amp;b=2'));
        expect(request, isNot(contains('<evil>')));
        expect(request, contains('&lt;evil&gt;'));
        expect(request, contains('&quot;'));
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

      test(
          'encodes SAMLRequest as raw-DEFLATE + base64 per the HTTP-Redirect binding',
          () {
        const config = SAMLProvider(
          idpSsoUrl: 'https://idp.example.com/sso',
          entityId: 'https://app.example.com',
          acsUrl: 'https://app.example.com/acs',
        );
        final url = buildSAMLRedirectUrl(config);
        final samlRequestParam = Uri.parse(url).queryParameters['SAMLRequest']!;

        final inflated =
            ZLibCodec(raw: true).decode(base64.decode(samlRequestParam));
        final xml = utf8.decode(inflated);
        expect(xml, contains('<samlp:AuthnRequest'));
        expect(xml, contains('https://idp.example.com/sso'));
      });
    });

    group('generateRelayState', () {
      test('generates non-empty relay state', () {
        final state = generateRelayState();
        expect(state, isNotEmpty);
      });
    });

    group('initiateSAMLLogin', () {
      test('builds complete SAML login URL with matching relayState', () {
        const provider = SAMLProvider(
          idpSsoUrl: 'https://idp.example.com/sso',
          entityId: 'https://app.example.com',
          acsUrl: 'https://app.example.com/acs',
        );
        final result = initiateSAMLLogin(provider);
        expect(result.url, contains('idp.example.com'));
        expect(result.url, contains('SAMLRequest'));
        expect(result.relayState, isNotEmpty);
        expect(
          Uri.parse(result.url).queryParameters['RelayState'],
          result.relayState,
        );
      });
    });

    group('isValidCallbackState (RelayState)', () {
      test('validates a returned RelayState against the original', () {
        const provider = SAMLProvider(
          idpSsoUrl: 'https://idp.example.com/sso',
          entityId: 'https://app.example.com',
          acsUrl: 'https://app.example.com/acs',
        );
        final result = initiateSAMLLogin(provider);
        expect(
            isValidCallbackState(result.relayState, result.relayState), isTrue);
        expect(isValidCallbackState(result.relayState, 'tampered'), isFalse);
      });
    });
  });
}
