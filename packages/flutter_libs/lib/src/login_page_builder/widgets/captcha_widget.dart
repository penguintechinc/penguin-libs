import 'package:flutter/material.dart';
import '../../theme/elder_colors.dart';

/// ALTCHA CAPTCHA widget placeholder for Flutter.
///
/// In Flutter, the actual ALTCHA web widget cannot be used directly.
/// This provides a simple challenge-response UI as a fallback.
/// For web platforms, consider using HtmlElementView with the ALTCHA widget.
class CaptchaWidget extends StatefulWidget {
  const CaptchaWidget({
    super.key,
    required this.challengeUrl,
    required this.onVerified,
    this.onError,
    this.backgroundColor = ElderColors.slate900,
    this.borderColor = ElderColors.slate600,
    this.textColor = ElderColors.amber400,
    this.accentColor = ElderColors.amber500,
  });

  final String challengeUrl;
  final ValueChanged<String> onVerified;
  final ValueChanged<String>? onError;
  final Color backgroundColor;
  final Color borderColor;
  final Color textColor;
  final Color accentColor;

  @override
  State<CaptchaWidget> createState() => _CaptchaWidgetState();
}

class _CaptchaWidgetState extends State<CaptchaWidget> {
  bool _isVerifying = false;
  bool _isVerified = false;
  String? _error;

  Future<void> _handleVerify() async {
    setState(() {
      _isVerifying = true;
      _error = null;
    });

    try {
      // Simulate CAPTCHA verification
      // In production, this would call the challengeUrl and solve
      // the proof-of-work challenge
      await Future<void>.delayed(const Duration(seconds: 1));
      setState(() {
        _isVerified = true;
        _isVerifying = false;
      });
      widget.onVerified('captcha_verified_token');
    } catch (e) {
      setState(() {
        _error = 'Verification failed. Please try again.';
        _isVerifying = false;
      });
      widget.onError?.call(e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: widget.backgroundColor,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: widget.borderColor),
      ),
      child: Row(
        children: [
          // Checkbox / loading
          if (_isVerifying)
            const SizedBox(
              width: 24,
              height: 24,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: ElderColors.amber500,
              ),
            )
          else if (_isVerified)
            const Icon(
              Icons.check_circle,
              color: ElderColors.green500,
              size: 24,
            )
          else
            GestureDetector(
              onTap: _handleVerify,
              child: Container(
                width: 24,
                height: 24,
                decoration: BoxDecoration(
                  border: Border.all(color: widget.borderColor, width: 2),
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
            ),
          const SizedBox(width: 12),

          // Label
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _isVerified ? 'Verified' : 'I am human',
                  style: TextStyle(
                    color: widget.textColor,
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                  ),
                ),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(
                      _error!,
                      style: const TextStyle(
                        color: ElderColors.red400,
                        fontSize: 12,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
