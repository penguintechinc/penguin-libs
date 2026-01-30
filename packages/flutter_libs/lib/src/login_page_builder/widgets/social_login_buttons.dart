import 'package:flutter/material.dart';
import '../../theme/elder_colors.dart';
import '../login_types.dart';
import '../utils/oauth_utils.dart';
import 'social_icons.dart';

/// A grid of social login provider buttons with icons and labels.
class SocialLoginButtons extends StatelessWidget {
  const SocialLoginButtons({
    super.key,
    required this.providers,
    required this.onProviderTap,
    this.buttonBackground = ElderColors.slate700,
    this.buttonBorder = ElderColors.slate600,
    this.buttonText = ElderColors.white,
    this.dividerColor = ElderColors.slate700,
    this.dividerTextColor = ElderColors.slate400,
  });

  final List<SocialProvider> providers;
  final ValueChanged<SocialProvider> onProviderTap;
  final Color buttonBackground;
  final Color buttonBorder;
  final Color buttonText;
  final Color dividerColor;
  final Color dividerTextColor;

  @override
  Widget build(BuildContext context) {
    if (providers.isEmpty) return const SizedBox.shrink();

    return Column(
      children: [
        // Divider
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 20),
          child: Row(
            children: [
              Expanded(child: Divider(color: dividerColor)),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Text(
                  'Or continue with',
                  style: TextStyle(
                    color: dividerTextColor,
                    fontSize: 13,
                  ),
                ),
              ),
              Expanded(child: Divider(color: dividerColor)),
            ],
          ),
        ),

        // Button grid
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: providers.map((provider) {
            return _buildButton(provider);
          }).toList(),
        ),
      ],
    );
  }

  Widget _buildButton(SocialProvider provider) {
    String label;
    Widget icon;
    Color bgColor = buttonBackground;
    Color txtColor = buttonText;

    if (provider is BuiltInOAuth2Provider) {
      label = getProviderLabel(provider.provider);
      icon = getProviderIcon(provider.provider.name);
      final colors = getProviderColors(provider.provider);
      bgColor = Color(colors.background);
      txtColor = Color(colors.text);
    } else if (provider is CustomOAuth2Provider) {
      label = provider.label;
      icon = provider.icon ?? const Icon(Icons.login, size: 20);
      if (provider.buttonColor != null) bgColor = provider.buttonColor!;
      if (provider.textColor != null) txtColor = provider.textColor!;
    } else if (provider is OIDCProvider) {
      label = provider.label ?? 'SSO';
      icon = provider.icon ??
          getProviderIcon('sso');
      if (provider.buttonColor != null) bgColor = provider.buttonColor!;
      if (provider.textColor != null) txtColor = provider.textColor!;
    } else if (provider is SAMLProvider) {
      label = provider.label ?? 'Enterprise SSO';
      icon = provider.icon ??
          getProviderIcon('enterprise');
      if (provider.buttonColor != null) bgColor = provider.buttonColor!;
      if (provider.textColor != null) txtColor = provider.textColor!;
    } else {
      label = 'Login';
      icon = const Icon(Icons.login, size: 20);
    }

    return SizedBox(
      width: 160,
      child: OutlinedButton(
        onPressed: () => onProviderTap(provider),
        style: OutlinedButton.styleFrom(
          backgroundColor: bgColor,
          foregroundColor: txtColor,
          side: BorderSide(color: buttonBorder),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: 16,
            vertical: 12,
          ),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            icon,
            const SizedBox(width: 8),
            Flexible(
              child: Text(
                label,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: txtColor,
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
