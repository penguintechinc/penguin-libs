import 'dart:convert';
import 'dart:math';
import 'package:crypto/crypto.dart';
import '../login_types.dart';

/// OAuth2 provider endpoint configurations.
const Map<BuiltInProviderType, _ProviderEndpoint> _providerEndpoints = {
  BuiltInProviderType.google: _ProviderEndpoint(
    authUrl: 'https://accounts.google.com/o/oauth2/v2/auth',
    defaultScopes: ['openid', 'email', 'profile'],
  ),
  BuiltInProviderType.github: _ProviderEndpoint(
    authUrl: 'https://github.com/login/oauth/authorize',
    defaultScopes: ['user:email'],
  ),
  BuiltInProviderType.microsoft: _ProviderEndpoint(
    authUrl:
        'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
    defaultScopes: ['openid', 'email', 'profile'],
  ),
  BuiltInProviderType.apple: _ProviderEndpoint(
    authUrl: 'https://appleid.apple.com/auth/authorize',
    defaultScopes: ['name', 'email'],
  ),
  BuiltInProviderType.twitch: _ProviderEndpoint(
    authUrl: 'https://id.twitch.tv/oauth2/authorize',
    defaultScopes: ['user:read:email'],
  ),
  BuiltInProviderType.discord: _ProviderEndpoint(
    authUrl: 'https://discord.com/api/oauth2/authorize',
    defaultScopes: ['identify', 'email'],
  ),
};

class _ProviderEndpoint {
  const _ProviderEndpoint({
    required this.authUrl,
    required this.defaultScopes,
  });

  final String authUrl;
  final List<String> defaultScopes;
}

/// Provider display colors for social login buttons.
class ProviderColors {
  const ProviderColors({
    required this.background,
    required this.text,
  });

  final int background; // ARGB hex
  final int text; // ARGB hex
}

/// Default button colors for built-in providers.
const Map<BuiltInProviderType, ProviderColors> providerColorMap = {
  BuiltInProviderType.google: ProviderColors(
    background: 0xFFFFFFFF,
    text: 0xFF374151,
  ),
  BuiltInProviderType.github: ProviderColors(
    background: 0xFF111827,
    text: 0xFFFFFFFF,
  ),
  BuiltInProviderType.microsoft: ProviderColors(
    background: 0xFF2F2F2F,
    text: 0xFFFFFFFF,
  ),
  BuiltInProviderType.apple: ProviderColors(
    background: 0xFF000000,
    text: 0xFFFFFFFF,
  ),
  BuiltInProviderType.twitch: ProviderColors(
    background: 0xFF9146FF,
    text: 0xFFFFFFFF,
  ),
  BuiltInProviderType.discord: ProviderColors(
    background: 0xFF5865F2,
    text: 0xFFFFFFFF,
  ),
};

/// Generate a cryptographically secure state parameter for CSRF protection.
///
/// Returns a 32-byte hex string.
String generateState() {
  final random = Random.secure();
  final bytes = List<int>.generate(32, (_) => random.nextInt(256));
  return bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
}

/// Generate a PKCE code verifier.
///
/// Returns a base64url-encoded 32-byte random string.
String generateCodeVerifier() {
  final random = Random.secure();
  final bytes = List<int>.generate(32, (_) => random.nextInt(256));
  return base64Url.encode(bytes).replaceAll('=', '');
}

/// Generate a PKCE code challenge from a [verifier].
///
/// Returns the SHA-256 hash of the verifier, base64url-encoded.
String generateCodeChallenge(String verifier) {
  final bytes = utf8.encode(verifier);
  final digest = sha256.convert(bytes);
  return base64Url.encode(digest.bytes).replaceAll('=', '');
}

/// Build an OAuth2 authorization URL for a built-in provider.
///
/// The [state] parameter is included for CSRF protection.
/// Stores state in the returned URL query parameters.
String buildOAuth2Url(BuiltInOAuth2Provider provider, {String? state}) {
  final endpoint = _providerEndpoints[provider.provider];
  if (endpoint == null) {
    throw ArgumentError('Unknown provider: ${provider.provider}');
  }

  final oauthState = state ?? generateState();
  final scopes = provider.scopes ?? endpoint.defaultScopes;

  final params = <String, String>{
    'client_id': provider.clientId,
    'response_type': 'code',
    'scope': scopes.join(' '),
    'state': oauthState,
  };

  if (provider.redirectUri != null) {
    params['redirect_uri'] = provider.redirectUri!;
  }

  final uri = Uri.parse(endpoint.authUrl).replace(queryParameters: params);
  return uri.toString();
}

/// Build an OAuth2 authorization URL for a custom provider.
String buildCustomOAuth2Url(CustomOAuth2Provider provider, {String? state}) {
  final oauthState = state ?? generateState();
  final scopes = provider.scopes ?? [];

  final params = <String, String>{
    'client_id': provider.clientId,
    'response_type': 'code',
    'state': oauthState,
  };

  if (scopes.isNotEmpty) {
    params['scope'] = scopes.join(' ');
  }

  if (provider.redirectUri != null) {
    params['redirect_uri'] = provider.redirectUri!;
  }

  final uri = Uri.parse(provider.authUrl).replace(queryParameters: params);
  return uri.toString();
}

/// Build an OIDC authorization URL using the issuer's discovery endpoint.
///
/// Note: In a real implementation, this would first fetch the
/// `.well-known/openid-configuration` to get the authorization endpoint.
/// For simplicity, this constructs the URL using `issuerUrl + /authorize`.
String buildOIDCUrl(OIDCProvider provider, {String? state}) {
  final oauthState = state ?? generateState();
  final scopes = provider.scopes ?? ['openid', 'email', 'profile'];

  final authEndpoint = provider.issuerUrl.endsWith('/')
      ? '${provider.issuerUrl}authorize'
      : '${provider.issuerUrl}/authorize';

  final params = <String, String>{
    'client_id': provider.clientId,
    'response_type': 'code',
    'scope': scopes.join(' '),
    'state': oauthState,
  };

  if (provider.redirectUri != null) {
    params['redirect_uri'] = provider.redirectUri!;
  }

  final uri = Uri.parse(authEndpoint).replace(queryParameters: params);
  return uri.toString();
}

/// Get the display label for a built-in provider.
String getProviderLabel(BuiltInProviderType provider) {
  switch (provider) {
    case BuiltInProviderType.google:
      return 'Google';
    case BuiltInProviderType.github:
      return 'GitHub';
    case BuiltInProviderType.microsoft:
      return 'Microsoft';
    case BuiltInProviderType.apple:
      return 'Apple';
    case BuiltInProviderType.twitch:
      return 'Twitch';
    case BuiltInProviderType.discord:
      return 'Discord';
  }
}

/// Get the button colors for a built-in provider.
ProviderColors getProviderColors(BuiltInProviderType provider) {
  return providerColorMap[provider] ??
      const ProviderColors(
        background: 0xFF334155,
        text: 0xFFFFFFFF,
      );
}
