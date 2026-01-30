import 'package:flutter/material.dart';
import '../../theme/elder_colors.dart';
import 'mfa_input.dart';

/// MFA verification dialog.
///
/// Displays a 6-digit code input, optional "Remember Device" checkbox,
/// and verify/cancel buttons.
class MFAModal extends StatefulWidget {
  const MFAModal({
    super.key,
    required this.onVerify,
    this.onCancel,
    this.codeLength = 6,
    this.allowRememberDevice = true,
    this.errorMessage,
  });

  final void Function(String code, bool rememberDevice) onVerify;
  final VoidCallback? onCancel;
  final int codeLength;
  final bool allowRememberDevice;
  final String? errorMessage;

  /// Show MFA modal as a dialog.
  static Future<void> show({
    required BuildContext context,
    required void Function(String code, bool rememberDevice) onVerify,
    VoidCallback? onCancel,
    int codeLength = 6,
    bool allowRememberDevice = true,
    String? errorMessage,
  }) {
    return showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => MFAModal(
        onVerify: onVerify,
        onCancel: onCancel ?? () => Navigator.of(context).pop(),
        codeLength: codeLength,
        allowRememberDevice: allowRememberDevice,
        errorMessage: errorMessage,
      ),
    );
  }

  @override
  State<MFAModal> createState() => _MFAModalState();
}

class _MFAModalState extends State<MFAModal> {
  String _code = '';
  bool _rememberDevice = false;
  bool _isVerifying = false;

  void _handleComplete(String code) {
    setState(() => _code = code);
  }

  void _handleVerify() {
    if (_code.length != widget.codeLength) return;
    setState(() => _isVerifying = true);
    widget.onVerify(_code, _rememberDevice);
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: ElderColors.slate800,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: ElderColors.slate700),
      ),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Lock icon
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                color: ElderColors.amber500.withAlpha(25),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.lock_outline,
                color: ElderColors.amber500,
                size: 28,
              ),
            ),
            const SizedBox(height: 16),

            // Title
            const Text(
              'Two-Factor Authentication',
              style: TextStyle(
                color: ElderColors.amber400,
                fontSize: 18,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 8),

            // Description
            const Text(
              'Enter the verification code from your authenticator app.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: ElderColors.slate400,
                fontSize: 14,
              ),
            ),
            const SizedBox(height: 24),

            // MFA Input
            MFAInput(
              length: widget.codeLength,
              onCompleted: _handleComplete,
              onChanged: (code) => setState(() => _code = code),
            ),
            const SizedBox(height: 16),

            // Error message
            if (widget.errorMessage != null) ...[
              Text(
                widget.errorMessage!,
                style: const TextStyle(
                  color: ElderColors.red400,
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 12),
            ],

            // Remember device
            if (widget.allowRememberDevice) ...[
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Checkbox(
                    value: _rememberDevice,
                    activeColor: ElderColors.amber500,
                    checkColor: ElderColors.slate900,
                    onChanged: (v) =>
                        setState(() => _rememberDevice = v ?? false),
                  ),
                  const Text(
                    'Remember this device for 30 days',
                    style: TextStyle(
                      color: ElderColors.slate400,
                      fontSize: 13,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
            ],

            // Buttons
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                OutlinedButton(
                  onPressed: _isVerifying ? null : widget.onCancel,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: ElderColors.slate300,
                    side: const BorderSide(color: ElderColors.slate600),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 12,
                    ),
                  ),
                  child: const Text('Cancel'),
                ),
                const SizedBox(width: 12),
                ElevatedButton(
                  onPressed: (_isVerifying ||
                          _code.length != widget.codeLength)
                      ? null
                      : _handleVerify,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: ElderColors.amber500,
                    foregroundColor: ElderColors.slate900,
                    disabledBackgroundColor: ElderColors.slate600,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 12,
                    ),
                  ),
                  child: _isVerifying
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: ElderColors.slate300,
                          ),
                        )
                      : const Text('Verify'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
