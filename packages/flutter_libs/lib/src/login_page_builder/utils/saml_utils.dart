import 'dart:convert';
import 'dart:math';
import '../login_types.dart';

/// Generate a SAML request ID.
///
/// Format: "_" + 16-byte hex string.
String generateRequestId() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
  return '_$hex';
}

/// Build a SAML AuthnRequest XML string.
String buildSAMLRequest(SAMLProvider config) {
  final id = generateRequestId();
  final issueInstant = DateTime.now().toUtc().toIso8601String();

  return '''<?xml version="1.0" encoding="UTF-8"?>
<samlp:AuthnRequest
  xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
  xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
  ID="$id"
  Version="2.0"
  IssueInstant="$issueInstant"
  Destination="${config.idpSsoUrl}"
  AssertionConsumerServiceURL="${config.acsUrl}"
  ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">
  <saml:Issuer>${config.entityId}</saml:Issuer>
  <samlp:NameIDPolicy
    Format="urn:oasis:names:tc:SAML:2.0:nameid-format:emailAddress"
    AllowCreate="true"/>
</samlp:AuthnRequest>''';
}

/// Build a SAML redirect URL with the encoded request.
///
/// Returns a URL pointing to the IdP SSO endpoint with the SAMLRequest
/// and RelayState as query parameters.
String buildSAMLRedirectUrl(SAMLProvider config, {String? relayState}) {
  final samlRequest = buildSAMLRequest(config);
  final encoded = base64.encode(utf8.encode(samlRequest));

  final params = <String, String>{
    'SAMLRequest': encoded,
  };

  if (relayState != null) {
    params['RelayState'] = relayState;
  }

  final uri =
      Uri.parse(config.idpSsoUrl).replace(queryParameters: params);
  return uri.toString();
}

/// Generate a relay state token for SAML CSRF protection.
String generateRelayState() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  return bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
}

/// Initiate a SAML login flow.
///
/// Returns the redirect URL to navigate to.
String initiateSAMLLogin(SAMLProvider config) {
  final relayState = generateRelayState();
  return buildSAMLRedirectUrl(config, relayState: relayState);
}
