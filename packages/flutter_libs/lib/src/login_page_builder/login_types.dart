import 'package:flutter/material.dart';

/// HTTP method for login API calls.
enum LoginMethod { post, put }

/// Configuration for the login API endpoint.
class LoginApiConfig {
  const LoginApiConfig({
    required this.loginUrl,
    this.method = LoginMethod.post,
    this.headers = const {},
  });

  final String loginUrl;
  final LoginMethod method;
  final Map<String, String> headers;
}

/// Payload sent to the login API.
class LoginPayload {
  const LoginPayload({
    required this.email,
    required this.password,
    this.rememberMe = false,
    this.captchaToken,
    this.mfaCode,
  });

  final String email;
  final String password;
  final bool rememberMe;
  final String? captchaToken;
  final String? mfaCode;

  Map<String, dynamic> toJson() => {
        'email': email,
        'password': password,
        if (rememberMe) 'rememberMe': true,
        if (captchaToken != null) 'captchaToken': captchaToken,
        if (mfaCode != null) 'mfaCode': mfaCode,
      };
}

/// User info returned from a successful login.
class LoginUser {
  const LoginUser({
    required this.id,
    required this.email,
    this.name,
    this.roles = const [],
  });

  final String id;
  final String email;
  final String? name;
  final List<String> roles;

  factory LoginUser.fromJson(Map<String, dynamic> json) => LoginUser(
        id: json['id'] as String,
        email: json['email'] as String,
        name: json['name'] as String?,
        roles: (json['roles'] as List<dynamic>?)
                ?.map((e) => e as String)
                .toList() ??
            const [],
      );
}

/// Response from the login API.
class LoginResponse {
  const LoginResponse({
    required this.success,
    this.user,
    this.token,
    this.refreshToken,
    this.mfaRequired = false,
    this.error,
    this.errorCode,
  });

  final bool success;
  final LoginUser? user;
  final String? token;
  final String? refreshToken;
  final bool mfaRequired;
  final String? error;
  final String? errorCode;

  factory LoginResponse.fromJson(Map<String, dynamic> json) => LoginResponse(
        success: json['success'] as bool,
        user: json['user'] != null
            ? LoginUser.fromJson(json['user'] as Map<String, dynamic>)
            : null,
        token: json['token'] as String?,
        refreshToken: json['refreshToken'] as String?,
        mfaRequired: json['mfaRequired'] as bool? ?? false,
        error: json['error'] as String?,
        errorCode: json['errorCode'] as String?,
      );
}

/// Branding configuration for the login page.
class BrandingConfig {
  const BrandingConfig({
    required this.appName,
    this.logo,
    this.logoWidth = 300,
    this.tagline,
    this.githubRepo,
  });

  final String appName;
  final Widget? logo;
  final double logoWidth;
  final String? tagline;
  final String? githubRepo;
}

/// CAPTCHA configuration.
class CaptchaConfig {
  const CaptchaConfig({
    required this.enabled,
    this.provider = CaptchaProvider.altcha,
    this.failedAttemptsThreshold = 3,
    required this.challengeUrl,
    this.resetTimeoutMs = 900000,
  });

  final bool enabled;
  final CaptchaProvider provider;
  final int failedAttemptsThreshold;
  final String challengeUrl;
  final int resetTimeoutMs;
}

/// Supported CAPTCHA providers.
enum CaptchaProvider { altcha }

/// MFA configuration.
class MFAConfig {
  const MFAConfig({
    required this.enabled,
    this.codeLength = 6,
    this.allowRememberDevice = true,
  });

  final bool enabled;
  final int codeLength;
  final bool allowRememberDevice;
}

/// GDPR/cookie consent configuration.
class GDPRConfig {
  const GDPRConfig({
    this.enabled = true,
    required this.privacyPolicyUrl,
    this.cookiePolicyUrl,
    this.consentText,
    this.showPreferences = true,
  });

  final bool enabled;
  final String privacyPolicyUrl;
  final String? cookiePolicyUrl;
  final String? consentText;
  final bool showPreferences;
}

// --- Social Login Provider Hierarchy ---

/// Base class for all social login providers.
sealed class SocialProvider {
  const SocialProvider();
}

/// Built-in OAuth2 provider (Google, GitHub, Microsoft, Apple, Twitch, Discord).
enum BuiltInProviderType {
  google,
  github,
  microsoft,
  apple,
  twitch,
  discord,
}

class BuiltInOAuth2Provider extends SocialProvider {
  const BuiltInOAuth2Provider({
    required this.provider,
    required this.clientId,
    this.redirectUri,
    this.scopes,
  });

  final BuiltInProviderType provider;
  final String clientId;
  final String? redirectUri;
  final List<String>? scopes;
}

/// Custom OAuth2 provider with explicit auth URL.
class CustomOAuth2Provider extends SocialProvider {
  const CustomOAuth2Provider({
    required this.authUrl,
    required this.clientId,
    required this.label,
    this.redirectUri,
    this.scopes,
    this.icon,
    this.buttonColor,
    this.textColor,
  });

  final String authUrl;
  final String clientId;
  final String label;
  final String? redirectUri;
  final List<String>? scopes;
  final Widget? icon;
  final Color? buttonColor;
  final Color? textColor;
}

/// OpenID Connect provider with auto-discovery.
class OIDCProvider extends SocialProvider {
  const OIDCProvider({
    required this.issuerUrl,
    required this.clientId,
    this.label,
    this.redirectUri,
    this.scopes,
    this.icon,
    this.buttonColor,
    this.textColor,
  });

  final String issuerUrl;
  final String clientId;
  final String? label;
  final String? redirectUri;
  final List<String>? scopes;
  final Widget? icon;
  final Color? buttonColor;
  final Color? textColor;
}

/// SAML provider.
class SAMLProvider extends SocialProvider {
  const SAMLProvider({
    required this.idpSsoUrl,
    required this.entityId,
    required this.acsUrl,
    this.certificate,
    this.label,
    this.icon,
    this.buttonColor,
    this.textColor,
  });

  final String idpSsoUrl;
  final String entityId;
  final String acsUrl;
  final String? certificate;
  final String? label;
  final Widget? icon;
  final Color? buttonColor;
  final Color? textColor;
}
