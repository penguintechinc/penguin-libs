import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Secure, platform-backed storage for auth tokens — Keychain on
/// iOS/macOS, Keystore on Android, equivalent secure stores elsewhere.
///
/// Pass an instance to [LoginPageBuilder.tokenStorage] to have it persist
/// the access/refresh tokens automatically on a successful login. This
/// class only stores/reads/clears tokens; call [clear] yourself wherever
/// your app implements logout (this widget has no logout UI of its own).
class TokenStorage {
  TokenStorage({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  static const _accessTokenKey = 'flutter_libs.auth.access_token';
  static const _refreshTokenKey = 'flutter_libs.auth.refresh_token';

  /// Persist the access token and, if present, the refresh token.
  ///
  /// A `null` [refreshToken] actively deletes any previously stored refresh
  /// token rather than leaving it in place — a login response that omits
  /// `refreshToken` (e.g. an access-token-only refresh) must not leave a
  /// stale, possibly-revoked refresh token behind.
  Future<void> saveTokens({
    required String accessToken,
    String? refreshToken,
  }) async {
    await _storage.write(key: _accessTokenKey, value: accessToken);
    if (refreshToken != null) {
      await _storage.write(key: _refreshTokenKey, value: refreshToken);
    } else {
      await _storage.delete(key: _refreshTokenKey);
    }
  }

  /// Read the stored access token, or `null` if none is stored.
  Future<String?> readAccessToken() => _storage.read(key: _accessTokenKey);

  /// Read the stored refresh token, or `null` if none is stored.
  Future<String?> readRefreshToken() => _storage.read(key: _refreshTokenKey);

  /// Clear all stored tokens. Call this on logout.
  Future<void> clear() async {
    await _storage.delete(key: _accessTokenKey);
    await _storage.delete(key: _refreshTokenKey);
  }
}
