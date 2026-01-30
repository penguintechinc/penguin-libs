import 'package:flutter/material.dart';
import '../../theme/elder_colors.dart';

/// Footer section for the login page with optional links.
class LoginFooter extends StatelessWidget {
  const LoginFooter({
    super.key,
    this.githubRepo,
    this.privacyPolicyUrl,
    this.termsUrl,
    this.copyrightText,
    this.onLinkTap,
    this.textColor = ElderColors.slate500,
    this.linkColor = ElderColors.amber400,
  });

  final String? githubRepo;
  final String? privacyPolicyUrl;
  final String? termsUrl;
  final String? copyrightText;
  final void Function(String url)? onLinkTap;
  final Color textColor;
  final Color linkColor;

  @override
  Widget build(BuildContext context) {
    final links = <Widget>[];

    if (githubRepo != null) {
      links.add(_buildLink('GitHub', githubRepo!));
    }
    if (privacyPolicyUrl != null) {
      links.add(_buildLink('Privacy Policy', privacyPolicyUrl!));
    }
    if (termsUrl != null) {
      links.add(_buildLink('Terms of Service', termsUrl!));
    }

    return Padding(
      padding: const EdgeInsets.only(top: 24),
      child: Column(
        children: [
          if (links.isNotEmpty)
            Wrap(
              spacing: 16,
              runSpacing: 8,
              alignment: WrapAlignment.center,
              children: links,
            ),
          if (copyrightText != null) ...[
            const SizedBox(height: 8),
            Text(
              copyrightText!,
              style: TextStyle(color: textColor, fontSize: 12),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildLink(String label, String url) {
    return GestureDetector(
      onTap: () => onLinkTap?.call(url),
      child: Text(
        label,
        style: TextStyle(
          color: linkColor,
          fontSize: 13,
          decoration: TextDecoration.underline,
          decorationColor: linkColor,
        ),
      ),
    );
  }
}
