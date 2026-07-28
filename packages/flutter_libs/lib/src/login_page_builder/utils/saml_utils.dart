import 'dart:convert';
import 'dart:io';
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

/// Escape a string for safe interpolation into XML attribute/element
/// content (`&`, `<`, `>`, `"`, `'`).
String _xmlEscape(String value) {
  return value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&apos;');
}

/// Build a SAML AuthnRequest XML string.
///
/// All [config] fields are XML-escaped before interpolation to prevent
/// injection via a malicious/misconfigured `idpSsoUrl`, `acsUrl`, or
/// `entityId`.
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
  Destination="${_xmlEscape(config.idpSsoUrl)}"
  AssertionConsumerServiceURL="${_xmlEscape(config.acsUrl)}"
  ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">
  <saml:Issuer>${_xmlEscape(config.entityId)}</saml:Issuer>
  <samlp:NameIDPolicy
    Format="urn:oasis:names:tc:SAML:2.0:nameid-format:emailAddress"
    AllowCreate="true"/>
</samlp:AuthnRequest>''';
}

/// Build a SAML redirect URL with the encoded request.
///
/// Encodes the AuthnRequest per the SAML HTTP-Redirect binding
/// (SAML core §3.4.4): raw DEFLATE compression, then base64 — not just
/// base64 alone. Returns a URL pointing to the IdP SSO endpoint with the
/// `SAMLRequest` and `RelayState` query parameters.
String buildSAMLRedirectUrl(SAMLProvider config, {String? relayState}) {
  final samlRequest = buildSAMLRequest(config);
  final deflated = ZLibCodec(raw: true).encode(utf8.encode(samlRequest));
  final encoded = base64.encode(deflated);

  final params = <String, String>{
    'SAMLRequest': encoded,
  };

  if (relayState != null) {
    params['RelayState'] = relayState;
  }

  final uri = Uri.parse(config.idpSsoUrl).replace(queryParameters: params);
  return uri.toString();
}

/// Generate a relay state token for SAML CSRF protection.
String generateRelayState() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  return bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
}

/// Result of initiating a SAML login flow.
///
/// Carries the [url] to navigate the user to and the [relayState] CSRF
/// token — validate it against the IdP's returned `RelayState` via
/// [isValidCallbackState] (see `csrf_state.dart`) in the ACS callback
/// handler before accepting the SAML response.
class SAMLLoginRequest {
  const SAMLLoginRequest({
    required this.url,
    required this.relayState,
  });

  final String url;
  final String relayState;
}

/// Initiate a SAML login flow.
///
/// Returns the redirect URL to navigate to along with the generated
/// `RelayState`, which the caller must retain and validate on callback.
SAMLLoginRequest initiateSAMLLogin(SAMLProvider config) {
  final relayState = generateRelayState();
  final url = buildSAMLRedirectUrl(config, relayState: relayState);
  return SAMLLoginRequest(url: url, relayState: relayState);
}
