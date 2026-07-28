import 'package:flutter/material.dart';
import '../../theme/elder_colors.dart';
import '../utils/altcha_solver.dart';

/// ALTCHA (https://altcha.org) proof-of-work CAPTCHA widget.
///
/// Fetches a challenge from [challengeUrl], solves the proof-of-work on a
/// background isolate, and reports the resulting verification token via
/// [onVerified]. Any failure — network error, malformed response,
/// unsupported algorithm, or an unsolved challenge — fails closed: no token
/// is ever produced and [onError] is invoked instead.
class CaptchaWidget extends StatefulWidget {
  const CaptchaWidget({
    super.key,
    required this.challengeUrl,
    required this.onVerified,
    this.onError,
    this.fetchChallenge = fetchAltchaChallenge,
    this.solveChallenge = solveAltchaChallenge,
    this.backgroundColor = ElderColors.slate900,
    this.borderColor = ElderColors.slate600,
    this.textColor = ElderColors.amber400,
    this.accentColor = ElderColors.amber500,
  });

  final String challengeUrl;
  final ValueChanged<String> onVerified;
  final ValueChanged<String>? onError;

  /// Fetches the ALTCHA challenge for [challengeUrl]. Overridable for
  /// testing; defaults to the real network implementation.
  final Future<AltchaChallenge> Function(String challengeUrl) fetchChallenge;

  /// Solves an [AltchaChallenge]. Defaults to [solveAltchaChallenge], which
  /// runs on a background isolate via `compute()`. Overridable for testing
  /// — `flutter_test`'s fake-clock pump loop doesn't reliably wait on a real
  /// isolate, so widget tests that need a solved/unsolved result should
  /// inject a synchronous wrapper around `solveAltchaSync` instead.
  final Future<int> Function(AltchaChallenge challenge) solveChallenge;
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
      final challenge = await widget.fetchChallenge(widget.challengeUrl);
      final number = await widget.solveChallenge(challenge);
      final payload = buildAltchaPayload(challenge, number);

      if (!mounted) return;
      setState(() {
        _isVerified = true;
        _isVerifying = false;
      });
      widget.onVerified(payload);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _isVerified = false;
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
