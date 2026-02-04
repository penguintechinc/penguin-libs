import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import '../theme/elder_colors.dart';
import '../form_modal_builder/sanitized_logger.dart';
import 'login_types.dart';
import 'login_color_config.dart';
import 'state/captcha_state.dart';
import 'state/cookie_consent_state.dart';
import 'utils/oauth_utils.dart';
import 'utils/saml_utils.dart';
import 'widgets/mfa_modal.dart';
import 'widgets/captcha_widget.dart';
import 'widgets/social_login_buttons.dart';
import 'widgets/cookie_consent_banner.dart';
import 'widgets/login_footer.dart';

/// A full-featured login page with Elder dark theme.
///
/// Features:
/// - Email/password login with validation
/// - Remember Me checkbox
/// - Forgot Password / Sign Up links
/// - Social login (OAuth2, OIDC, SAML) via url_launcher
/// - CAPTCHA after N failed attempts
/// - MFA flow (shows MFA modal on mfa_required response)
/// - GDPR cookie consent gating
/// - Error display with transformable messages
/// - Full Elder theme via [LoginColorConfig]
class LoginPageBuilder extends StatefulWidget {
  const LoginPageBuilder({
    super.key,
    required this.apiConfig,
    required this.branding,
    this.socialProviders = const [],
    this.captchaConfig,
    this.mfaConfig,
    this.gdprConfig,
    this.colorConfig = LoginColorConfig.elder,
    this.onLoginSuccess,
    this.onLoginError,
    this.forgotPasswordUrl,
    this.forgotPasswordCallback,
    this.signUpUrl,
    this.signUpCallback,
    this.transformErrorMessage,
    this.onLinkTap,
    this.showRememberMe = true,
    this.footer,
  });

  final LoginApiConfig apiConfig;
  final BrandingConfig branding;
  final List<SocialProvider> socialProviders;
  final CaptchaConfig? captchaConfig;
  final MFAConfig? mfaConfig;
  final GDPRConfig? gdprConfig;
  final LoginColorConfig colorConfig;
  final void Function(LoginResponse response)? onLoginSuccess;
  final void Function(String error)? onLoginError;
  final String? forgotPasswordUrl;
  final VoidCallback? forgotPasswordCallback;
  final String? signUpUrl;
  final VoidCallback? signUpCallback;
  final String Function(String error)? transformErrorMessage;
  final void Function(String url)? onLinkTap;
  final bool showRememberMe;
  final Widget? footer;

  @override
  State<LoginPageBuilder> createState() => _LoginPageBuilderState();
}

class _LoginPageBuilderState extends State<LoginPageBuilder> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _rememberMe = false;
  bool _isSubmitting = false;
  String? _errorMessage;
  bool _showMfa = false;

  late final CaptchaNotifier _captchaNotifier;
  late final CookieConsentNotifier _cookieConsentNotifier;

  @override
  void initState() {
    super.initState();
    _captchaNotifier = CaptchaNotifier(
      threshold: widget.captchaConfig?.failedAttemptsThreshold ?? 3,
      resetTimeoutMs: widget.captchaConfig?.resetTimeoutMs ?? 900000,
    );
    _cookieConsentNotifier = CookieConsentNotifier(
      enabled: widget.gdprConfig?.enabled ?? false,
    );
    _cookieConsentNotifier.load();
    _cookieConsentNotifier.addListener(_onConsentChanged);
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _captchaNotifier.dispose();
    _cookieConsentNotifier.removeListener(_onConsentChanged);
    _cookieConsentNotifier.dispose();
    super.dispose();
  }

  void _onConsentChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _handleLogin({String? mfaCode}) async {
    if (!_formKey.currentState!.validate()) return;

    // Check CAPTCHA if required
    if (widget.captchaConfig?.enabled == true &&
        _captchaNotifier.showCaptcha &&
        !_captchaNotifier.isVerified) {
      setState(() {
        _errorMessage = 'Please complete the CAPTCHA verification';
      });
      return;
    }

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    try {
      final payload = LoginPayload(
        email: _emailController.text.trim(),
        password: _passwordController.text,
        rememberMe: _rememberMe,
        captchaToken: _captchaNotifier.captchaToken,
        mfaCode: mfaCode,
      );

      sanitizedLog('Login attempt', data: {
        'email': payload.email,
        'rememberMe': payload.rememberMe,
      });

      final uri = Uri.parse(widget.apiConfig.loginUrl);
      final response = widget.apiConfig.method == LoginMethod.put
          ? await http.put(
              uri,
              headers: {
                'Content-Type': 'application/json',
                ...widget.apiConfig.headers,
              },
              body: json.encode(payload.toJson()),
            )
          : await http.post(
              uri,
              headers: {
                'Content-Type': 'application/json',
                ...widget.apiConfig.headers,
              },
              body: json.encode(payload.toJson()),
            );

      final data = json.decode(response.body) as Map<String, dynamic>;
      final loginResponse = LoginResponse.fromJson(data);

      if (loginResponse.mfaRequired && widget.mfaConfig?.enabled == true) {
        setState(() {
          _isSubmitting = false;
          _showMfa = true;
        });
        return;
      }

      if (loginResponse.success) {
        _captchaNotifier.reset();
        sanitizedLog('Login successful');
        widget.onLoginSuccess?.call(loginResponse);
      } else {
        _captchaNotifier.recordFailure();
        final error = loginResponse.error ?? 'Login failed';
        final displayError = widget.transformErrorMessage != null
            ? widget.transformErrorMessage!(error)
            : error;
        setState(() => _errorMessage = displayError);
        widget.onLoginError?.call(error);
      }
    } catch (e) {
      _captchaNotifier.recordFailure();
      final error = 'Connection error. Please try again.';
      setState(() => _errorMessage = error);
      widget.onLoginError?.call(e.toString());
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  void _handleSocialLogin(SocialProvider provider) {
    String url;

    if (provider is BuiltInOAuth2Provider) {
      url = buildOAuth2Url(provider);
    } else if (provider is CustomOAuth2Provider) {
      url = buildCustomOAuth2Url(provider);
    } else if (provider is OIDCProvider) {
      url = buildOIDCUrl(provider);
    } else if (provider is SAMLProvider) {
      url = initiateSAMLLogin(provider);
    } else {
      return;
    }

    if (widget.onLinkTap != null) {
      widget.onLinkTap!(url);
    } else {
      launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
    }
  }

  void _handleMfaVerify(String code, bool rememberDevice) {
    setState(() => _showMfa = false);
    _handleLogin(mfaCode: code);
  }

  void _handleForgotPassword() {
    if (widget.forgotPasswordCallback != null) {
      widget.forgotPasswordCallback!();
    } else if (widget.forgotPasswordUrl != null) {
      if (widget.onLinkTap != null) {
        widget.onLinkTap!(widget.forgotPasswordUrl!);
      } else {
        launchUrl(Uri.parse(widget.forgotPasswordUrl!));
      }
    }
  }

  void _handleSignUp() {
    if (widget.signUpCallback != null) {
      widget.signUpCallback!();
    } else if (widget.signUpUrl != null) {
      if (widget.onLinkTap != null) {
        widget.onLinkTap!(widget.signUpUrl!);
      } else {
        launchUrl(Uri.parse(widget.signUpUrl!));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = widget.colorConfig;

    return Scaffold(
      backgroundColor: colors.pageBackground,
      body: Stack(
        children: [
          // Main content
          Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: _buildCard(colors),
              ),
            ),
          ),

          // MFA Modal
          if (_showMfa)
            MFAModal(
              onVerify: _handleMfaVerify,
              onCancel: () => setState(() => _showMfa = false),
              codeLength: widget.mfaConfig?.codeLength ?? 6,
              allowRememberDevice:
                  widget.mfaConfig?.allowRememberDevice ?? true,
            ),

          // Cookie consent banner
          if (widget.gdprConfig != null &&
              widget.gdprConfig!.enabled &&
              !_cookieConsentNotifier.canInteract)
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: CookieConsentBanner(
                onAcceptAll: _cookieConsentNotifier.acceptAll,
                onAcceptEssential:
                    _cookieConsentNotifier.acceptEssentialOnly,
                consentText: widget.gdprConfig!.consentText,
                privacyPolicyUrl: widget.gdprConfig!.privacyPolicyUrl,
                cookiePolicyUrl: widget.gdprConfig!.cookiePolicyUrl,
                showPreferences:
                    widget.gdprConfig!.showPreferences,
                onLinkTap: widget.onLinkTap,
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildCard(LoginColorConfig colors) {
    return Container(
      padding: const EdgeInsets.all(32),
      decoration: BoxDecoration(
        color: colors.cardBackground,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: colors.cardBorder),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Logo — 300px height on desktop, shrinks responsively on smaller screens
          if (widget.branding.logo != null)
            Center(
              child: ConstrainedBox(
                constraints: BoxConstraints(maxHeight: widget.branding.logoHeight),
                child: widget.branding.logo,
              ),
            ),

          // App name
          if (widget.branding.logo == null)
            Text(
              widget.branding.appName,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.titleText,
                fontSize: 28,
                fontWeight: FontWeight.bold,
              ),
            ),

          // Tagline
          if (widget.branding.tagline != null) ...[
            const SizedBox(height: 8),
            Text(
              widget.branding.tagline!,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.subtitleText,
                fontSize: 14,
              ),
            ),
          ],

          const SizedBox(height: 32),

          // Error message
          if (_errorMessage != null) ...[
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: colors.errorBackground,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(
                  color: colors.errorText.withAlpha(50),
                ),
              ),
              child: Text(
                _errorMessage!,
                style: TextStyle(
                  color: colors.errorText,
                  fontSize: 13,
                ),
              ),
            ),
            const SizedBox(height: 16),
          ],

          // Login form
          _buildForm(colors),

          // Social login buttons
          if (widget.socialProviders.isNotEmpty)
            SocialLoginButtons(
              providers: widget.socialProviders,
              onProviderTap: _handleSocialLogin,
              buttonBackground: colors.socialButtonBackground,
              buttonBorder: colors.socialButtonBorder,
              buttonText: colors.socialButtonText,
              dividerColor: colors.dividerColor,
              dividerTextColor: colors.subtitleText,
            ),

          // Footer
          if (widget.footer != null)
            widget.footer!
          else
            LoginFooter(
              githubRepo: widget.branding.githubRepo,
              privacyPolicyUrl: widget.gdprConfig?.privacyPolicyUrl,
              onLinkTap: widget.onLinkTap,
            ),
        ],
      ),
    );
  }

  Widget _buildForm(LoginColorConfig colors) {
    final canInteract = _cookieConsentNotifier.canInteract;

    return AbsorbPointer(
      absorbing: !canInteract,
      child: Opacity(
        opacity: canInteract ? 1.0 : 0.5,
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Email field
              Text(
                'Email',
                style: TextStyle(
                  color: colors.labelText,
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: 6),
              TextFormField(
                controller: _emailController,
                keyboardType: TextInputType.emailAddress,
                style: TextStyle(color: colors.inputText),
                decoration: _inputDecoration(
                  colors,
                  hintText: 'Enter your email',
                ),
                validator: (v) {
                  if (v == null || v.trim().isEmpty) {
                    return 'Email is required';
                  }
                  if (!RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
                      .hasMatch(v.trim())) {
                    return 'Please enter a valid email';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 16),

              // Password field
              Text(
                'Password',
                style: TextStyle(
                  color: colors.labelText,
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: 6),
              TextFormField(
                controller: _passwordController,
                obscureText: true,
                style: TextStyle(color: colors.inputText),
                decoration: _inputDecoration(
                  colors,
                  hintText: 'Enter your password',
                ),
                validator: (v) {
                  if (v == null || v.isEmpty) {
                    return 'Password is required';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 12),

              // Remember Me + Forgot Password row
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  if (widget.showRememberMe)
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        SizedBox(
                          width: 20,
                          height: 20,
                          child: Checkbox(
                            value: _rememberMe,
                            activeColor: colors.checkboxActive,
                            checkColor: colors.primaryButtonText,
                            onChanged: (v) =>
                                setState(() => _rememberMe = v ?? false),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          'Remember me',
                          style: TextStyle(
                            color: colors.subtitleText,
                            fontSize: 13,
                          ),
                        ),
                      ],
                    ),
                  if (widget.forgotPasswordUrl != null ||
                      widget.forgotPasswordCallback != null)
                    GestureDetector(
                      onTap: _handleForgotPassword,
                      child: Text(
                        'Forgot password?',
                        style: TextStyle(
                          color: colors.linkText,
                          fontSize: 13,
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 20),

              // CAPTCHA
              if (widget.captchaConfig?.enabled == true &&
                  _captchaNotifier.showCaptcha) ...[
                CaptchaWidget(
                  challengeUrl: widget.captchaConfig!.challengeUrl,
                  onVerified: _captchaNotifier.setCaptchaToken,
                  backgroundColor: colors.captchaBackground,
                  borderColor: colors.inputBorder,
                  textColor: colors.labelText,
                  accentColor: colors.primaryButton,
                ),
                const SizedBox(height: 16),
              ],

              // Submit button
              ElevatedButton(
                onPressed: _isSubmitting ? null : () => _handleLogin(),
                style: ElevatedButton.styleFrom(
                  backgroundColor: colors.primaryButton,
                  foregroundColor: colors.primaryButtonText,
                  disabledBackgroundColor: ElderColors.slate600,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(8),
                  ),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  minimumSize: const Size(double.infinity, 48),
                ),
                child: _isSubmitting
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: ElderColors.slate300,
                        ),
                      )
                    : const Text(
                        'Sign In',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
              ),

              // Sign up link
              if (widget.signUpUrl != null ||
                  widget.signUpCallback != null) ...[
                const SizedBox(height: 16),
                Center(
                  child: GestureDetector(
                    onTap: _handleSignUp,
                    child: RichText(
                      text: TextSpan(
                        text: "Don't have an account? ",
                        style: TextStyle(
                          color: colors.subtitleText,
                          fontSize: 13,
                        ),
                        children: [
                          TextSpan(
                            text: 'Sign up',
                            style: TextStyle(
                              color: colors.linkText,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  InputDecoration _inputDecoration(
    LoginColorConfig colors, {
    String? hintText,
  }) {
    return InputDecoration(
      hintText: hintText,
      hintStyle: TextStyle(color: colors.inputPlaceholder),
      filled: true,
      fillColor: colors.inputBackground,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: colors.inputBorder),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: colors.inputBorder),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(
          color: colors.inputFocusBorder,
          width: 2,
        ),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: colors.errorText),
      ),
      contentPadding: const EdgeInsets.symmetric(
        horizontal: 14,
        vertical: 14,
      ),
    );
  }
}
